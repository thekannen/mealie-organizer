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
- `GET /settings/dredger-sites` / `POST /settings/dredger-sites`
- `PUT /settings/dredger-sites/{id}` / `DELETE /settings/dredger-sites/{id}`
- `POST /settings/dredger-sites/seed` / `POST /settings/dredger-sites/validate`

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

**Data Pipeline**
| Task ID | Title | Description |
|---|---|---|
| `data-maintenance` | Data Maintenance Pipeline | Run all maintenance stages in order: Dedup → Junk Filter → Name Normalize → Ingredient Parse → Foods Cleanup → Units Cleanup → Labels Sync → Tools Sync → Taxonomy Refresh → Categorize → Cookbook Sync → Yield Normalize → Quality Audit → Taxonomy Audit |
| `recipe-dredger` | Recipe Dredger | Discover and import recipes from curated sites — crawls sitemaps, verifies JSON-LD recipe schema, filters by language, and imports to Mealie |
| `mealie-backup` | Mealie Backup | Create a Mealie backup via the admin API, with optional pruning to keep only the newest N backups |

**Actions**
| Task ID | Title | Description |
|---|---|---|
| `clean-recipes` | Clean Recipe Library | Remove duplicates, filter junk content, and normalize messy import names |
| `slug-repair` | Repair Recipe Slugs | Detect and fix recipe slug mismatches caused by name normalization. Scan runs via API; fixes require direct DB access |
| `ingredient-parse` | Ingredient Parser | Parse ingredients using NLP with AI fallback |
| `yield-normalize` | Yield Normalizer | Fill missing yield text from servings count, or parse yield text to set numeric servings |
| `cleanup-duplicates` | Clean Up Duplicates | Merge duplicate food and/or unit entries |
| `reimport-recipes` | Re-import Recipes | Re-scrape recipes from their original URLs. Overwrites content but preserves tags, categories, and favorites |

**Organizers**
| Task ID | Title | Description |
|---|---|---|
| `tag-categorize` | Tag & Categorize Recipes | Assign categories, tags, and tools — Both (default) runs rules then AI, Rules Only needs no LLM, AI Only skips rules |
| `taxonomy-refresh` | Refresh Taxonomy | Sync categories, tags, labels, and tools from config files into Mealie |
| `cookbook-sync` | Cookbook Sync | Create and update cookbooks from cookbook configuration |

**Audits**
| Task ID | Title | Description |
|---|---|---|
| `health-check` | Health Check | Run diagnostic audits on your recipe library and taxonomy — surface missing metadata, unused entries, and duplicates |

### mealie-backup options

| Option | Type | Default | Description |
|---|---|---|---|
| `keep` | integer | *(unset)* | After creating a backup, prune older backups keeping only this many. Leave blank to keep all |
| `prune_only` | boolean | `false` | Skip backup creation and only prune old backups |

### data-maintenance options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `backup_first` | boolean | `false` | Create a Mealie backup before running (hidden in dry-run mode) |
| `stages` | string (multi) | *(all)* | Select specific stages: `dedup`, `junk`, `names`, `parse`, `foods`, `units`, `labels`, `tools`, `taxonomy`, `categorize`, `cookbooks`, `yield`, `quality`, `audit` |
| `provider` | string | *(configured default)* | Override categorizer provider for this run: `chatgpt` or `ollama` |
| `use_db` | boolean | `false` | Enable direct DB mode for `quality` and `yield` stages (requires DB settings) |
| `nutrition_sample` | integer | `200` | Quality-stage nutrition sample size (API mode only) |
| `reason` | string | *(all)* | Junk-stage category filter: `how_to`, `listicle`, `digest`, `keyword`, `utility`, `bad_instructions` |
| `force_all` | boolean | `false` | Normalize all recipe names when `names` stage runs |
| `confidence_threshold` | integer | `75` | Ingredient parser confidence % (0–100) for `parse` stage |
| `max_recipes` | integer | *(unset)* | Ingredient parser max recipes for `parse` stage |
| `after_slug` | string | *(unset)* | Ingredient parser resume cursor for `parse` stage |
| `parsers` | string | *(unset)* | Ingredient parser strategy list (e.g. `nlp,openai`) for `parse` stage |
| `force_parser` | string | *(unset)* | Force one ingredient parser strategy for `parse` stage |
| `page_size` | integer | *(unset)* | Ingredient parser page size for `parse` stage |
| `delay_seconds` | number | *(unset)* | Ingredient parser delay between writes for `parse` stage |
| `timeout_seconds` | integer | *(unset)* | Ingredient parser request timeout for `parse` stage |
| `retries` | integer | *(unset)* | Ingredient parser request retries for `parse` stage |
| `backoff_seconds` | number | *(unset)* | Ingredient parser retry backoff for `parse` stage |
| `taxonomy_mode` | string | *(configured default)* | Taxonomy stage mode override: `merge` or `replace` |
| `continue_on_error` | boolean | `false` | Keep running remaining stages if one fails |
| `apply_cleanups` | boolean | `false` | Write deduplication and cleanup results (dangerous) |

### clean-recipes options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `run_dedup` | boolean | `true` | Remove recipes with duplicate source URLs |
| `run_junk` | boolean | `true` | Filter listicles, how-to articles, and non-recipe content |
| `run_names` | boolean | `true` | Normalize lowercase/unformatted recipe names |
| `reason` | string | *(all)* | Only scan a specific junk category: `how_to`, `listicle`, `digest`, `keyword`, `utility`, `bad_instructions` |
| `force_all` | boolean | `false` | Normalize all recipe names, not just lowercase/unformatted ones |

### slug-repair options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Scan only — print mismatches and SQL fix statements |
| `use_db` | boolean | `false` | Apply fixes directly via Mealie's database. Required for writing — the API cannot update these recipes |

### ingredient-parse options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `max_recipes` | integer | *(unset)* | Limit parsing to at most N recipes. Leave blank to parse all candidates |
| `no_cache` | boolean | `false` | Ignore the scan cache and reprocess all unparsed recipes |
| `confidence_threshold` | integer | `80` | Minimum NLP confidence % (0–100); results below this fall back to AI parsing |

### yield-normalize options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `use_db` | boolean | `false` | Write changes in a single DB transaction instead of per-recipe API calls; requires `MEALIE_DB_TYPE` |

### cleanup-duplicates options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `target` | string | `both` | Which table to deduplicate: `both`, `foods`, `units` |

### tag-categorize options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `method` | string | `both` | Classification method: `both` (rules then AI, recommended), `rules` (regex only, no LLM), or `ai` (LLM only) |
| `recat` | boolean | `false` | Re-process every recipe, even those that already have categories/tags/tools assigned (AI/Both modes) |
| `provider` | string | *(configured default)* | Override AI provider (AI method only) |
| `use_db` | boolean | `false` | Match ingredients via direct DB queries (rule-based method only); requires `MEALIE_DB_TYPE` |

### taxonomy-refresh options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `sync_labels` | boolean | `true` | Create missing labels and remove unlisted ones |
| `sync_tools` | boolean | `true` | Create new tools and merge duplicates |
| `mode` | string | `merge` | `merge` keeps existing entries; `replace` overwrites to match source files exactly |
| `cleanup_apply` | boolean | `false` | Permanently delete categories/tags not referenced by any recipe (dangerous) |

### cookbook-sync options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |

### reimport-recipes options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview which recipes would be reimported |
| `max_recipes` | integer | *(unset)* | Limit reimport to at most N recipes. Leave blank for all |
| `workers` | integer | `2` | Concurrent scrape workers (1–4). More is faster but heavier on Mealie |
| `delay` | number | `0.5` | Seconds between requests per worker |
| `resume` | boolean | `false` | Skip recipes already reimported in the previous run |
| `slugs` | string | *(unset)* | Comma-separated list of recipe slugs to reimport. Leave blank for all eligible recipes |

### health-check options

| Option | Type | Default | Description |
|---|---|---|---|
| `scope_quality` | boolean | `true` | Score all recipes on completeness: categories, tags, tools, ingredients, cook time, yield, nutrition |
| `scope_taxonomy` | boolean | `true` | Scan for unused taxonomy entries, duplicate names, and recipes missing categories or tags |
| `use_db` | boolean | `false` | Fetch all recipe data in one query — faster and gives exact nutrition coverage; requires `MEALIE_DB_TYPE` |
| `nutrition_sample` | integer | `200` | Recipes sampled for nutrition coverage estimate (API mode only, quality scope only) |

The `use_db` option requires the `db` extras (`pip install 'cookdex[db]'`) and DB credentials in `.env`. See [Direct DB Access](DIRECT_DB.md) for setup.

## Environment Variable Management

Runtime values are managed in the Web UI through `GET/PUT /settings`.

- Non-secret keys are stored in app settings.
- Secret keys are encrypted at rest.
- Task executions consume the effective runtime environment built from these values.

## Safety Policies

Dangerous options are blocked by default and unlocked per task via `PUT /policies`.
