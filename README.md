# Mealie Automation Scripts

Standalone utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset/import/cleanup lifecycle manager
- Recipe categorization via Ollama or ChatGPT/OpenAI-compatible APIs
- Taxonomy auditing and cleanup tooling
- Ubuntu and Windows setup scripts

## Structure

```text
.
├── configs/
│   ├── config.json
│   └── taxonomy/
│       ├── categories.json
│       └── tags.json
├── src/
│   └── mealie_scripts/
│       ├── __init__.py
│       ├── config.py
│       ├── taxonomy_manager.py
│       ├── audit_taxonomy.py
│       ├── categorizer_core.py
│       ├── recipe_categorizer_ollama.py
│       └── recipe_categorizer_chatgpt.py
├── scripts/
│   └── install/
│       ├── ubuntu_setup_mealie.sh
│       └── windows_setup_mealie.ps1
├── tests/
│   ├── test_categorizer_core.py
│   └── test_taxonomy_manager.py
├── .env.example
├── pyproject.toml
└── README.md
```

## Configuration Model

- `configs/config.json`: central non-secret defaults (paths, models, batch sizes, retries).
- `.env`: secrets and environment-specific overrides.

Precedence:
1. Environment / `.env`
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

## Install Scripts

### Ubuntu

Run from cloned repo:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

Run directly on server:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | bash
```

Common flags:
- `--target-dir <dir>` clone/update target (default `$HOME/mealie-scripts`)
- `--repo-url <url>` override repo URL
- `--repo-branch <branch>` override branch
- `--use-current-repo` use current path and skip clone/update
- `--update` update repo only, then exit
- `--provider <ollama|chatgpt>` cron provider selection
- `--install-ollama` install Ollama if missing
- `--skip-apt-update` skip apt update
- `--setup-cron` configure cron job
- `--cron-schedule "<expr>"` cron schedule for selected provider

Cron examples:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | \
bash -s -- --provider ollama --install-ollama --setup-cron --cron-schedule "0 */6 * * *"
```

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | \
bash -s -- --provider chatgpt --setup-cron --cron-schedule "0 */6 * * *"
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install\windows_setup_mealie.ps1
```

Optional flag: `-InstallOllama`

## Usage

Taxonomy refresh:

```bash
python3 -m mealie_scripts.taxonomy_manager refresh \
  --categories-file configs/taxonomy/categories.json \
  --tags-file configs/taxonomy/tags.json \
  --replace-categories --replace-tags \
  --cleanup --cleanup-only-unused --cleanup-delete-noisy
```

Taxonomy import:

```bash
python3 -m mealie_scripts.taxonomy_manager import \
  --file configs/taxonomy/categories.json \
  --endpoint categories --replace
```

```bash
python3 -m mealie_scripts.taxonomy_manager import \
  --file configs/taxonomy/tags.json \
  --endpoint tags --replace
```

Taxonomy audit:

```bash
python3 -m mealie_scripts.audit_taxonomy
```

Categorize recipes:

```bash
python3 -m mealie_scripts.recipe_categorizer_ollama
python3 -m mealie_scripts.recipe_categorizer_chatgpt
```

Provider-specific modes:

```bash
python3 -m mealie_scripts.recipe_categorizer_chatgpt --missing-tags
python3 -m mealie_scripts.recipe_categorizer_ollama --missing-categories
python3 -m mealie_scripts.recipe_categorizer_chatgpt --recat
```

## Development

Run tests:

```bash
python3 -m pytest
```

## Notes

- Use one provider in cron at a time.
- Keep secrets only in `.env`; do not store them in `config.json`.
