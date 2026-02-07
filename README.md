# Mealie Automation Scripts

Standalone utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset and import tools
- Recipe categorization via Ollama or ChatGPT / OpenAI-compatible APIs
- Ubuntu and Windows setup scripts

## Structure

```text
.
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
│           └── reset_mealie_taxonomy.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
