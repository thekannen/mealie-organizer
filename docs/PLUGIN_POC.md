# Mealie UI Plugin PoC (No Fork)

[Overview](../README.md) | [Install](INSTALL.md) | [Tasks](TASKS.md)

This PoC overlays a parser companion page into Mealie without forking Mealie code.

It uses:

- `mealie-organizer` as a separate plugin API container (`TASK=plugin-server`)
- A lightweight gateway that injects one JS asset into Mealie HTML responses
- An admin-only companion page at `/mo-plugin/page`

## What It Does

- Adds an `Organizer` button to Mealie's top bar
- Uses `/mo-plugin/api/v1/auth/context` so the top-bar button only renders for admins
- Serves a styled parser companion page that matches Mealie-like colors/spacing
- Allows a single active parser run at a time
- Runs parser in **dry-run only** mode from the companion page
- Shows status and summary counters

## 1) Start Organizer Plugin Server

Run organizer with plugin mode enabled:

```bash
docker compose run --rm -e TASK=plugin-server -e RUN_MODE=once -e PLUGIN_BIND_PORT=9102 -p 9102:9102 mealie-organizer
```

For long-running deployment, add a dedicated compose service with `TASK=plugin-server`.

## 2) Generate Gateway + Injection Files

If `mealie-organizer` is not present on the Mealie host, use curl to download and run the bootstrap script directly from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/bootstrap_mealie_plugin.sh -o /tmp/bootstrap_mealie_plugin.sh
bash /tmp/bootstrap_mealie_plugin.sh --project-root auto
```

This path does not require a pre-existing local clone. If `git` is unavailable, the bootstrap script falls back to a GitHub source archive download.

Or if you already have this repo locally on that host:

```bash
bash scripts/install/bootstrap_mealie_plugin.sh --project-root /path/to/mealie-stack
```

`--project-root auto` tries to discover the right directory. Override with `--project-root <path>` when needed.

For this workflow, "stack directory" means the directory containing your active Mealie compose file
(`docker-compose.yml`, `docker-compose.yaml`, `compose.yaml`, or `compose.yml`) and typically its `.env`.

Generated output:

- `/path/to/mealie-stack/mealie-plugin.config.json`
- `/path/to/mealie-stack/mealie-plugin/nginx.conf`
- `/path/to/mealie-stack/mealie-plugin/compose.plugin-gateway.yml`
- `/path/to/mealie-stack/mealie-plugin/README.generated.md`

`mealie-plugin.config.json` is intentionally root-level so operators can quickly adjust upstream URLs.

## 3) Wire Gateway Into Deployment

Follow commands in `mealie-plugin/README.generated.md`.

Important:

- The gateway should own the public Mealie URL/port.
- Mealie itself must remain reachable from the gateway as an internal upstream.
- Organizer plugin server must be reachable from the gateway for `/mo-plugin/*`.

## 4) Verify

1. Open Mealie using the same public URL/port as before.
2. Confirm `Organizer` appears in top bar when logged in as admin.
3. Open `/mo-plugin/page`.
4. Start dry-run parser and watch status update.

## Security Model

- Plugin endpoints validate user session token against Mealie `/api/users/self`
- Admin role is enforced server-side
- Non-admin or missing token requests are denied
