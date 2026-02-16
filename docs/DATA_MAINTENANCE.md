# Data Maintenance Pipeline

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

`data-maintenance` orchestrates a full hygiene pass:

`parse -> foods -> units -> taxonomy -> categorize -> cookbooks -> audit`

## Web UI Workflow (Primary)

1. Open `/organizer`
2. Run `data-maintenance` from **Run Task** with `dry_run=true`
3. Review run logs and reports
4. If needed, enable dangerous policy for `data-maintenance`
5. Re-run with `apply_cleanups=true`

## Scheduling

Use **Schedules** in the UI to run maintenance automatically.

- `interval`: every N seconds
- `cron`: standard 5-field expression

## Safety Model

- Dangerous options are blocked by default.
- Per-task policy controls dangerous options (`allow_dangerous`).
- `dry_run=true` remains recommended for initial validation cycles.

## Legacy CLI Compatibility (Deprecated)

```bash
docker compose run --rm -e TASK=data-maintenance -e RUN_MODE=once mealie-organizer
```

Apply cleanups:

```bash
docker compose run --rm -e TASK=data-maintenance -e MAINTENANCE_APPLY_CLEANUPS=true -e RUN_MODE=once mealie-organizer
```