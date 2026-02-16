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

## Global Switches

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `MEALIE_URL` | none | all tasks | Required. Must be your real Mealie API base URL. |
| `MEALIE_API_KEY` | none | all tasks | Required. |
| `DRY_RUN` | `false` | categorize, taxonomy manager, cookbook sync | Plans changes without sending write operations. |
| `TASK` | `categorize` | entrypoint | Task selector. |
| `RUN_MODE` | `loop` in compose | entrypoint | `once` runs a single pass, `loop` repeats forever. |
| `RUN_INTERVAL_SECONDS` | `21600` | entrypoint loop mode | Must be an integer. |
| `PROVIDER` | empty | categorize task path | Docker-only override passed as `--provider` when `TASK=categorize`. |
| `TAXONOMY_REFRESH_MODE` | `merge` | taxonomy-refresh task path | `merge` or `replace`. |

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

## Practical Operating Patterns

- Continuous lightweight mode:
  - `TASK=categorize`
  - `RUN_MODE=loop`
  - `RUN_INTERVAL_SECONDS=21600`
- Weekly taxonomy maintenance:
  - Run `TASK=taxonomy-refresh` in `RUN_MODE=once`
  - Review cleanup plan output before any `--cleanup-apply` run
- Monthly audit:
  - Run `TASK=taxonomy-audit` and review `reports/taxonomy_audit_report.json`

## Troubleshooting

- `[error] Unknown TASK ...`: `TASK` must be one of `categorize`, `taxonomy-refresh`, `taxonomy-audit`, `cookbook-sync`.
- `MEALIE_URL is not configured`: set real `MEALIE_URL` in `.env`.
- `MEALIE_API_KEY is empty`: set `MEALIE_API_KEY` in `.env`.
- Loop interval error: `RUN_INTERVAL_SECONDS` must be numeric.
