# Changelog

All notable changes to CookDex are documented here.

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
