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

**Data Pipeline**
| Task ID | Title | Description |
|---|---|---|
| `data-maintenance` | Data Maintenance Pipeline | Run all maintenance stages in order: Dedup → Junk Filter → Name Normalize → Ingredient Parse → Foods Cleanup → Units Cleanup → Labels Sync → Tools Sync → Taxonomy Refresh → Categorize → Cookbook Sync → Yield Normalize → Quality Audit → Taxonomy Audit |

**Actions**
| Task ID | Title | Description |
|---|---|---|
| `clean-recipes` | Clean Recipe Library | Remove duplicates, filter junk content, and normalize messy import names |
| `ingredient-parse` | Ingredient Parser | Parse ingredients using NLP with AI fallback |
| `yield-normalize` | Yield Normalizer | Fill missing yield text from servings count, or parse yield text to set numeric servings |
| `cleanup-duplicates` | Clean Up Duplicates | Merge duplicate food and/or unit entries |

**Organizers**
| Task ID | Title | Description |
|---|---|---|
| `tag-categorize` | Tag & Categorize Recipes | Assign categories, tags, and tools via AI semantic classification or regex rule-based matching |
| `taxonomy-refresh` | Refresh Taxonomy | Sync categories, tags, labels, and tools from config files into Mealie |
| `cookbook-sync` | Cookbook Sync | Create and update cookbooks from cookbook configuration |

**Audits**
| Task ID | Title | Description |
|---|---|---|
| `health-check` | Health Check | Score recipes on completeness dimensions; audit taxonomy for unused/missing entries |

### data-maintenance options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `stages` | string (multi) | *(all)* | Select specific stages: `dedup`, `junk`, `names`, `parse`, `foods`, `units`, `labels`, `tools`, `taxonomy`, `categorize`, `cookbooks`, `yield`, `quality`, `audit` |
| `skip_ai` | boolean | `false` | Skip the AI categorization stage |
| `continue_on_error` | boolean | `false` | Keep running remaining stages if one fails |
| `apply_cleanups` | boolean | `false` | Write deduplication and cleanup results (dangerous) |

### clean-recipes options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `run_dedup` | boolean | `true` | Remove recipes with duplicate source URLs |
| `run_junk` | boolean | `true` | Filter listicles, how-to articles, and non-recipe content |
| `run_names` | boolean | `true` | Normalize slug-derived recipe names |
| `reason` | string | *(all)* | Only scan a specific junk category: `how_to`, `listicle`, `digest`, `keyword`, `utility`, `bad_instructions` |
| `force_all` | boolean | `false` | Normalize all recipe names, not just slug-derived ones |

### ingredient-parse options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything |
| `confidence_threshold` | integer | `75` | Minimum NLP confidence % (0–100); results below this fall back to AI parsing |

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
| `method` | string | `ai` | Classification method: `ai` (uses configured LLM provider) or `rules` (regex, no LLM) |
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

### health-check options

| Option | Type | Default | Description |
|---|---|---|---|
| `scope_quality` | boolean | `true` | Score all recipes on completeness: categories, tags, tools, description, cook time, yield, nutrition |
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
