# Mealie Organizer Tasks

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

This guide explains each task, the special switches, and when to use each mode.

## Runtime Model

Container task execution is driven by environment variables read by `scripts/docker/entrypoint.sh`:

- `TASK`: which task to run
- `RUN_MODE`: `once` or `loop`
- `RUN_INTERVAL_SECONDS`: loop sleep interval
- `PROVIDER`: optional one-run categorizer provider override
- `TAXONOMY_REFRESH_MODE`: taxonomy refresh strategy
- `CLEANUP_APPLY`: apply mode toggle for foods/units/labels/tools tasks
- `MAINTENANCE_APPLY_CLEANUPS`: apply mode toggle for cleanup stages in `data-maintenance`

Important defaults:

- Entrypoint default is `RUN_MODE=once`
- Compose files set `RUN_MODE=loop` by default
- `RUN_INTERVAL_SECONDS` default is `21600` (6 hours)

For advanced CLI flags not exposed by `TASK`, run the Python module directly with `--entrypoint python`.

## Task Matrix

| `TASK` value | Purpose | Entrypoint command | Default write behavior |
| --- | --- | --- | --- |
| `categorize` | Add categories/tags to recipes missing metadata | `python -m mealie_organizer.recipe_categorizer` | Writes changes unless `DRY_RUN=true` |
| `taxonomy-refresh` | Import categories/tags from JSON templates and run cleanup scan | `python -m mealie_organizer.taxonomy_manager refresh --mode ... --cleanup --cleanup-only-unused --cleanup-delete-noisy` | Imports write unless `DRY_RUN=true`; cleanup delete is plan-only by default |
| `taxonomy-audit` | Build taxonomy quality/usage report | `python -m mealie_organizer.audit_taxonomy` | Read-only (writes local report file) |
| `cookbook-sync` | Upsert cookbook definitions from JSON | `python -m mealie_organizer.cookbook_manager sync` | Writes changes unless `DRY_RUN=true` |
| `ingredient-parse` | Parse unparsed recipe ingredients into structured fields | `python -m mealie_organizer.ingredient_parser` | Writes patches unless `DRY_RUN=true` |
| `plugin-server` | Serve Mealie UI companion plugin endpoints/assets | `python -m mealie_organizer.plugin_server` | Read-only except parser dry-run execution state |
| `foods-cleanup` | Detect and merge duplicate foods conservatively | `python -m mealie_organizer.foods_manager cleanup` | Audit mode by default; apply with `CLEANUP_APPLY=true` |
| `units-cleanup` | Standardize units using alias map and merge actions | `python -m mealie_organizer.units_manager cleanup` | Audit mode by default; apply with `CLEANUP_APPLY=true` |
| `labels-sync` | Seed/sync labels catalog from config | `python -m mealie_organizer.labels_manager` | Audit mode by default; apply with `CLEANUP_APPLY=true` |
| `tools-sync` | Seed tools catalog and exact duplicate cleanup | `python -m mealie_organizer.tools_manager` | Audit mode by default; apply with `CLEANUP_APPLY=true` |
| `data-maintenance` | Run staged maintenance pipeline | `python -m mealie_organizer.data_maintenance` | Cleanup stages audit by default; apply with `MAINTENANCE_APPLY_CLEANUPS=true` |

## Global Switches

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `MEALIE_URL` | none | all tasks | Required. Must be your real Mealie API base URL. |
| `MEALIE_API_KEY` | none | all tasks | Required. |
| `DRY_RUN` | `false` | categorize, taxonomy manager, cookbook sync | Plans changes without sending write operations. |
| `TASK` | `categorize` | entrypoint | Task selector. |
| `RUN_MODE` | `loop` in compose | entrypoint | `once` runs a single pass, `loop` repeats forever. |
| `RUN_INTERVAL_SECONDS` | `21600` | entrypoint loop mode | Must be an integer. |
| `PLUGIN_BIND_HOST` | `0.0.0.0` | plugin-server | Bind host for plugin server. |
| `PLUGIN_BIND_PORT` | `9102` | plugin-server | Bind port for plugin server. |
| `PLUGIN_BASE_PATH` | `/mo-plugin` | plugin-server | URL prefix for plugin page/assets/API. |
| `PLUGIN_TOKEN_COOKIES` | `mealie.access_token,access_token` | plugin-server | Cookie names checked for Mealie session token. |
| `PLUGIN_AUTH_TIMEOUT_SECONDS` | `15` | plugin-server | Timeout when validating user/admin via Mealie API. |
| `PROVIDER` | empty | categorize task path | Docker-only override passed as `--provider` when `TASK=categorize`. |
| `TAXONOMY_REFRESH_MODE` | `merge` | taxonomy-refresh task path | `merge` or `replace`. |
| `CLEANUP_APPLY` | `false` | foods/units/labels/tools tasks | Enables write mode for those tasks when true. |
| `MAINTENANCE_APPLY_CLEANUPS` | `false` | data-maintenance task | Enables write mode for cleanup stages in the pipeline. |
| `MAINTENANCE_STAGES` | pipeline default | data-maintenance task | Override stage sequence with comma-separated list. |
| `MAX_ACTIONS_PER_STAGE` | `250` | foods/units/tools cleanup | Max merge actions per run. |
| `CHECKPOINT_DIR` | `cache/maintenance` | cleanup managers | Stores resume checkpoints. |
| `UNITS_ALIAS_FILE` | `configs/taxonomy/units_aliases.json` | units-cleanup | Alias map source file. |
| `LABELS_FILE` | `configs/taxonomy/labels.json` | labels-sync | Labels catalog source file. |
| `TOOLS_FILE` | `configs/taxonomy/tools.json` | tools-sync | Tools catalog source file. |

## Running Tasks

Use the compose command that matches your deployment layout:

```bash
# GHCR no-clone layout
docker compose -f compose.yaml run --rm -e TASK=categorize -e RUN_MODE=once mealie-organizer

# Repo-clone layout
docker compose run --rm -e TASK=categorize -e RUN_MODE=once mealie-organizer
```

Run any entrypoint task once:

If you use the GHCR no-clone layout, add `-f compose.yaml` to each command.

```bash
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=taxonomy-audit -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=ingredient-parse -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=plugin-server -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=foods-cleanup -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=units-cleanup -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=labels-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=tools-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=data-maintenance -e RUN_MODE=once mealie-organizer
```

## `categorize` Deep Dive

Default behavior:

- Processes recipes missing categories or missing tags (`missing-either`)
- Keeps existing metadata and only appends new matched category/tag values

Special switches:

- `PROVIDER=ollama|chatgpt` for one-run override through `TASK=categorize`
- `CATEGORIZER_PROVIDER=ollama|chatgpt` default provider if `PROVIDER`/CLI override is not used
- `--recat` reprocesses all recipes and rebuilds metadata for each recipe from model output
- `--missing-tags` only targets recipes with no tags
- `--missing-categories` only targets recipes with no categories
- `TAG_MAX_NAME_LENGTH` excludes long tags from prompt candidate list
- `TAG_MIN_USAGE` excludes rare tags from prompt candidate list
- `BATCH_SIZE` and `MAX_WORKERS` tune throughput/concurrency

Provider settings:

- Ollama: `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_REQUEST_TIMEOUT`, `OLLAMA_HTTP_RETRIES`, `OLLAMA_NUM_CTX`, `OLLAMA_TEMPERATURE`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TOP_P`, `OLLAMA_NUM_THREAD`
- ChatGPT-compatible: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_REQUEST_TIMEOUT`, `OPENAI_HTTP_RETRIES`

Advanced CLI examples (bypass entrypoint):

```bash
# Re-categorize everything once
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.recipe_categorizer --recat

# Only fill missing tags
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.recipe_categorizer --missing-tags

# Force provider for this command
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.recipe_categorizer --provider chatgpt
```

## `taxonomy-refresh` Deep Dive

Entrypoint task behavior:

- Imports `configs/taxonomy/categories.json`
- Imports `configs/taxonomy/tags.json`
- Uses `--mode` from `TAXONOMY_REFRESH_MODE` (`merge` or `replace`)
- Runs cleanup scan with:
  - `--cleanup`
  - `--cleanup-only-unused`
  - `--cleanup-delete-noisy`

Important detail:

- Entrypoint does not pass `--cleanup-apply`, so cleanup deletions are planned and printed, not deleted.

Special switches:

- `TAXONOMY_REFRESH_MODE=merge|replace`
- `DRY_RUN=true` to plan imports too
- `TAXONOMY_CATEGORIES_FILE` and `TAXONOMY_TAGS_FILE` are available for direct CLI usage

Advanced CLI examples:

```bash
# Merge refresh and actually delete cleanup candidates
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.taxonomy_manager refresh --mode merge --cleanup --cleanup-apply --cleanup-only-unused --cleanup-delete-noisy

# Full replace refresh
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.taxonomy_manager refresh --mode replace

# Cleanup only (apply)
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.taxonomy_manager cleanup --apply --max-length 24 --min-usage 1 --delete-noisy --only-unused
```

## `taxonomy-audit` Deep Dive

Behavior:

- Reads all recipes/categories/tags
- Calculates unused categories/tags, missing metadata coverage, and problematic tags
- Writes JSON report locally

Switches:

- `TAXONOMY_AUDIT_OUTPUT` to change report path
- `--output` path override
- `--long-tag-threshold` default `24`
- `--min-useful-usage` default `2`

Example:

```bash
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.audit_taxonomy --output reports/taxonomy_audit_report.json --long-tag-threshold 24 --min-useful-usage 2
```

## `cookbook-sync` Deep Dive

Default behavior:

- Creates missing cookbooks
- Updates changed cookbooks
- Leaves extra existing cookbooks alone

Special switches:

- `--replace` deletes cookbooks not present in your source JSON
- `COOKBOOKS_FILE` sets default file path for direct CLI usage
- `DRY_RUN=true` plans create/update/delete actions only

Example:

```bash
# Safe upsert (no deletions)
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer

# Enforce exact cookbook set (deletes extras)
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.cookbook_manager sync --replace
```

## `ingredient-parse` Deep Dive

Default behavior:

- Processes recipes where `hasParsedIngredients=false`
- Uses parser fallback strategies from `PARSER_STRATEGIES`
- Requires confidence threshold before patching
- Writes review and success artifacts under `reports/`

Special switches:

- `MEALIE_BASE_URL` and `MEALIE_API_TOKEN` are accepted as legacy aliases (deprecated)
- `CONFIDENCE_THRESHOLD`, `PARSER_STRATEGIES`, `FORCE_PARSER`
- `MAX_RECIPES`, `AFTER_SLUG`
- `REQUEST_TIMEOUT_SECONDS`, `REQUEST_RETRIES`, `REQUEST_BACKOFF_SECONDS`

Example:

```bash
docker compose run --rm -e TASK=ingredient-parse -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=ingredient-parse -e DRY_RUN=true -e RUN_MODE=once mealie-organizer
```

## `plugin-server` Deep Dive

Default behavior:

- Serves `/mo-plugin/page` companion UI
- Serves `/mo-plugin/static/injector.js` for top-bar button injection
- Exposes `/mo-plugin/api/v1/parser/status` and `/mo-plugin/api/v1/parser/runs`
- Enforces admin-only access by validating Mealie bearer/cookie tokens via `/api/users/self`
- Runs parser in dry-run mode only when started from plugin API

Special switches:

- `PLUGIN_BIND_HOST`, `PLUGIN_BIND_PORT`
- `PLUGIN_BASE_PATH`
- `PLUGIN_TOKEN_COOKIES`
- `PLUGIN_AUTH_TIMEOUT_SECONDS`

Example:

```bash
docker compose run --rm -e TASK=plugin-server -e RUN_MODE=once mealie-organizer
```

## `foods-cleanup` and `units-cleanup` Deep Dive

Default behavior:

- Audit-first (plan/report), no merges unless apply flag is set
- Deterministic normalization and exact merge candidates only
- Checkpoint-aware resumes for apply mode

Special switches:

- `CLEANUP_APPLY=true` to enable writes
- `MAX_ACTIONS_PER_STAGE` for merge cap
- `CHECKPOINT_DIR` for resume storage
- `UNITS_ALIAS_FILE` controls unit alias mapping

Example:

```bash
docker compose run --rm -e TASK=foods-cleanup -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=units-cleanup -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=units-cleanup -e CLEANUP_APPLY=true -e RUN_MODE=once mealie-organizer
```

## `labels-sync` and `tools-sync` Deep Dive

Default behavior:

- Labels: catalog-only sync (create missing, skip existing)
- Tools: seed catalog plus exact duplicate merge candidates
- Audit-first unless apply flag is set

Example:

```bash
docker compose run --rm -e TASK=labels-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=tools-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=tools-sync -e CLEANUP_APPLY=true -e RUN_MODE=once mealie-organizer
```

## `data-maintenance` Deep Dive

Default stage order:

- `parse,foods,units,taxonomy,categorize,cookbooks,audit`

Special switches:

- `MAINTENANCE_STAGES` to override stage list
- `MAINTENANCE_APPLY_CLEANUPS=true` to write cleanup changes
- `--continue-on-error` for best-effort runs

Examples:

```bash
docker compose run --rm -e TASK=data-maintenance -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=data-maintenance -e MAINTENANCE_APPLY_CLEANUPS=true -e RUN_MODE=once mealie-organizer
docker compose run --rm --entrypoint python mealie-organizer -m mealie_organizer.data_maintenance --stages parse,foods,units,audit
```

## Practical Operating Patterns

- Continuous lightweight mode:
  - `TASK=categorize`
  - `RUN_MODE=loop`
  - `RUN_INTERVAL_SECONDS=21600`
- Incremental ingredient/entity cleanup:
  - `TASK=data-maintenance`
  - `RUN_MODE=once`
  - start with `DRY_RUN=true`, then enable apply flags for controlled batches
- Weekly taxonomy maintenance:
  - Run `TASK=taxonomy-refresh` in `RUN_MODE=once`
  - Review cleanup plan output before any `--cleanup-apply` run
- Monthly audit:
  - Run `TASK=taxonomy-audit` and review `reports/taxonomy_audit_report.json`

## Troubleshooting

- `[error] Unknown TASK ...`: `TASK` must be one of `categorize`, `taxonomy-refresh`, `taxonomy-audit`, `cookbook-sync`, `ingredient-parse`, `plugin-server`, `foods-cleanup`, `units-cleanup`, `labels-sync`, `tools-sync`, `data-maintenance`.
- `MEALIE_URL is not configured`: set real `MEALIE_URL` in `.env`.
- `MEALIE_API_KEY is empty`: set `MEALIE_API_KEY` in `.env`.
- Loop interval error: `RUN_INTERVAL_SECONDS` must be numeric.
