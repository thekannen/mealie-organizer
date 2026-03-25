# Direct DB Access

CookDex can read and write the Mealie database directly for bulk operations, bypassing the HTTP API entirely. This is an optional feature used by the `health-check`, `yield-normalize`, `tag-categorize`, `slug-repair`, and `reimport-recipes` tasks.

## Why Use It

| | API mode | DB mode |
|---|---|---|
| `health-check` on 3000 recipes | ~5–10 min (N API calls + nutrition sampling) | ~2 sec (single JOIN query) |
| `yield-normalize` on 3000 recipes | ~30 min (3000 PATCH calls) | ~3 sec (single transaction) |
| Nutrition coverage | Estimated from sample | Exact from `recipe_nutrition` table |

## Quick Setup (Wizard)

The fastest way to get Direct DB working. SSH into the machine running CookDex and run:

```bash
docker cp cookdex:/app/scripts/setup-db-tunnel.sh /tmp/setup-db-tunnel.sh && bash /tmp/setup-db-tunnel.sh
```

The wizard will:

1. Ask for your Mealie host IP and SSH user
2. Generate an SSH key and copy it to the Mealie host (you'll enter the password once)
3. Enable the volume mount in your compose file
4. Save the SSH settings directly into CookDex
5. Restart the container

When it's done, open CookDex **Settings** → click **Auto-detect DB** → click **Apply Changes**. That's it.

## Manual Setup (Step-by-Step)

If you prefer to set things up by hand, or the wizard doesn't work for your environment, follow these steps.

### 1. Generate an SSH key

SSH into your CookDex Docker host (the machine running `docker compose`). Then generate a dedicated key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/cookdex_mealie -N ""
```

This creates two files: `~/.ssh/cookdex_mealie` (private key) and `~/.ssh/cookdex_mealie.pub` (public key).

Now copy the **public** key to your Mealie host. Replace `your_ssh_user` with the SSH user on that machine and `192.168.1.100` with the Mealie host's IP:

```bash
ssh-copy-id -i ~/.ssh/cookdex_mealie.pub your_ssh_user@192.168.1.100
```

It will ask for that user's password one time. After that, verify the key works (should print `OK` with no password prompt):

```bash
ssh -i ~/.ssh/cookdex_mealie your_ssh_user@192.168.1.100 echo OK
```

### 2. Mount the key into Docker

The SSH key lives on the host, but CookDex runs inside a Docker container where host files aren't visible. You need to mount the key file as a volume.

Open your CookDex `compose.yaml` (or `compose.ghcr.yml`) — this is in the same directory where you ran `docker compose up`. The SSH key volume line is **already there but commented out**:

```yaml
    volumes:
      - ./cache:/app/cache
      - ./logs:/app/logs
      - ./reports:/app/reports
      # To enable Direct DB tunnel access, mount your SSH key (read-only is fine):
      # - ~/.ssh/cookdex_mealie:/app/.ssh/cookdex_mealie:ro
```

**Uncomment** the last line by removing the `#`:

```yaml
      - ~/.ssh/cookdex_mealie:/app/.ssh/cookdex_mealie:ro
```

Save the file, then recreate the container:

```bash
docker compose up -d cookdex
```

### 3. Configure SSH in Settings

Open CookDex in your browser and go to **Settings**. Expand the **Direct DB** section and fill in three fields:

| Setting | What to enter |
|---|---|
| **SSH Tunnel Host** | The IP or hostname of your Mealie server (e.g. `192.168.1.100`) — the same address you used in `ssh-copy-id` above |
| **SSH Tunnel User** | The SSH user on that host (e.g. `your_user`) — the same user you used in `ssh-copy-id` above |
| **SSH Key Path** | Leave the default `/app/.ssh/cookdex_mealie` — this is the **container** path where you mounted the key, not the host path |

Click **Apply Changes**.

### 4. Auto-detect credentials

In the **Connection Tests** sidebar, click **Auto-detect DB**. CookDex will SSH into your Mealie host, find the running Mealie container (or config files), and fill in the DB Type, host, port, database name, user, and password automatically.

Review the populated fields, then click **Apply Changes** again.

### 5. Test the connection

Click **Test DB** in the Connection Tests sidebar. You should see a success message with your group ID.

### 6. Use it

When queuing `health-check`, `yield-normalize`, `tag-categorize`, `slug-repair`, or `reimport-recipes`, enable the **Use Direct DB** toggle. The task will open a tunnel (if configured), run the query/transaction, and close the tunnel automatically.

---

## Manual Setup

If auto-detect doesn't work for your setup, or you prefer to configure credentials directly, follow these steps instead.

### Prerequisites

All DB dependencies (`psycopg2-binary`, `sshtunnel`, `paramiko`) are included in the Docker image — no extra installation needed. For local/non-Docker development, install them with:

```bash
pip install 'cookdex[db]'
```

### Configuration

All DB settings are managed in the **Settings** page under the **Direct DB** group. They can also be pre-seeded via `.env` (see `.env.example`). Set **DB Type** to enable DB access; leave it blank to keep API-only mode.

#### PostgreSQL via SSH tunnel

Use this when Mealie's PostgreSQL only listens on `localhost` of the remote host (the most common Docker/self-hosted setup). CookDex opens the tunnel automatically.

| Setting | `.env` key | Example |
|---|---|---|
| DB Type | `MEALIE_DB_TYPE` | `postgres` |
| Postgres Host | `MEALIE_PG_HOST` | `localhost` |
| Postgres Port | `MEALIE_PG_PORT` | `5432` |
| Postgres Database | `MEALIE_PG_DB` | `mealie_db` |
| Postgres User | `MEALIE_PG_USER` | `mealie__user` |
| Postgres Password | `MEALIE_PG_PASS` | *(your password)* |
| SSH Tunnel Host | `MEALIE_DB_SSH_HOST` | `192.168.1.100` |
| SSH Tunnel User | `MEALIE_DB_SSH_USER` | `root` |
| SSH Key Path | `MEALIE_DB_SSH_KEY` | `/app/.ssh/cookdex_mealie` |

See [Quick Setup](#quick-setup-auto-detect-via-ui) above for SSH key generation and Docker volume mounting.

#### PostgreSQL direct (no tunnel)

If PostgreSQL is reachable from your CookDex host directly (same machine, VPN, etc.), omit the SSH settings and point Postgres Host at the server:

| Setting | `.env` key | Example |
|---|---|---|
| DB Type | `MEALIE_DB_TYPE` | `postgres` |
| Postgres Host | `MEALIE_PG_HOST` | `192.168.1.100` |
| Postgres Port | `MEALIE_PG_PORT` | `5432` |
| Postgres Database | `MEALIE_PG_DB` | `mealie_db` |
| Postgres User | `MEALIE_PG_USER` | `mealie__user` |
| Postgres Password | `MEALIE_PG_PASS` | *(your password)* |

#### SQLite

For single-container Docker installs where Mealie uses SQLite:

| Setting | `.env` key | Example |
|---|---|---|
| DB Type | `MEALIE_DB_TYPE` | `sqlite` |
| SQLite Path | `MEALIE_SQLITE_PATH` | `/app/data/mealie.db` |

#### Finding your DB credentials manually

On the Mealie host, the credentials are in the Mealie environment file. For Docker Compose installs:

```bash
# Check the Mealie container's environment directly
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mealie

# Or grep the env file
grep POSTGRES /opt/mealie/mealie.env
# or
grep POSTGRES /path/to/mealie/.env
```

Look for `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.

## What It Accesses

CookDex only touches these tables and columns:

| Table | Columns read | Columns written |
|---|---|---|
| `recipes` | `id`, `slug`, `name`, `description`, `recipe_yield`, `recipe_yield_quantity`, `recipe_servings`, `prep_time`, `total_time`, `perform_time`, `cook_time`, `group_id` | `recipe_yield`, `recipe_yield_quantity`, `recipe_servings` |
| `recipe_nutrition` | `calories` | — |
| `recipes_to_tags` | `tag_id` (count) | — |
| `recipes_to_categories` | `category_id` (count) | — |
| `recipes_to_tools` | `tool_id` (count) | — |
| `recipes_ingredients` | `id`, `food_id` (count where not null) | — |
| `groups` | `id` | — |
| `users` | `group_id` | — |

All queries are parameterized. No raw string interpolation of user data.
