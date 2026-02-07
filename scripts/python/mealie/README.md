# Mealie Scripts

Scripts in this folder manage Mealie taxonomy and recipe categorization using either Ollama or ChatGPT.
Core implementation now lives in `src/mealie_scripts/`; scripts in this folder are CLI entrypoints and compatibility wrappers.

## Files

- `taxonomy_manager.py`: consolidated taxonomy lifecycle manager (reset/import/cleanup/refresh).
- `reset_mealie_taxonomy.py`: compatibility wrapper for taxonomy reset.
- `import_categories.py`: compatibility wrapper for taxonomy import.
- `audit_taxonomy.py`: audits category/tag quality and usage and writes a report.
- `cleanup_tags.py`: compatibility wrapper for tag cleanup.
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
pip install -e .[dev]
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

Recommended: streamlined taxonomy refresh (single command):

```bash
python3 scripts/python/mealie/taxonomy_manager.py refresh \
  --categories-file scripts/python/mealie/categories.json \
  --replace-categories \
  --cleanup --cleanup-only-unused --cleanup-delete-noisy
```

Reset taxonomy:

```bash
python3 scripts/python/mealie/taxonomy_manager.py reset \
  --categories-file scripts/python/mealie/categories.json
```

Import categories from JSON:

```bash
python3 scripts/python/mealie/taxonomy_manager.py import \
  --file scripts/python/mealie/categories.json \
  --endpoint categories
```

Import tags from JSON:

```bash
python3 scripts/python/mealie/taxonomy_manager.py import \
  --file scripts/python/mealie/tags.json \
  --endpoint tags
```

Audit taxonomy quality/usage:

```bash
python3 scripts/python/mealie/audit_taxonomy.py
```

Preview tag cleanup candidates:

```bash
python3 scripts/python/mealie/taxonomy_manager.py cleanup --only-unused --delete-noisy
```

Apply cleanup (deletes tags in Mealie):

```bash
python3 scripts/python/mealie/taxonomy_manager.py cleanup --only-unused --delete-noisy --apply
```

Replace existing categories before importing:

```bash
python3 scripts/python/mealie/taxonomy_manager.py import \
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
- Legacy scripts (`reset_mealie_taxonomy.py`, `import_categories.py`, `cleanup_tags.py`) now delegate to `taxonomy_manager.py`.
