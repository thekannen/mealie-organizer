# Mealie Scripts

Scripts in this folder manage Mealie taxonomy and recipe categorization using either Ollama or ChatGPT.

## Files

- `reset_mealie_taxonomy.py`: wipes and reseeds categories/tags.
- `import_categories.py`: imports categories or tags from JSON files.
- `recipe_categorizer_ollama.py`: categorizes recipes using Ollama.
- `recipe_categorizer_chatgpt.py`: categorizes recipes using ChatGPT/OpenAI-compatible API.
- `categorizer_core.py`: shared categorization engine used by both provider scripts.
- `categories.json`: sample category import data.
- `tags.json`: sample tag import data.

## Setup

Run from repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Prefer automated install scripts when possible:
- Ubuntu: `scripts/install/ubuntu_setup_mealie.sh`
- Windows: `scripts/install/windows_setup_mealie.ps1`
- Full install docs: `scripts/install/README.md`

Direct Ubuntu bootstrap from server:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-scripts/main/scripts/install/ubuntu_setup_mealie.sh | bash
```

Fill required values in `.env`:
- `MEALIE_URL`
- `MEALIE_API_KEY`

Provider-specific values:
- Ollama: `OLLAMA_URL`, `OLLAMA_MODEL`
- ChatGPT: `OPENAI_API_KEY`, `OPENAI_MODEL`, optional `OPENAI_BASE_URL`

Shared tuning:
- `BATCH_SIZE`
- `MAX_WORKERS`
- optional `CACHE_FILE`

## Usage

Reset taxonomy:

```bash
python3 scripts/python/mealie/reset_mealie_taxonomy.py
```

Import categories from JSON:

```bash
python3 scripts/python/mealie/import_categories.py \
  --file scripts/python/mealie/categories.json \
  --endpoint categories
```

Import tags from JSON:

```bash
python3 scripts/python/mealie/import_categories.py \
  --file scripts/python/mealie/tags.json \
  --endpoint tags
```

Replace existing categories before importing:

```bash
python3 scripts/python/mealie/import_categories.py \
  --file scripts/python/mealie/categories.json \
  --endpoint categories \
  --replace
```

Categorize uncategorized recipes with Ollama:

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py
```

Categorize uncategorized recipes with ChatGPT:

```bash
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py
```

Re-categorize all recipes:

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py --recat
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py --recat
```

## Notes

- Run scripts from repo root to keep `.env` and cache paths consistent.
- Default provider caches are separate (`results_ollama.json`, `results_chatgpt.json`).
- These scripts call live Mealie APIs; test with caution on production data.
