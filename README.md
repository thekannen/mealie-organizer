# Mealie Automation Scripts

Standalone utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset and import tools
- Recipe categorization via Ollama or ChatGPT / OpenAI-compatible APIs
- Ubuntu and Windows setup scripts

## Structure

```text
.
├── src/
│   └── mealie_scripts/
│       ├── __init__.py
│       ├── audit_taxonomy.py
│       ├── categorizer_core.py
│       ├── recipe_categorizer_chatgpt.py
│       ├── recipe_categorizer_ollama.py
│       └── taxonomy_manager.py
├── tests/
│   ├── test_categorizer_core.py
│   └── test_taxonomy_manager.py
├── scripts/
│   ├── install/
│   │   ├── README.md
│   │   ├── ubuntu_setup_mealie.sh
│   │   └── windows_setup_mealie.ps1
│   └── python/
│       └── mealie/
│           ├── README.md
│           ├── audit_taxonomy.py
│           ├── categories.json
│           ├── cleanup_tags.py
│           ├── categorizer_core.py
│           ├── import_categories.py
│           ├── recipe_categorizer_chatgpt.py
│           ├── recipe_categorizer_ollama.py
│           ├── reset_mealie_taxonomy.py
│           ├── tags.json
│           └── taxonomy_manager.py
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .[dev]
cp .env.example .env
```

## Provider Preference

Pick one provider at a time:
- `ollama` for local inference
- `chatgpt` for OpenAI-compatible APIs

Do not run both providers on cron simultaneously. The Ubuntu installer enforces a single provider when `--setup-cron` is used.

## Documentation

- Install and cron setup: `scripts/install/README.md`
- Mealie script usage: `scripts/python/mealie/README.md`
