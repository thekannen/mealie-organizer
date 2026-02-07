# Mealie Automation Scripts

Standalone utilities for managing Mealie taxonomy and AI-powered categorization.

## Included

- Taxonomy reset and import tools
- Recipe categorization via Ollama
- Recipe categorization via ChatGPT / OpenAI-compatible APIs
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
│           ├── categories.json
│           ├── tags.json
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

Then follow:
- `scripts/install/README.md`
- `scripts/python/mealie/README.md`
