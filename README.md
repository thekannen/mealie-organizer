# CookDex

Web UI-first automation service for [Mealie](https://mealie.io). Manage recipe taxonomy, ingredient parsing, scheduled tasks, and runtime configuration from a single desktop-friendly interface.

## Quick Start

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
```

Edit `.env` with your values (at minimum `MEALIE_URL`, `MEALIE_API_KEY`, `WEB_BOOTSTRAP_PASSWORD`, and `MO_WEBUI_MASTER_KEY`), then start:

```bash
docker compose pull cookdex
docker compose up -d cookdex
```

Open `http://localhost:4820/cookdex` and log in with the bootstrap credentials.

## What It Does

| Feature | Description |
|---|---|
| Task runner | Queue one-off tasks with dry-run safety defaults |
| Scheduler | Interval and cron schedules managed in the UI |
| Taxonomy editing | Categories, tags, cookbooks, labels, tools, and units |
| Ingredient parsing | Multi-parser pipeline with confidence thresholds |
| Data maintenance | Staged cleanup pipeline across foods, units, and taxonomy |
| Settings | Runtime env vars and encrypted secrets managed in-app |
| User management | Multi-user auth with password complexity enforcement |

## Available Tasks

| Task ID | Purpose |
|---|---|
| `categorize` | Classify recipes using the configured AI provider |
| `taxonomy-refresh` | Sync categories and tags from config files |
| `taxonomy-audit` | Generate taxonomy diagnostics report |
| `cookbook-sync` | Create/update cookbooks from config rules |
| `ingredient-parse` | Parse ingredients with parser fallback chain |
| `foods-cleanup` | Merge duplicate food entries |
| `units-cleanup` | Normalize unit aliases and merge duplicates |
| `labels-sync` | Create/delete labels from taxonomy config |
| `tools-sync` | Create/merge tools from taxonomy config |
| `data-maintenance` | Run full staged maintenance pipeline |

## API

All endpoints are under `/cookdex/api/v1`. Authentication is cookie-based.

<details>
<summary>Endpoint reference</summary>

**Auth**
- `GET /auth/bootstrap-status` — check if first-time setup is needed
- `POST /auth/register` — first-time admin registration
- `POST /auth/login` / `POST /auth/logout` / `GET /auth/session`

**Tasks and Runs**
- `GET /tasks` — list task definitions with policies
- `POST /runs` — queue a task run
- `GET /runs` / `GET /runs/{id}` / `GET /runs/{id}/log`
- `POST /runs/{id}/cancel`

**Policies**
- `GET /policies` / `PUT /policies` — manage safety policy overrides

**Schedules**
- `GET /schedules` / `POST /schedules`
- `PATCH /schedules/{id}` / `DELETE /schedules/{id}`

**Settings**
- `GET /settings` / `PUT /settings` — env vars and encrypted secrets
- `POST /settings/test/mealie` / `POST /settings/test/openai` / `POST /settings/test/ollama`

**Users**
- `GET /users` / `POST /users`
- `POST /users/{username}/reset-password` / `DELETE /users/{username}`

**Config Files**
- `GET /config/files` / `GET /config/files/{name}` / `PUT /config/files/{name}`

**Meta**
- `GET /health` / `GET /metrics/overview` / `GET /about/meta` / `GET /help/docs`

</details>

## Environment Variables

Required at startup (set in `.env`):

| Variable | Description |
|---|---|
| `MEALIE_URL` | Mealie API base URL (e.g. `http://mealie:9000/api`) |
| `MEALIE_API_KEY` | Mealie API key with write access |
| `WEB_BOOTSTRAP_PASSWORD` | Initial admin password (omit for first-time registration flow) |
| `MO_WEBUI_MASTER_KEY` | Fernet key for encrypting secrets at rest |

Optional (defaults shown):

| Variable | Default | Description |
|---|---|---|
| `WEB_BIND_HOST` | `0.0.0.0` | Server bind address |
| `WEB_BIND_PORT` | `4820` | Server port |
| `WEB_BASE_PATH` | `/cookdex` | URL base path |
| `WEB_BOOTSTRAP_USER` | `admin` | Bootstrap admin username |
| `WEB_COOKIE_SECURE` | `true` | Require HTTPS for session cookies |

After first login, provider keys and runtime settings can be managed from the Settings page.

## Docker Volumes

| Host path | Container path | Purpose |
|---|---|---|
| `./configs` | `/app/configs` | Taxonomy JSON files |
| `./cache` | `/app/cache` | SQLite state database |
| `./logs` | `/app/logs` | Task run logs |
| `./reports` | `/app/reports` | Audit/maintenance reports |

## Updating

```bash
docker compose pull cookdex
docker compose up -d --remove-orphans cookdex
```

Verify health after update:

```bash
curl http://localhost:4820/cookdex/api/v1/health
```

## Documentation

- [Install](docs/INSTALL.md) — full deployment walkthrough
- [Getting Started](docs/GETTING_STARTED.md) — first login and first task run
- [Tasks](docs/TASKS.md) — task reference and safety policies
- [Data Maintenance](docs/DATA_MAINTENANCE.md) — staged cleanup pipeline
- [Parser Migration](docs/PARSER_MIGRATION.md) — migrating from standalone parser

## Testing

```bash
python -m pytest
```

## Local Web UI QA Loop

```bash
python scripts/qa/run_local_webui_qa.py --iterations 3
```

Artifacts are written to `reports/qa/loop-*/` with smoke test results, screenshots, and server logs.
