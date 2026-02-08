# Mealie Organizer

Standalone organizer utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset/import/cleanup lifecycle manager
- Recipe categorization via Ollama or ChatGPT/OpenAI-compatible APIs
- Taxonomy auditing and cleanup tooling
- Cookbook sync and organization views
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
│       ├── tags.json
│       └── cookbooks.json
├── src/
│   └── mealie_organizer/
│       ├── __init__.py
│       ├── config.py
│       ├── taxonomy_manager.py
│       ├── audit_taxonomy.py
│       ├── cookbook_manager.py
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
│   ├── test_recipe_categorizer.py
│   └── test_cookbook_manager.py
├── .env.example
├── pyproject.toml
└── README.md
```

## Configuration Model

- `configs/config.json`: central non-secret defaults (provider, models, paths, batch sizes, retries).
- `.env`: environment-specific user settings and secrets (especially useful in Docker/Portainer). Values here override `configs/config.json`.

Precedence:
1. CLI flags (where supported)
2. Environment variables (`.env`, Docker env, Portainer env)
3. `configs/config.json`
4. Hardcoded fallback in code

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
- `.env` with required user settings and secrets (at minimum `MEALIE_URL` and `MEALIE_API_KEY`; include `OPENAI_API_KEY` if using ChatGPT provider)
- `configs/config.json` configured for your Mealie instance

If your Ollama instance is not local to the container, set `OLLAMA_URL` in `.env` (or Portainer env vars) to:

```text
http://host.docker.internal:11434/api
```

`OLLAMA_URL` overrides `providers.ollama.url` in `configs/config.json`.

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

Cookbook sync once:

```bash
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer
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

Cookbook sync:

```bash
python3 -m mealie_organizer.cookbook_manager sync
```

Cookbook sync with cleanup of unmanaged cookbooks:

```bash
python3 -m mealie_organizer.cookbook_manager sync --replace
```

Categorize recipes:

```bash
python3 -m mealie_organizer.recipe_categorizer
```

Installed command aliases (after `pip install -e .`):

```bash
mealie-categorizer
mealie-taxonomy
mealie-taxonomy-audit
mealie-cookbooks
```

Provider selection:

- Set `CATEGORIZER_PROVIDER` in `.env` (or container env vars) to `ollama` or `chatgpt` for deployment-specific behavior.
- Or override per command with `--provider`.

Run modes:

```bash
python3 -m mealie_organizer.recipe_categorizer --missing-tags
python3 -m mealie_organizer.recipe_categorizer --missing-categories
python3 -m mealie_organizer.recipe_categorizer --recat
```

Dry-run mode (env-driven):

```bash
DRY_RUN=true
```

With dry-run enabled, taxonomy imports/cleanup, cookbook sync actions, and recipe metadata updates are logged as `[plan]` actions and no write requests are sent to Mealie.

## Development

Run tests:

```bash
python3 -m pytest
```

## Notes

- Default provider behavior is controlled by `configs/config.json`; deployment-specific model selection should be set via env vars (`CATEGORIZER_PROVIDER`, `OLLAMA_MODEL`, `OPENAI_MODEL`, `OLLAMA_URL`).
- Keep environment-specific settings and secrets in `.env`; keep reusable defaults in `configs/config.json` and cookbook definitions in `configs/taxonomy/cookbooks.json`.
