# Mealie Organizer

[Overview](README.md) | [Install](docs/INSTALL.md) | [Getting Started](docs/GETTING_STARTED.md) | [Update](docs/UPDATE.md)

Mealie Organizer now runs as a standalone Web UI service.

- URL base: `/organizer`
- Default port: `4820`
- Primary runtime mode: `TASK=webui-server`
- Control plane: runs, schedules, policies, settings, secrets, and config-file editing are all Web UI first.

## Quick Start (Docker)

```bash
mkdir -p mealie-organizer && cd mealie-organizer
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/compose.ghcr.yml -o compose.yaml

# edit .env at minimum:
#   MEALIE_URL
#   MEALIE_API_KEY
#   WEB_BOOTSTRAP_PASSWORD
#   MO_WEBUI_MASTER_KEY

docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d mealie-organizer
```

Open: `http://localhost:4820/organizer`

## Bootstrap Script (No Repo Clone Required)

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/bootstrap_webui.sh -o /tmp/bootstrap_webui.sh
bash /tmp/bootstrap_webui.sh --output-dir ./mealie-organizer-webui --web-port 4820
```

The generated folder includes `.env`, `docker-compose.yml`, and `README.generated.md`.

## Web UI API (Internal/LAN)

All API routes are under `/organizer/api/v1`.

- Auth: `/auth/login`, `/auth/logout`, `/auth/session`
- Tasks/Runs: `/tasks`, `/runs`, `/runs/{id}`, `/runs/{id}/log`
- Schedules: `/schedules`
- Policies: `/policies`
- Settings/Secrets: `/settings`
- Config file parity: `/config/files`, `/config/files/{name}`

## Default Environment

See `.env.example` for the full set.

Required at minimum:
- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

Key defaults:
- `WEB_BIND_PORT=4820`
- `WEB_BASE_PATH=/organizer`
- `WEB_STATE_DB_PATH=cache/webui/state.db`

## Legacy CLI Compatibility

Task-switch execution is retained as a compatibility path for one release.

- New primary task: `TASK=webui-server`
- Deprecated alias: `TASK=plugin-server` (forwards to `webui-server` with warning)

## Testing

```bash
python -m pytest
```