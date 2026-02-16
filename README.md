# Mealie Organizer

[Overview](README.md) | [Getting Started](docs/GETTING_STARTED.md) | [Install](docs/INSTALL.md) | [Update](docs/UPDATE.md) | [Tasks](docs/TASKS.md)

Mealie Organizer keeps Mealie metadata clean and usable at scale.
Operational guides now live under [`docs/`](docs/README.md).

It can:
- Parse unstructured ingredients into Mealie parsed ingredient data
- Clean and deduplicate foods and units with incremental safety controls
- Seed and sync labels/tools catalogs
- Refresh categories and tags from templates
- Sync cookbook templates
- Categorize/tag recipes using Ollama or ChatGPT-compatible APIs
- Audit taxonomy quality and usage
- Run an end-to-end data maintenance pipeline
- Run once or on a schedule in Docker

## Choose Your Path

| Deployment path | Best for | Install guide | Update guide |
| --- | --- | --- | --- |
| GHCR public image (recommended, no clone needed) | Most self-hosters | [Install](docs/INSTALL.md#1-ghcr-public-image-recommended) | [Update](docs/UPDATE.md#1-ghcr-public-image-recommended) |
| Your own custom image | Teams with custom changes or private registries | [Install](docs/INSTALL.md#2-build-and-push-your-own-image) | [Update](docs/UPDATE.md#2-your-own-custom-image) |
| Full local Ubuntu manual (no Docker) | Operators who want total host-level control | [Install](docs/INSTALL.md#3-full-local-ubuntu-manual-no-docker) | [Update](docs/UPDATE.md#3-full-local-ubuntu-manual-no-docker) |

## Common Commands

Fastest start (GHCR, no clone):

```bash
mkdir -p mealie-organizer && cd mealie-organizer
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/compose.ghcr.yml -o compose.yaml
# edit .env with your MEALIE_URL and MEALIE_API_KEY
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d --no-build --remove-orphans mealie-organizer
```

Start (repo-clone layout):

```bash
docker compose pull mealie-organizer
docker compose up -d --no-build --remove-orphans mealie-organizer
```

Logs:

```bash
docker compose logs -f mealie-organizer
```

Run one-shot tasks:

```bash
docker compose run --rm -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=taxonomy-audit -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=data-maintenance -e RUN_MODE=once mealie-organizer
```

Advanced task flags and task-specific workflows are documented in [docs/TASKS.md](docs/TASKS.md).
First-time bootstrap walkthrough is documented in [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

Use helper update script:

```bash
./scripts/docker/update.sh --source ghcr
```

## Runtime Flags

Container behavior is controlled by env vars:
- `TASK`: `categorize`, `taxonomy-refresh`, `taxonomy-audit`, `cookbook-sync`
- Additional `TASK` values: `ingredient-parse`, `foods-cleanup`, `units-cleanup`, `labels-sync`, `tools-sync`, `data-maintenance`
- `RUN_MODE`: `once` or `loop`
- `RUN_INTERVAL_SECONDS`: loop interval in seconds
- `TAXONOMY_REFRESH_MODE`: `merge` (default) or `replace`
- `DRY_RUN`: `true` for plan-only mode
- `CLEANUP_APPLY` / `MAINTENANCE_APPLY_CLEANUPS`: enable write mode for cleanup stages

For full task and switch behavior, see [docs/TASKS.md](docs/TASKS.md).

## User-Controlled Settings

User control remains local even with GHCR images:
- `.env` for secrets and runtime flags
- Optional `./configs` mounted to `/app/configs` (image defaults used if omitted)
- `./cache`, `./logs`, `./reports` mounted for local state/output

## Config And Taxonomy Files

- App defaults: `configs/config.json`
- Taxonomy templates:
  - `configs/taxonomy/categories.json`
  - `configs/taxonomy/tags.json`
  - `configs/taxonomy/cookbooks.json`
  - `configs/taxonomy/units_aliases.json`
  - `configs/taxonomy/labels.json`
  - `configs/taxonomy/tools.json`

## Project Layout

```text
.
|-- .github/workflows/publish-ghcr.yml
|-- configs/
|-- docs/
|   |-- README.md
|   |-- GETTING_STARTED.md
|   |-- INSTALL.md
|   |-- UPDATE.md
|   |-- TASKS.md
|   |-- DATA_MAINTENANCE.md
|   |-- PARSER_MIGRATION.md
|   `-- docker-ghcr.md
|-- scripts/
|-- src/mealie_organizer/
|-- tests/
|-- docker-compose.yml
|-- docker-compose.build.yml
|-- compose.ghcr.yml
|-- .env.example
`-- README.md
```

## Versioning

- Version source of truth: `VERSION`
- Release helper: `scripts/release.sh`
- GHCR publishes:
  - `latest` on `main`
  - `v*` on git tags
  - `sha-*` on publishes

## Troubleshooting

- `MEALIE_URL is not configured`: set a real API URL in `.env`
- Ollama cannot connect from container: use `OLLAMA_URL=http://host.docker.internal:11434/api`
- High retry rate from provider: reduce `BATCH_SIZE`/`MAX_WORKERS` or increase provider timeout

## Testing

```bash
python3 -m pytest
```
