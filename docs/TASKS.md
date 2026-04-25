# Tasks and API

This is the technical reference for CookDex task execution, scheduling, safety policies, and Web UI API routes.

All API routes are prefixed with `/cookdex/api/v1` by default. If `WEB_BASE_PATH` changes, replace `/cookdex` with your configured base path.

## Scheduling

CookDex supports two schedule kinds:

| Kind | Required fields | Notes |
|---|---|---|
| `interval` | `seconds` | Runs repeatedly. Optional `start_at`, `end_at`, and `run_if_missed` values are stored in UTC. |
| `once` | `run_at` | Runs one time in the future. Optional `run_if_missed` controls restored missed runs. |

Only `interval` and `once` schedules are supported in the current API.

## Safety Policies

Most write-capable tasks default to `dry_run=true`. Live runs (`dry_run=false`) and other dangerous options are blocked unless an owner enables the task policy through `PUT /policies` or the Web UI unlock flow.

The **Backup First** option is hidden while a task is in dry-run mode. When enabled for a live run, CookDex creates a Mealie backup before the main task starts.

## Task IDs

**Data Pipeline**

| Task ID | Title | Purpose |
|---|---|---|
| `data-maintenance` | Data Maintenance Pipeline | Run staged cleanup and audit steps in order, or select a subset of stages. |
| `recipe-dredger` | Recipe Dredger | Crawl configured recipe sites, verify recipe pages, filter by language, and import verified URLs into Mealie. |
| `mealie-backup` | Mealie Backup | Create a Mealie backup through the admin API and optionally prune old backups. |

**Actions**

| Task ID | Title | Purpose |
|---|---|---|
| `clean-recipes` | Clean Recipe Library | Remove duplicate source URLs, filter junk content, and normalize messy import names. |
| `slug-repair` | Repair Recipe Slugs | Detect slug/name mismatches and fix them through Direct DB when applying changes. |
| `ingredient-parse` | Ingredient Parser | Parse raw ingredient text into structured food, unit, and quantity fields. |
| `yield-normalize` | Yield Normalizer | Fill missing yield text or parse yield text into numeric servings. |
| `cleanup-duplicates` | Clean Up Duplicates | Merge duplicate food and unit entries. |
| `reimport-recipes` | Re-import Recipes | Re-scrape source URLs while preserving recipe identity, favorites, and organization. |

**Organizers**

| Task ID | Title | Purpose |
|---|---|---|
| `tag-categorize` | Tag & Categorize Recipes | Assign categories, tags, and tools with rule matching and optional AI. |
| `taxonomy-refresh` | Refresh Taxonomy | Sync categories, tags, labels, and tools from CookDex config into Mealie. |
| `cookbook-sync` | Cookbook Sync | Create and update cookbooks from cookbook configuration rules. |

**Audits**

| Task ID | Title | Purpose |
|---|---|---|
| `health-check` | Health Check | Run read-only recipe quality and taxonomy audits. |

## Options

### `data-maintenance`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `stages` | string list | all stages | Select stages: `dedup`, `junk`, `names`, `parse`, `foods`, `units`, `labels`, `tools`, `taxonomy`, `categorize`, `cookbooks`, `yield`, `quality`, `audit`. |
| `confidence_threshold` | integer | `70` | Ingredient parser NLP confidence percentage. Lower accepts more NLP results and reduces AI fallback. |
| `max_recipes` | integer | unset | Limit ingredient parsing when the `parse` stage runs. |
| `no_cache` | boolean | `false` | Ignore the ingredient parser scan cache. |
| `reason` | string | all categories | Limit junk filtering to one category. |
| `force_all` | boolean | `false` | Normalize all names, not only unformatted names. |
| `provider` | string | configured default | Override AI provider for categorization: `chatgpt`, `anthropic`, or `ollama`. |
| `taxonomy_mode` | string | configured default | Override taxonomy refresh mode: `merge` or `replace`. |
| `use_db` | boolean | `false` | Enable Direct DB for the `quality` and `yield` stages. |
| `nutrition_sample` | integer | `200` | API-mode nutrition sample size for the quality stage. Hidden when `use_db=true`. |
| `continue_on_error` | boolean | `false` | Keep running later stages if one stage fails. |
| `apply_cleanups` | boolean | `false` | Dangerous. Allows cleanup stages to write changes. Hidden while `dry_run=true`. |

Default stage order:

`dedup -> junk -> names -> parse -> foods -> units -> labels -> tools -> taxonomy -> categorize -> cookbooks -> yield -> quality -> audit`

### `recipe-dredger`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview imports without writing to Mealie. |
| `limit` | integer | `50` | Maximum recipes to import per configured site. |
| `depth` | integer | `1000` | Maximum URLs to scan per site sitemap. |
| `no_cache` | boolean | `false` | Ignore cached sitemaps and crawl fresh. |
| `import_workers` | integer | `2` | Concurrent import workers, capped at 4. |
| `precheck_duplicates` | boolean | `true` | Fetch existing Mealie recipes first and skip duplicates before import. |
| `language_filter` | boolean | `true` | Skip recipes that do not match `DREDGER_TARGET_LANGUAGE`. |
| `max_retry_attempts` | integer | `3` | Retry transient failures before marking a URL rejected. |

### `mealie-backup`

| Option | Type | Default | Description |
|---|---|---|---|
| `keep` | integer | unset | After creating a backup, prune older backups and keep only this many. |
| `prune_only` | boolean | `false` | Skip backup creation and only prune old backups. Requires `keep`. |

### `clean-recipes`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `run_dedup` | boolean | `true` | Remove imported duplicates with the same source URL. |
| `run_junk` | boolean | `true` | Remove non-recipe content such as listicles, how-to articles, and placeholder pages. |
| `run_names` | boolean | `true` | Normalize names derived from URL slugs. |
| `reason` | string | all categories | Limit junk filtering to one category. |
| `force_all` | boolean | `false` | Normalize all recipe names, not only unformatted names. |
| `use_db` | boolean | `false` | Advanced fallback for deleting corrupted duplicate recipes when the API returns 500. Requires Direct DB settings. |

### `slug-repair`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Scan only and print mismatches plus SQL fix statements. |
| `use_db` | boolean | `false` | Apply fixes directly through Mealie's database. Required for writing. |

### `ingredient-parse`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `max_recipes` | integer | unset | Limit parsing to at most N recipes. |
| `no_cache` | boolean | `false` | Ignore the scan cache and reprocess all unparsed recipes. |
| `confidence_threshold` | integer | `70` | Minimum NLP confidence percentage before accepting a parse. Low-confidence lines fall back to AI parsing. |

### `yield-normalize`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `use_db` | boolean | `false` | Write changes in one DB transaction instead of many API calls. |

### `cleanup-duplicates`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview merges without writing anything. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `target` | string | `both` | Deduplicate `both`, `foods`, or `units`. |

### `reimport-recipes`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview eligible recipes. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `max_recipes` | integer | unset | Limit reimport to at most N recipes. |
| `workers` | integer | `2` | Concurrent scrape workers, capped at 4. |
| `delay` | number | `0.5` | Seconds between requests per worker. |
| `resume` | boolean | `false` | Skip recipes completed in the previous run. |
| `slugs` | string | unset | Comma-separated recipe slugs to reimport. Leave blank for all eligible recipes. |

Reimport normally uses the Mealie API. If Direct DB is configured, it can repair a slug mismatch fallback when Mealie rejects an update with a 403.

### `tag-categorize`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `backup_first` | boolean | `false` | Create a Mealie backup before a live run. Hidden while `dry_run=true`. |
| `method` | string | `both` | `both` runs rules first then AI, `rules` uses rules only, `ai` skips rules. |
| `recat` | boolean | `false` | Re-process every recipe, including recipes that already have organization data. Hidden for `rules`. |
| `provider` | string | configured default | Override AI provider for this run. Hidden for `rules`. |
| `use_db` | boolean | `false` | Enable Direct DB matching for rules, including ingredient and tool matching. Hidden for `ai`. |
| `missing_targets` | string | `skip` | `skip` missing taxonomy targets or `create` them automatically. Hidden for `ai`. |

### `taxonomy-refresh`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |
| `sync_labels` | boolean | `true` | Sync labels along with categories and tags. |
| `sync_tools` | boolean | `true` | Sync tools and merge duplicates from taxonomy config. |
| `mode` | string | `merge` | `merge` keeps existing entries; `replace` matches source files exactly. |
| `cleanup_apply` | boolean | `false` | Dangerous. Permanently delete unused categories/tags. Hidden while `dry_run=true`. |

### `cookbook-sync`

| Option | Type | Default | Description |
|---|---|---|---|
| `dry_run` | boolean | `true` | Preview changes without writing anything. |

### `health-check`

| Option | Type | Default | Description |
|---|---|---|---|
| `scope_quality` | boolean | `true` | Score recipe completeness for categories, tags, tools, ingredients, cook time, yield, and nutrition. |
| `scope_taxonomy` | boolean | `true` | Scan taxonomy for unused entries, duplicate names, and recipes missing categories or tags. |
| `use_db` | boolean | `false` | Fetch all recipe data in one query for faster and exact nutrition coverage. |
| `nutrition_sample` | integer | `200` | API-mode nutrition sample size. Hidden when `use_db=true`. |

`health-check` is read-only and does not expose a `dry_run` option.

## Direct DB

Docker images include the Direct DB dependencies. Configure DB settings in **Settings -> Direct DB** and use **Auto-detect DB** when possible.

For local source installs only, install the optional DB extras before using Direct DB:

```bash
pip install -e ".[db]"
```

See [Direct DB Access](DIRECT_DB.md) for the wizard, manual setup, and table access notes.

## Runtime Settings

Runtime settings are managed through `GET /settings` and `PUT /settings`.

- Non-secret values are stored in the app state database.
- Secret values are encrypted at rest.
- Task runs receive the effective runtime environment built from the settings catalog.
- `.env` is optional and mainly useful for server overrides, pre-seeding values, or headless deployments.

Main setting groups:

| Group | Examples |
|---|---|
| Connection | `MEALIE_URL`, `MEALIE_API_KEY` |
| AI | `CATEGORIZER_PROVIDER`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`, model settings |
| Dredger | `DREDGER_TARGET_LANGUAGE`, `DREDGER_CRAWL_DELAY`, `DREDGER_CACHE_EXPIRY_DAYS` |
| Web UI | `WEB_BIND_PORT`, `WEB_BASE_PATH`, `WEB_SESSION_TTL_SECONDS` |
| Direct DB | `MEALIE_DB_TYPE`, Postgres credentials, SSH tunnel settings |
| Runner | `MAX_RUN_DURATION_SECONDS` |

## API Routes

**Auth**

- `GET /auth/bootstrap-status`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`

**Tasks, Runs, Policies**

- `GET /tasks`
- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/log`
- `GET /runs/{run_id}/log/tail`
- `POST /runs/{run_id}/cancel`
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
- `POST /settings/models/openai`
- `POST /settings/models/anthropic`
- `POST /settings/models/ollama`
- `POST /settings/test/mealie`
- `POST /settings/test/openai`
- `POST /settings/test/anthropic`
- `POST /settings/test/ollama`
- `POST /settings/test/db`
- `POST /settings/detect/db`
- `GET /settings/dredger-sites`
- `POST /settings/dredger-sites`
- `PUT /settings/dredger-sites/{site_id}`
- `DELETE /settings/dredger-sites/{site_id}`
- `POST /settings/dredger-sites/seed`
- `POST /settings/dredger-sites/validate`

**Users**

- `GET /users`
- `POST /users`
- `POST /users/{username}/reset-password`
- `PATCH /users/{username}/role`
- `DELETE /users/{username}`

**Config And Taxonomy Workspace**

- `GET /config/files`
- `GET /config/files/{name}`
- `PUT /config/files/{name}`
- `GET /config/taxonomy/starter-pack`
- `POST /config/taxonomy/initialize-from-mealie`
- `POST /config/taxonomy/import-starter-pack`
- `GET /config/workspace/lookups`
- `GET /config/workspace/draft`
- `PUT /config/workspace/draft`
- `POST /config/workspace/validate`
- `POST /config/workspace/reset`
- `POST /config/workspace/publish`

**Meta**

- `GET /health`
- `GET /metrics/overview`
- `GET /metrics/quality`
- `GET /about/meta`
- `GET /help/docs`
- `GET /debug-log`
