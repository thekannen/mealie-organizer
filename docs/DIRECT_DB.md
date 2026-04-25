# Direct DB Access

Direct DB is an optional faster path for operations that are slow or impossible through Mealie's HTTP API. CookDex can connect to Mealie's PostgreSQL database directly, or to SQLite in advanced local setups.

The normal API path still works. Only enable Direct DB when you understand which database CookDex should reach.

## When CookDex Uses Direct DB

| Area | How Direct DB is used |
|---|---|
| `health-check` | Reads recipe, nutrition, ingredient, category, tag, and tool data in one query. |
| `yield-normalize` | Writes yield and servings changes in a single transaction when **Use Direct DB** is enabled. |
| `tag-categorize` | Enables ingredient and tool matching for rule-based organization; live runs can write tag/category/tool links. |
| `slug-repair` | Required for live slug fixes because Mealie's API cannot update mismatched slugs. |
| `clean-recipes` | Optional fallback for deleting corrupted duplicate recipes when the API delete path fails. |
| `reimport-recipes` | Uses a DB slug-repair fallback automatically if Direct DB is configured and Mealie rejects a reimport update with a 403. |

For `data-maintenance`, the `use_db` option applies to the `quality` and `yield` stages.

## Why Use It

| Operation | API mode | DB mode |
|---|---|---|
| Large `health-check` | Many API calls plus nutrition sampling | Single read query with exact nutrition coverage |
| Large `yield-normalize` live run | One API patch per recipe | One database transaction |
| Rule-based ingredient/tool matching | Not available from API list data | Available through parsed ingredient and instruction tables |
| Slug mismatch repair | API cannot write the needed slug change | Direct recipe row update |

## Quick Setup For PostgreSQL Over SSH

Use this when CookDex and Mealie run on a Docker host and Mealie's PostgreSQL is reachable only from that host.

SSH into the machine running CookDex and run:

```bash
docker cp cookdex:/app/scripts/setup-db-tunnel.sh /tmp/setup-db-tunnel.sh && bash /tmp/setup-db-tunnel.sh
```

The wizard will:

1. Ask for your Mealie host IP and SSH user.
2. Generate a dedicated SSH key.
3. Copy the public key to the Mealie host.
4. Enable the Docker volume mount for the private key.
5. Save SSH settings into CookDex.
6. Restart the CookDex container.

After it finishes:

1. Open CookDex **Settings**.
2. Click **Auto-detect DB**.
3. Review the detected Postgres values.
4. Click **Apply Changes**.
5. Click **Test DB**.

The wizard only needs to run once. CookDex opens and closes the SSH tunnel for each task run.

## Manual PostgreSQL Setup

Use this when the wizard cannot modify your compose file, or when you prefer to manage the SSH key yourself.

### 1. Generate An SSH Key

On the Docker host running CookDex:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/cookdex_mealie -N ""
ssh-copy-id -i ~/.ssh/cookdex_mealie.pub your_ssh_user@192.168.1.100
ssh -i ~/.ssh/cookdex_mealie your_ssh_user@192.168.1.100 echo OK
```

### 2. Mount The Key Into CookDex

Edit your CookDex `compose.yaml` and mount the private key into the container:

```yaml
services:
  cookdex:
    volumes:
      - ./cache:/app/cache
      - ./logs:/app/logs
      - ./reports:/app/reports
      - ~/.ssh/cookdex_mealie:/app/.ssh/cookdex_mealie:ro
```

Recreate the container:

```bash
docker compose up -d cookdex
```

### 3. Configure SSH Settings

Open **Settings -> Direct DB** and set:

| Setting | Example | Notes |
|---|---|---|
| SSH Tunnel Host | `192.168.1.100` | The host you used with `ssh-copy-id`. |
| SSH Tunnel User | `your_ssh_user` | The SSH user on that host. |
| SSH Key Path | `/app/.ssh/cookdex_mealie` | Container path, not host path. |

Click **Apply Changes**, then **Auto-detect DB**.

## Manual PostgreSQL Credentials

If auto-detect cannot find credentials, enter them manually in **Settings -> Direct DB**.

| Setting | Env key | Example |
|---|---|---|
| DB Type | `MEALIE_DB_TYPE` | `postgres` |
| Postgres Host | `MEALIE_PG_HOST` | `localhost` with SSH tunnel, or a reachable DB hostname |
| Postgres Port | `MEALIE_PG_PORT` | `5432` |
| Postgres Database | `MEALIE_PG_DB` | `mealie_db` |
| Postgres User | `MEALIE_PG_USER` | `mealie__user` |
| Postgres Password | `MEALIE_PG_PASS` | your Mealie DB password |
| SSH Tunnel Host | `MEALIE_DB_SSH_HOST` | optional |
| SSH Tunnel User | `MEALIE_DB_SSH_USER` | optional |
| SSH Key Path | `MEALIE_DB_SSH_KEY` | `/app/.ssh/cookdex_mealie` |

You can usually find Mealie's Postgres values in the Mealie compose environment:

```bash
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mealie
```

Look for `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_SERVER`, and `POSTGRES_PORT`.

## SQLite

Direct SQLite support exists in the low-level DB client, but the Web UI currently exposes only `MEALIE_DB_TYPE` for SQLite. The database path is env-only and defaults to `/app/data/mealie.db`.

For SQLite, set these in `.env` and make sure the Mealie database file is mounted into the CookDex container:

```bash
MEALIE_DB_TYPE=sqlite
MEALIE_SQLITE_PATH=/app/data/mealie.db
```

Then restart CookDex and use **Test DB**.

## Local Source Installs

The Docker image already includes PostgreSQL and SSH tunnel dependencies. For local source installs, install the optional DB extras:

```bash
pip install -e ".[db]"
```

## What CookDex Reads And Writes

CookDex uses parameterized SQL for Direct DB operations.

Direct DB reads can include recipe rows, nutrition rows, ingredient rows and foods, instruction rows, category/tag/tool link tables, groups, and users.

Direct DB writes are limited to the task being run:

- `yield-normalize`: recipe yield and servings fields
- `slug-repair`: recipe slug values
- `tag-categorize`: recipe-to-tag/category/tool links, and optional missing taxonomy rows when **Missing Target Handling** is set to create
- `clean-recipes`: duplicate recipe deletion fallback, including related recipe rows
- `reimport-recipes`: slug repair fallback only

Use dry runs first when a task offers them.
