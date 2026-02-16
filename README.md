# Mealie Organizer

[Overview](README.md) | [Install](INSTALL.md) | [Update](UPDATE.md)

Mealie Organizer keeps Mealie metadata clean and usable at scale.

It can:
- Refresh categories and tags from templates
- Sync cookbook templates
- Categorize/tag recipes using Ollama or ChatGPT-compatible APIs
- Audit taxonomy quality and usage
- Run once or on a schedule in Docker

## Choose Your Path

| Deployment path | Best for | Install guide | Update guide |
| --- | --- | --- | --- |
| GHCR public image (recommended) | Most self-hosters | [Install](INSTALL.md#1-ghcr-public-image-recommended) | [Update](UPDATE.md#1-ghcr-public-image-recommended) |
| Your own custom image | Teams with custom changes or private registries | [Install](INSTALL.md#2-build-and-push-your-own-image) | [Update](UPDATE.md#2-your-own-custom-image) |
| Full local Ubuntu manual (no Docker) | Operators who want total host-level control | [Install](INSTALL.md#3-full-local-ubuntu-manual-no-docker) | [Update](UPDATE.md#3-full-local-ubuntu-manual-no-docker) |

## Common Commands

Start (GHCR pull-first):

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
```

Use helper update script:

```bash
./scripts/docker/update.sh --source ghcr
```

## Runtime Flags

Container behavior is controlled by env vars:
- `TASK`: `categorize`, `taxonomy-refresh`, `taxonomy-audit`, `cookbook-sync`
- `RUN_MODE`: `once` or `loop`
- `RUN_INTERVAL_SECONDS`: loop interval in seconds
- `TAXONOMY_REFRESH_MODE`: `merge` (default) or `replace`
- `DRY_RUN`: `true` for plan-only mode

## User-Controlled Settings

User control remains local even with GHCR images:
- `.env` for secrets and runtime flags
- `./configs` mounted to `/app/configs`
- `./cache`, `./logs`, `./reports` mounted for local state/output

## Config And Taxonomy Files

- App defaults: `configs/config.json`
- Taxonomy templates:
  - `configs/taxonomy/categories.json`
  - `configs/taxonomy/tags.json`
  - `configs/taxonomy/cookbooks.json`

## Project Layout

```text
.
|-- .github/workflows/publish-ghcr.yml
|-- configs/
|-- docs/
|-- scripts/
|-- src/mealie_organizer/
|-- tests/
|-- docker-compose.yml
|-- docker-compose.build.yml
|-- .env.example
|-- INSTALL.md
|-- UPDATE.md
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
