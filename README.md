# Mealie Organizer

Standalone organizer utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset/import/cleanup lifecycle manager
- Recipe categorization via Ollama or ChatGPT/OpenAI-compatible APIs
- Taxonomy auditing and cleanup tooling
- Ubuntu setup script
- Docker deployment path

## Structure

```text
.
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── configs/
│   ├── config.json
│   └── taxonomy/
│       ├── categories.json
│       └── tags.json
├── src/
│   └── mealie_organizer/
│       ├── __init__.py
│       ├── config.py
│       ├── taxonomy_manager.py
│       ├── audit_taxonomy.py
│       ├── categorizer_core.py
│       ├── recipe_categorizer.py
│       ├── recipe_categorizer_ollama.py
│       └── recipe_categorizer_chatgpt.py
├── scripts/
│   ├── docker/
│   │   └── entrypoint.sh
│   └── install/
│       └── ubuntu_setup_mealie.sh
├── tests/
│   ├── test_categorizer_core.py
│   ├── test_taxonomy_manager.py
│   └── test_recipe_categorizer.py
├── .env.example
├── pyproject.toml
└── README.md
```

## Configuration Model

- `configs/config.json`: central non-secret defaults (provider, models, paths, batch sizes, retries).
- `.env`: secrets only.

Precedence:
1. CLI flags (where supported)
2. `configs/config.json`
3. Hardcoded fallback in code

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .[dev]
cp .env.example .env
```

## Docker Deployment

### Prerequisites

- Docker Engine + Docker Compose plugin
- `.env` with required secrets (at minimum `MEALIE_API_KEY`; include `OPENAI_API_KEY` if using ChatGPT provider)
- `configs/config.json` configured for your Mealie instance

If your Ollama instance runs on the Docker host, set `providers.ollama.url` in `configs/config.json` to:

```text
http://host.docker.internal:11434/api
```

### Start as a long-running service

```bash
docker compose up -d --build
```

Defaults in `docker-compose.yml`:
- `TASK=categorize`
- `RUN_MODE=loop`
- `RUN_INTERVAL_SECONDS=21600` (every 6 hours)

### Run one-shot jobs

Categorizer once:

```bash
docker compose run --rm -e RUN_MODE=once mealie-organizer
```

Taxonomy refresh once:

```bash
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer
```

Taxonomy audit once:

```bash
docker compose run --rm -e TASK=taxonomy-audit -e RUN_MODE=once mealie-organizer
```

### Update and redeploy

```bash
git pull
docker compose up -d --build
```

### Logs and stop

```bash
docker compose logs -f mealie-organizer
docker compose down
```

## Install Scripts

### Ubuntu

Run from cloned repo:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

Run directly on server:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/ubuntu_setup_mealie.sh | bash
```

Common flags:
- `--target-dir <dir>` clone/update target (default `$HOME/mealie-organizer`)
- `--repo-url <url>` override repo URL
- `--repo-branch <branch>` override branch
- `--use-current-repo` use current path and skip clone/update
- `--update` update repo only, then exit
- `--provider <ollama|chatgpt>` optional cron provider override (otherwise uses `configs/config.json`)
- `--install-ollama` install Ollama if missing
- `--skip-apt-update` skip apt update
- `--setup-cron` configure cron job
- `--cron-schedule "<expr>"` cron schedule for the unified categorizer job

Cron examples:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/ubuntu_setup_mealie.sh | \
bash -s -- --setup-cron --cron-schedule "0 */6 * * *"
```

## Usage

Taxonomy refresh:

```bash
python3 -m mealie_organizer.taxonomy_manager refresh \
  --categories-file configs/taxonomy/categories.json \
  --tags-file configs/taxonomy/tags.json \
  --replace-categories --replace-tags \
  --cleanup --cleanup-only-unused --cleanup-delete-noisy
```

Taxonomy import:

```bash
python3 -m mealie_organizer.taxonomy_manager import \
  --file configs/taxonomy/categories.json \
  --endpoint categories --replace
```

```bash
python3 -m mealie_organizer.taxonomy_manager import \
  --file configs/taxonomy/tags.json \
  --endpoint tags --replace
```

Taxonomy audit:

```bash
python3 -m mealie_organizer.audit_taxonomy
```

Categorize recipes:

```bash
python3 -m mealie_organizer.recipe_categorizer
```

Installed command alias (after `pip install -e .`):

```bash
mealie-categorizer
```

Provider selection:

- Set `categorizer.provider` in `configs/config.json` to `ollama` or `chatgpt` (single source of truth).
- Or override per command with `--provider`.

Run modes:

```bash
python3 -m mealie_organizer.recipe_categorizer --missing-tags
python3 -m mealie_organizer.recipe_categorizer --missing-categories
python3 -m mealie_organizer.recipe_categorizer --recat
```

## Development

Run tests:

```bash
python3 -m pytest
```

## Notes

- Default provider and model are controlled by `configs/config.json`.
- Keep secrets only in `.env`; keep non-secret runtime settings in `configs/config.json`.
