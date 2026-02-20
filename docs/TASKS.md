# Tasks and API

## Web UI Route Model

- Web app: `/cookdex`
- API: `/cookdex/api/v1`

## API Endpoints

**Auth**
- `GET /auth/bootstrap-status`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`

**Tasks and Runs**
- `GET /tasks`
- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/log`
- `POST /runs/{run_id}/cancel`

**Policies**
- `GET /policies`
- `PUT /policies`

**Schedules**
- `GET /schedules`
- `POST /schedules`
- `PATCH /schedules/{schedule_id}`
- `DELETE /schedules/{schedule_id}`

**Settings**
- `GET /settings`
- `PUT /settings`
- `POST /settings/test/mealie`
- `POST /settings/test/openai`
- `POST /settings/test/ollama`

**Users**
- `GET /users`
- `POST /users`
- `POST /users/{username}/reset-password`
- `DELETE /users/{username}`

**Config Files**
- `GET /config/files`
- `GET /config/files/{name}`
- `PUT /config/files/{name}`

**Meta**
- `GET /health`
- `GET /metrics/overview`
- `GET /about/meta`
- `GET /help/docs`

All endpoints above are prefixed with `/cookdex/api/v1`.

## Task IDs (Queue Runner)

- `categorize`
- `taxonomy-refresh`
- `taxonomy-audit`
- `cookbook-sync`
- `ingredient-parse`
- `foods-cleanup`
- `units-cleanup`
- `labels-sync`
- `tools-sync`
- `data-maintenance`

## Environment Variable Management

Runtime values are managed in the Web UI through `GET/PUT /settings`.

- Non-secret keys are stored in app settings.
- Secret keys are encrypted at rest.
- Task executions consume the effective runtime environment built from these values.

## Safety Policies

Dangerous options are blocked by default and unlocked per task via `PUT /policies`.
