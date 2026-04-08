# Changelog

All notable changes to CookDex are documented here.

## [2026.4.1] - 2026-04-07

### Security
- **Role-based access control** — Users now have `owner` or `editor` roles; owner-only routes (users, settings, debug) are enforced server-side with atomic last-owner protections
- **Session cookie TTL** — Login cookies now set `Max-Age`/`Expires` matching `WEB_SESSION_TTL_SECONDS` so sessions survive browser restarts

### Fixed
- **Schedule validation** — Invalid schedule inputs rejected with 422 before DB writes; legacy broken schedules surface `validation_error` instead of silently failing
- **Backup timeout** — Mealie backup POST timeout increased from 2min to 15min, pre-command timeout from 5min to 20min, to support large datasets

### Changed
- Mealie badge updated to v3.14

## [2026.3.63] - 2026-03-25

### Security
- **SSRF fix** — Starter pack import endpoint now validates URLs through `_validate_service_url`, blocking private IPs, cloud metadata endpoints, and non-HTTP schemes
- **Prompt injection hardening** — Recipe names, slugs, and ingredients are sanitized before AI prompt interpolation (strips control chars, role markers, and common injection phrases)
- **Identified User-Agent** — Dredger crawler now sends `CookDex/{version}` with repo link instead of anonymous `python-requests` default
- **Rate limit floor** — Hard minimum 1s crawl delay that cannot be bypassed by configuration

### Changed
- Default site list moved from hardcoded Python to `configs/default_sites.json` — cleaner data/code separation

## [2026.3.62] - 2026-03-24

### Fixed
- **Runaway task prevention** — AI categorizer now aborts immediately when provider is unavailable (rate-limit/quota exhausted) instead of retrying indefinitely for days
- Rate-limit retries reduced from 15 to 5 per API call; raises `ProviderUnavailableError` on exhaustion
- Consecutive batch failure circuit breaker — 3 failures in a row aborts the run
- **4-hour max run duration** enforced on all tasks (configurable via `MAX_RUN_DURATION_SECONDS` in Settings)

### Changed
- Default ingredient parser confidence threshold lowered from 80% to 70% — dramatically reduces expensive OpenAI parser fallbacks
- Categorizer batch size increased from 20 to 50 — fewer API calls, better cost amortization
- Categorizer prompts compacted to comma-separated taxonomy lists — reduces token usage per request

## [2026.3.61] - 2026-03-22

### Added
- **Privacy & Data** card on About page — shows telemetry, analytics, credential storage, and network access at a glance with detailed explanations
- **Privacy** section in README — documents data handling, credential storage, AI provider disclosure, and cookie usage
- **Bad scrape detection** in junk filter — catches recipes where the scraper produced garbled data:
  - Char-by-char HTML steps (scraper iterated an HTML string character by character, producing hundreds of single-char steps)
  - Collapsed ingredients (entire ingredient list jammed into a single note field as unparsed text)
- "Bad scrapes" option in junk filter reason dropdown (UI and CLI `--reason bad_scrape`)
- Mealie-to-Tandoor migration script (`scripts/migrate_mealie_to_tandoor.py`) — direct API-to-API recipe transfer with image support, resumability, and Unicode-safe output

## [2026.3.59] - 2026-03-22

### Added
- **Direct DB setup wizard** (`scripts/setup-db-tunnel.sh`) — interactive script that handles SSH key generation, copying, volume mounting, settings configuration, and container restart in one command
- Wizard writes SSH settings directly into CookDex's state database — no manual field entry needed
- "Merge Defaults" button on Recipe Sources — adds new curated sites from updates without removing existing sites
- Site add validation — checks reachability and requires a sitemap before adding; shows "Validating..." state during check

### Fixed
- SSH key validation now searches `/app/.ssh/` and `/tmp/.ssh-app/` in addition to `~/.ssh/`, and checks read permission — fixes "key not found" and permission errors in Docker
- SSH known_hosts path falls back to `/tmp/.ssh-app/` when `~/.ssh/` doesn't exist — fixes paramiko failure when `HOME=/nonexistent` (app user in Docker)
- Test DB now uses draft values from the UI like all other connection tests — no need to Apply Changes before testing
- Default SSH Key Path changed from `~/.ssh/cookdex_mealie` to `/app/.ssh/cookdex_mealie` to match the documented container mount path
- Tasks without a dry run option (e.g. Health Check) now show "Run" instead of misleading "Preview Run"

### Removed
- Removed 5 unreachable seed recipe sites (hard Cloudflare blocks / 406 rejections)

### Changed
- Renamed "Region" to "Group" throughout Recipe Sources — allows organizing sites by any category (e.g. Vegan, Budget, Keto), not just cuisine region; existing databases auto-migrate on startup
- Rewrote Direct DB docs — leads with setup wizard, then manual steps as fallback
- Removed misleading `pip install 'cookdex[db]'` from docs (dependencies are included in Docker image)
- Updated in-app help guides to match new wizard-first setup flow

## [2026.3.45] - 2026-03-21

### Added
- **Mealie Backup** task — create and prune Mealie backups via the admin API, with optional retention limit
- **Backup First** option on destructive tasks (Data Maintenance, Clean Recipes, Ingredient Parser, Tag & Categorize, Re-import, Cleanup Duplicates) — creates a Mealie backup before the task runs; hidden in dry-run mode
- Pre-command support in task runner — tasks can now run prerequisite commands (e.g. backup) before the main task, with automatic abort on failure
- Mealie server capabilities detection — connection test now probes `/about` for server version and feature flags
- `get_about()` method on `MealieApiClient` for querying Mealie server info
- Unit standardization fields (`standardUnit`, `standardQuantity`) supported in unit creation and alias metadata
- Mealie compatibility badge in README (validated against Mealie v3.13.1)
- Connection test response now includes `capabilities` object with `version` and `enableOpenaiTranscription`
- Health/debug report includes Mealie server capabilities alongside connection status

### Changed
- `_test_mealie_connection` returns server capabilities (version, transcription support) alongside connection status
- Settings test endpoint (`POST /settings/test/mealie`) returns `capabilities` when connection succeeds
## [2026.3.44] - 2026-03-21

### Security
- Subprocess env isolation — tasks receive only essential system vars + catalog vars, no longer inherit full parent env
- Added CSP, X-Frame-Options, X-Content-Type-Options, and Referrer-Policy security headers
- Debug endpoint no longer exposes internal Mealie/Ollama URLs — reports `set`/`not set` only
- Health endpoint no longer exposes app version or base path to unauthenticated callers
- SSH host validation tightened — removed `%` from allowed chars to prevent config injection
- SSH username and container name validation require alphanumeric first character to block flag injection
- SSRF protection extended to block Azure (168.63.129.16) and Alibaba Cloud (100.100.100.200) metadata IPs
- Auto-generated encryption key now stored in `.secrets/` subdirectory, separated from state database

### Accessibility (WCAG 2.1 AA)
- Added `:focus-visible` outlines on all interactive elements (buttons, inputs, nav items, toggles)
- Added `@media (prefers-reduced-motion: reduce)` to disable all animations
- Added `.sr-only` utility class for screen reader content
- Replaced `title` with `aria-label` on all icon-only buttons across Tasks, Users, Recipe Sources, and Recipe Organization pages
- Added `aria-label` to all search, filter, and unlabeled form inputs
- Added `scope="col"` to all table headers; empty header columns given sr-only labels
- Error/warning banners now use `role="alert"` and notice banners use `role="status"` for screen reader announcements
- Task badges (AI, DB) use `role="img"` with `aria-label` instead of title-only
- Improved disabled button contrast with explicit background/color instead of opacity-only

### Changed
- Replaced "Description" with "Ingredients Parsed" in gold medallion quality dimensions — all 6 dimensions are now actionable by the pipeline

## [2026.3.43] - 2026-03-21

### Changed
- Replaced "Description" with "Ingredients Parsed" in gold medallion quality dimensions — all 6 dimensions are now actionable by the pipeline

## [2026.3.42] - 2026-03-20

### Changed
- Split monolithic `App.jsx` (4925 lines) into 8 page components — App.jsx is now a 1160-line shell handling auth, routing, and shared state
- Extracted task log parser and renderers into `taskLogUtils.jsx`

### Docs
- Added missing `slug-repair` and `reimport-recipes` tasks to README, TASKS.md, and DIRECT_DB.md
- Fixed `tag-categorize` method default (`ai` → `both`) and added `recat` option in TASKS.md
- Fixed `ingredient-parse` confidence default (`75` → `80`) and added `max_recipes`/`no_cache` options in TASKS.md
- Added dredger-sites API endpoints to TASKS.md

## [2026.3.41] - 2026-03-20

### Added
- `--no-cache` flag for ingredient parser to bypass scan cache and reprocess all unparsed recipes
- "Bypass Cache" toggle in Tasks UI for ingredient parser
- Concurrent recipe prefetch (8 workers) for significantly faster parser runs

### Fixed
- Ingredient parser was sending `strategy` instead of `parser` to Mealie API — brute force and OpenAI fallbacks were never actually used
- Recipes fetched from list endpoint were missing ingredient data, causing all recipes to be skipped as "empty"

## [2026.3.40] - 2026-03-17

### Added
- UI screenshots in README (overview, tasks, recipe sources, taxonomy, settings)
- Credit to original Recipe Dredger author (D0rk4ce) in Recipe Sources UI

### Fixed
- Overview page cookbooks count showing 0 — added cookbook fetch to overview metrics API

## [2026.3] - 2026-03-15

### Added
- **Recipe Dredger** — discover and import recipes from curated sites via sitemap crawling, with language filtering and parallel workers
- **Mobile-friendly UI** — touch targets, responsive tables, adaptive polling, hamburger menu navigation
- **URL-based routing** — pages reflect in the browser URL (`/cookdex/tasks`, `/cookdex/settings`, etc.) with back/forward support
- **ETag caching** — backend returns `304 Not Modified` for unchanged API responses; frontend skips re-parsing
- **SQLite metrics cache** — dashboard overview loads from cache (~100ms) instead of live Mealie API calls (~60s), invalidated after task runs
- **Workspace draft reset** — "Initialize from Mealie" and "Import Starter Pack" now reconcile the workspace draft automatically
- **Junk detection** — filters failed scrapes, GUIDs, and empty-ingredient recipes before import
- **DB indexes** — automatic index creation on Mealie tags/tools/categories tables for faster lookups
- **Slug repair task** — detect and fix slug mismatches between API and database
- **Recipe reimporter** — re-scrape recipes from their original source URLs with parallel workers

### Changed
- AI provider settings (OpenAI, Anthropic, Ollama) are now hidden when their provider is not selected
- Run polling adapts to activity: 5s when tasks are active, 30s when idle (was fixed 3s)
- Log polling increased from 1.5s to 3s with proper cleanup of stale closures
- Settings/taxonomy saves no longer trigger a full data reload — only the changed data is refreshed
- Taxonomy content is lazy-loaded when navigating to pages that need it
- Ingredient parser reuses bulk-fetched recipe data instead of re-fetching each recipe individually
- Deduplicator deletes recipes in parallel (4 workers) instead of sequentially
- Hover effects wrapped in `@media (hover: hover)` to prevent sticky states on touch devices
- Overview stats grid uses 4 → 2 → 1 column progression across breakpoints
- Docker volumes simplified: `./configs` mount removed (taxonomy data lives in SQLite)

### Removed
- 920 lines of dead code from the old recipe organization editor
- Unused `configs/config.json` (no code referenced it)
- `configs.defaults` backup layer from Dockerfile
- Unused `PROVIDER` environment variable from docker-compose

### Fixed
- Log viewer maximized mode was pushed off-screen on mobile by sidebar offset
- Ingredient parser was re-fetching every recipe individually after already bulk-fetching all of them
- Taxonomy workspace showed phantom diffs after importing from Mealie or starter pack
- Dredger live mode had double `/api` prefix causing 404 on all Mealie calls

### Security
- SSRF protection hardened with DNS resolution and private IP blocking
- SSH subprocess args passed via temp config file instead of CLI to prevent injection
- CodeQL alerts resolved for command injection and path traversal

## [2026.2] - 2026-02-28

### Added
- Web UI with task runner, scheduler, and settings management
- Multi-user authentication with password complexity enforcement
- Encrypted secret storage (Fernet cipher with auto-generated key)
- Taxonomy workspace with draft/validate/publish workflow
- Quality audit with gold/silver/bronze scoring
- Data maintenance pipeline (14-stage sequential processing)
- Ingredient parser with NLP + AI fallback and confidence thresholds
- Tag categorizer with rule-based and AI-powered classification
- Direct database access for bulk operations (PostgreSQL + SQLite + SSH tunnel)
