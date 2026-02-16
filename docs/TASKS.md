# Tasks and API

## Web UI Route Model

- Web app: `/cookdex`
- API: `/cookdex/api/v1`

## API Endpoints

- `GET /cookdex/api/v1/health`
- `POST /cookdex/api/v1/auth/login`
- `POST /cookdex/api/v1/auth/logout`
- `GET /cookdex/api/v1/auth/session`
- `GET /cookdex/api/v1/tasks`
- `POST /cookdex/api/v1/runs`
- `GET /cookdex/api/v1/runs`
- `GET /cookdex/api/v1/runs/{run_id}`
- `GET /cookdex/api/v1/runs/{run_id}/log`
- `POST /cookdex/api/v1/runs/{run_id}/cancel`
- `GET /cookdex/api/v1/schedules`
- `POST /cookdex/api/v1/schedules`
- `PATCH /cookdex/api/v1/schedules/{schedule_id}`
- `DELETE /cookdex/api/v1/schedules/{schedule_id}`
- `GET /cookdex/api/v1/settings`
- `PUT /cookdex/api/v1/settings`
- `GET /cookdex/api/v1/policies`
- `PUT /cookdex/api/v1/policies`
- `GET /cookdex/api/v1/config/files`
- `GET /cookdex/api/v1/config/files/{name}`
- `PUT /cookdex/api/v1/config/files/{name}`

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

`.env`-style runtime values are managed in the Web UI through `GET/PUT /cookdex/api/v1/settings`.

- Non-secret keys are stored in app settings.
- Secret keys are encrypted at rest.
- Task executions consume the effective runtime environment built from these values.

## Safety Policies

Dangerous options are blocked by default and unlocked per task via policy settings.