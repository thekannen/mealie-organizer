# Mealie Scripts

Scripts in this folder manage Mealie taxonomy and recipe categorization using either Ollama or ChatGPT.

## Files

- `reset_mealie_taxonomy.py`: wipes and reseeds categories/tags.
- `import_categories.py`: imports categories or tags from JSON files.
- `audit_taxonomy.py`: audits category/tag quality and usage and writes a report.
- `cleanup_tags.py`: dry-run/apply cleanup for low-value tags.
- `recipe_categorizer_ollama.py`: categorizes recipes using Ollama.
- `recipe_categorizer_chatgpt.py`: categorizes recipes using ChatGPT/OpenAI-compatible API.
- `categorizer_core.py`: shared categorization engine used by both provider scripts.
- `categories.json`: sample category import data.

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
- `TAG_MAX_NAME_LENGTH` (default `24`, excludes longer tags from AI assignment prompts)
- `TAG_MIN_USAGE` (default `0`, can exclude low-usage tags from AI assignment prompts)

Choose one provider for regular use (Ollama or ChatGPT), rather than scheduling both at the same time.

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
  --file /path/to/your/tags.json \
  --endpoint tags
```

Audit taxonomy quality/usage:

```bash
python3 scripts/python/mealie/audit_taxonomy.py
```

Preview tag cleanup candidates:

```bash
python3 scripts/python/mealie/cleanup_tags.py --only-unused --delete-noisy
```

Apply cleanup (deletes tags in Mealie):

```bash
python3 scripts/python/mealie/cleanup_tags.py --only-unused --delete-noisy --apply
```

Replace existing categories before importing:

```bash
python3 scripts/python/mealie/import_categories.py \
  --file scripts/python/mealie/categories.json \
  --endpoint categories \
  --replace
```

Categorize recipes missing categories or tags with Ollama (default mode):

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py
```

Categorize recipes missing categories or tags with ChatGPT (default mode):

```bash
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py
```

Only fill missing tags:

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py --missing-tags
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py --missing-tags
```

Only fill missing categories:

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py --missing-categories
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py --missing-categories
```

Re-categorize all recipes (choose one provider):

```bash
python3 scripts/python/mealie/recipe_categorizer_ollama.py --recat
python3 scripts/python/mealie/recipe_categorizer_chatgpt.py --recat
```

## Notes

- Run scripts from repo root to keep `.env` and cache paths consistent.
- Default provider caches are separate (`results_ollama.json`, `results_chatgpt.json`).
- These scripts call live Mealie APIs; test with caution on production data.
