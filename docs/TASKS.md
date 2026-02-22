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

| Task ID | Title | Description |
|---|---|---|
| `categorize` | Recipe Categorizer | Classify recipes using the configured AI provider |
| `taxonomy-refresh` | Taxonomy Refresh | Sync categories and tags from config files |
| `taxonomy-audit` | Taxonomy Audit | Generate taxonomy diagnostics report |
| `cookbook-sync` | Cookbook Sync | Create/update cookbooks from config rules |
| `ingredient-parse` | Ingredient Parser | Parse ingredients with parser fallback chain |
| `foods-cleanup` | Foods Cleanup | Merge duplicate food entries |
| `units-cleanup` | Units Cleanup | Normalize unit aliases and merge duplicates |
| `labels-sync` | Labels Sync | Create/delete labels from taxonomy config |
| `tools-sync` | Tools Sync | Create/merge tools from taxonomy config |
| `data-maintenance` | Data Maintenance | Run full staged maintenance pipeline |
| `recipe-quality` | Recipe Quality Audit | Score recipes on gold-medallion dimensions; estimate nutrition coverage |
| `yield-normalize` | Yield Normalizer | Fill missing yield text from servings, or parse yield text to set numeric servings |
| `rule-tag` | Rule-Based Tagger | Tag and tool-assign recipes using regex rules — no LLM required |

### recipe-quality options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Read-only — do not write any changes |
| `nutrition_sample` | integer | `200` | Recipes fetched for nutrition coverage estimate (ignored with `use_db`) |
| `use_db` | boolean | `false` | Read via single JOIN query instead of N API calls; exact nutrition coverage; requires `MEALIE_DB_TYPE` |

### yield-normalize options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing |
| `apply` | boolean | `false` | Write changes (dangerous — requires policy unlock) |
| `use_db` | boolean | `false` | Write directly to Mealie DB in a single transaction instead of individual API PATCH calls; requires `MEALIE_DB_TYPE` |

### rule-tag options

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview matches without writing |
| `apply` | boolean | `false` | Write tag and tool assignments to Mealie (dangerous) |
| `use_db` | boolean | `false` | Enable ingredient and tool matching via direct DB queries; without this only `text_tags` rules run via the Mealie API; requires `MEALIE_DB_TYPE` |
| `config_file` | string | `configs/taxonomy/tag_rules.json` | Path to rules JSON file; leave blank for default |

The `use_db` option requires the `db` extras (`pip install 'cookdex[db]'`) and DB credentials in `.env`. See [Direct DB Access](DIRECT_DB.md) for setup.

## Environment Variable Management

Runtime values are managed in the Web UI through `GET/PUT /settings`.

- Non-secret keys are stored in app settings.
- Secret keys are encrypted at rest.
- Task executions consume the effective runtime environment built from these values.

## Safety Policies

Dangerous options are blocked by default and unlocked per task via `PUT /policies`.
