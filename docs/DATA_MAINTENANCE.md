# Data Maintenance Pipeline

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

`data-maintenance` orchestrates a full data hygiene pass for Mealie:

`parse -> foods -> units -> taxonomy -> categorize -> cookbooks -> audit`

## Safety Model

- Default mode is audit-first.
- Cleanup stages (`foods`, `units`, `labels`, `tools`) plan actions unless explicitly switched to apply.
- Global `DRY_RUN=true` always forces plan-only behavior.

## Default Run

```bash
docker compose run --rm -e TASK=data-maintenance -e RUN_MODE=once mealie-organizer
```

## Apply Cleanup Writes

```bash
docker compose run --rm \
  -e TASK=data-maintenance \
  -e RUN_MODE=once \
  -e MAINTENANCE_APPLY_CLEANUPS=true \
  mealie-organizer
```

## Stage Selection

Run only selected stages:

```bash
docker compose run --rm --entrypoint python mealie-organizer \
  -m mealie_organizer.data_maintenance \
  --stages parse,foods,units,audit
```

Continue after failures:

```bash
docker compose run --rm --entrypoint python mealie-organizer \
  -m mealie_organizer.data_maintenance \
  --continue-on-error
```

## Incremental Cleanup Strategy

- `maintenance.max_actions_per_stage` controls maximum merges per run.
- `maintenance.checkpoint_dir` stores per-stage merge checkpoints.
- Run repeatedly until reports show no remaining candidates.

## Checkpoint Reset

To restart a stage from scratch, remove its checkpoint file:

- Foods: `cache/maintenance/foods_cleanup_checkpoint.json`
- Units: `cache/maintenance/units_cleanup_checkpoint.json`
- Tools: `cache/maintenance/tools_sync_checkpoint.json`

## Rollback Guidance

- Use dry-run reports before apply mode.
- Keep conservative caps (`MAX_ACTIONS_PER_STAGE`) during first apply cycles.
- If an apply run is too aggressive:
  - disable apply flags
  - inspect generated reports
  - restore from Mealie backup if needed
