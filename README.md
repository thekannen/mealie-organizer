# CookDex

CookDex is a Web UI-first automation service for Mealie.

- Web UI base path: `/cookdex`
- Default port: `4820`
- Deployment standard: GHCR image

## Deploy (GHCR Standard)

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml

# edit .env at minimum:
#   MEALIE_URL
#   MEALIE_API_KEY
#   WEB_BOOTSTRAP_PASSWORD
#   MO_WEBUI_MASTER_KEY

docker compose -f compose.yaml pull cookdex
docker compose -f compose.yaml up -d cookdex
```

Open: `http://localhost:4820/cookdex`

## Web UI Responsibilities

The Web UI is the standard control surface for:

- Task runs and run logs
- Scheduling (interval and cron)
- Safety policy bypasses per task
- Runtime environment variables (managed in-app)
- Secrets (encrypted at rest)
- Config/taxonomy JSON file editing

## API (Internal/LAN)

All API routes are under `/cookdex/api/v1`.

- Auth: `/auth/login`, `/auth/logout`, `/auth/session`
- Tasks/runs: `/tasks`, `/runs`, `/runs/{id}`, `/runs/{id}/log`
- Scheduling: `/schedules`
- Policies: `/policies`
- Settings/env/secrets: `/settings`
- Config files: `/config/files`, `/config/files/{name}`

## Environment Bootstrap

Required startup values:

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

After first login, runtime `.env`-style variables are configurable from the Web UI.

## Docs

- `docs/INSTALL.md`
- `docs/GETTING_STARTED.md`
- `docs/TASKS.md`
- `docs/UPDATE.md`
- `docs/docker-ghcr.md`

## Testing

```bash
python -m pytest
```

## Local Web UI QA Loop

Run the full local verification loop (build -> start -> browser click-through -> analyze) using your `.env` values:

```bash
python scripts/qa/run_local_webui_qa.py --iterations 3
```

Artifacts are written to `reports/qa/loop-*/` with:
- `smoke/report.json` (per-check results)
- `smoke/screenshots/` (page and failure captures)
- `server.log` (backend runtime log)
