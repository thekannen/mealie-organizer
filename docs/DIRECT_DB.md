# Direct DB Access

CookDex can read and write the Mealie database directly for bulk operations, bypassing the HTTP API entirely. This is an optional feature used by the `health-check`, `yield-normalize`, and `tag-categorize` tasks.

## Why Use It

| | API mode | DB mode |
|---|---|---|
| `health-check` on 3000 recipes | ~5–10 min (N API calls + nutrition sampling) | ~2 sec (single JOIN query) |
| `yield-normalize` on 3000 recipes | ~30 min (3000 PATCH calls) | ~3 sec (single transaction) |
| Nutrition coverage | Estimated from sample | Exact from `recipe_nutrition` table |

## Prerequisites

Install the `db` extras:

```bash
pip install 'cookdex[db]'
```

This adds:
- `psycopg2-binary` — PostgreSQL driver
- `sshtunnel` — automatic SSH port forwarding
- `paramiko>=2.11,<4` — SSH transport (pinned; paramiko 4.x breaks sshtunnel)

For SQLite-based Mealie installs only `psycopg2-binary` can be omitted; the standard library `sqlite3` module is used instead.

## Configuration

All DB settings go in `.env`. Set `MEALIE_DB_TYPE` to enable DB access; leave it unset to keep API-only mode.

### PostgreSQL via auto SSH tunnel

Use this when Mealie's PostgreSQL only listens on `localhost` of the remote host (the most common Docker/self-hosted setup).

CookDex opens the tunnel automatically — no manual `ssh -N -L` command needed.

```
MEALIE_DB_TYPE=postgres

# PostgreSQL connection details (relative to the remote host)
MEALIE_PG_HOST=localhost
MEALIE_PG_PORT=5432
MEALIE_PG_DB=mealie_db
MEALIE_PG_USER=mealie__user
MEALIE_PG_PASS=your_mealie_db_password

# SSH tunnel target
MEALIE_DB_SSH_HOST=192.168.1.100     # IP or hostname of the Mealie server
MEALIE_DB_SSH_USER=your_ssh_user     # SSH user on that host
MEALIE_DB_SSH_KEY=/app/.ssh/cookdex_mealie   # container path to your private key
```

#### Generating the SSH key

On the **Docker host** (not inside the container):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/cookdex_mealie -N ""
```

Copy the public key to the Mealie host's `authorized_keys`:

```bash
ssh-copy-id -i ~/.ssh/cookdex_mealie.pub your_ssh_user@192.168.1.100
# or manually:
cat ~/.ssh/cookdex_mealie.pub | ssh your_ssh_user@192.168.1.100 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Verify access from the Docker host:

```bash
ssh -i ~/.ssh/cookdex_mealie your_ssh_user@192.168.1.100 echo OK
```

#### Mounting the key into Docker

The SSH key lives on the host filesystem, but CookDex runs inside a container where host paths like `~/.ssh/` are not visible. You must mount the key file as a volume.

Add this line to the `volumes:` section of your `compose.yaml`:

```yaml
volumes:
  - ~/.ssh/cookdex_mealie:/app/.ssh/cookdex_mealie
```

Then recreate the container:

```bash
docker compose up -d cookdex
```

In CookDex Settings (or `.env`), use the **container** path `/app/.ssh/cookdex_mealie` — not the host path `~/.ssh/cookdex_mealie`.

#### Finding your DB credentials

On the Mealie host, the credentials are in the Mealie environment file. For Docker Compose installs this is typically:

```bash
grep POSTGRES /opt/mealie/mealie.env
# or
grep POSTGRES /path/to/mealie/.env
```

Look for `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.

### PostgreSQL direct (no tunnel)

If PostgreSQL is reachable from your machine directly (same host, VPN, etc.), omit `MEALIE_DB_SSH_HOST` and point `MEALIE_PG_HOST` at the server:

```
MEALIE_DB_TYPE=postgres
MEALIE_PG_HOST=192.168.1.100
MEALIE_PG_PORT=5432
MEALIE_PG_DB=mealie_db
MEALIE_PG_USER=mealie__user
MEALIE_PG_PASS=your_mealie_db_password
```

### SQLite

For single-container Docker installs where Mealie uses SQLite:

```
MEALIE_DB_TYPE=sqlite
MEALIE_SQLITE_PATH=/app/data/mealie.db   # path visible to cookdex
```

## Using DB Mode

### In the Web UI

When queuing `health-check`, `yield-normalize`, or `tag-categorize` (rule-based method), enable the **Use Direct DB** toggle. The task will open a tunnel (if configured), run the query/transaction, and close the tunnel automatically.

### From the CLI

```bash
python -m cookdex.recipe_quality_audit --use-db
python -m cookdex.yield_normalizer --use-db --apply
```

## Smoke Test

Verify connectivity before running a full task:

```python
from cookdex.db_client import MealieDBClient

with MealieDBClient() as db:
    rows = db.get_recipe_rows()
    print(f"Connected — {len(rows)} recipes found")
```

## What It Accesses

CookDex only touches these tables and columns:

| Table | Columns read | Columns written |
|---|---|---|
| `recipes` | `id`, `slug`, `name`, `description`, `recipe_yield`, `recipe_yield_quantity`, `recipe_servings`, `prep_time`, `total_time`, `perform_time`, `cook_time`, `group_id` | `recipe_yield`, `recipe_yield_quantity`, `recipe_servings` |
| `recipe_nutrition` | `calories` | — |
| `recipes_to_tags` | `tag_id` (count) | — |
| `recipes_to_categories` | `category_id` (count) | — |
| `recipes_to_tools` | `tool_id` (count) | — |
| `groups` | `id` | — |
| `users` | `group_id` | — |

All queries are parameterized. No raw string interpolation of user data.
