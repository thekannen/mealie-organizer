# Tasks and API

## Runtime Mode

Primary service mode:

```bash
TASK=webui-server
RUN_MODE=once
```

Deprecated compatibility alias (one release):

```bash
TASK=plugin-server
```

## Web UI Routes

All routes are under `/organizer`.

- UI shell: `/organizer`
- Login page: `/organizer/login`
- API root: `/organizer/api/v1`

## API Surface

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

## Task IDs

The queue runner supports:

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

## Safety Policies

Dangerous write options are blocked by default.

Use `PUT /organizer/api/v1/policies` to allow dangerous options per task:

```json
{
  "policies": {
    "ingredient-parse": {
      "allow_dangerous": true
    }
  }
}
```

## Settings and Secrets

- Non-secret values live in `app_settings` (SQLite)
- Secrets live in `secrets` (encrypted with `MO_WEBUI_MASTER_KEY`)
- Runtime env overlay uses uppercase keys from settings/secrets

## Scheduling

Schedules are created through `/organizer/api/v1/schedules`.

Kinds:
- `interval` (`seconds`)
- `cron` (`cron` expression)

Schedules enqueue runs into the same queue worker used by manual runs.

## Legacy CLI Notes

Legacy one-shot task switching is still available for migration windows:

```bash
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer
```

This is deprecated in docs and UI-first operation is the intended path.