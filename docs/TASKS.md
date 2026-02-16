# Tasks and API

## Web UI Route Model

- Web app: `/organizer`
- API: `/organizer/api/v1`

## API Endpoints

- `GET /organizer/api/v1/health`
- `POST /organizer/api/v1/auth/login`
- `POST /organizer/api/v1/auth/logout`
- `GET /organizer/api/v1/auth/session`
- `GET /organizer/api/v1/tasks`
- `POST /organizer/api/v1/runs`
- `GET /organizer/api/v1/runs`
- `GET /organizer/api/v1/runs/{run_id}`
- `GET /organizer/api/v1/runs/{run_id}/log`
- `POST /organizer/api/v1/runs/{run_id}/cancel`
- `GET /organizer/api/v1/schedules`
- `POST /organizer/api/v1/schedules`
- `PATCH /organizer/api/v1/schedules/{schedule_id}`
- `DELETE /organizer/api/v1/schedules/{schedule_id}`
- `GET /organizer/api/v1/settings`
- `PUT /organizer/api/v1/settings`
- `GET /organizer/api/v1/policies`
- `PUT /organizer/api/v1/policies`
- `GET /organizer/api/v1/config/files`
- `GET /organizer/api/v1/config/files/{name}`
- `PUT /organizer/api/v1/config/files/{name}`

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

`.env`-style runtime values are managed in the Web UI through `GET/PUT /organizer/api/v1/settings`.

- Non-secret keys are stored in app settings.
- Secret keys are encrypted at rest.
- Task executions consume the effective runtime environment built from these values.

## Safety Policies

Dangerous options are blocked by default and unlocked per task via policy settings.