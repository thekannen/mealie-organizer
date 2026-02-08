# Mealie Organizer

Mealie Organizer is a Python automation toolchain for Mealie that keeps recipe metadata clean and useful.

It can:
- Apply and maintain category/tag taxonomy templates
- Sync cookbook templates
- Categorize/tag recipes with Ollama or ChatGPT-compatible APIs
- Audit taxonomy quality and output a report
- Run once or continuously in Docker

## Why this exists

As recipe libraries grow, tags and categories become noisy and inconsistent. This project gives you repeatable workflows to keep taxonomy organized without manual cleanup every week.

## Project layout

```text
.
├── configs/
│   ├── config.json
│   └── taxonomy/
│       ├── categories.json
│       ├── tags.json
│       └── cookbooks.json
├── scripts/
│   ├── docker/
│   │   ├── entrypoint.sh
│   │   └── update.sh
│   └── install/
│       └── ubuntu_setup_mealie.sh
├── src/mealie_organizer/
├── tests/
├── .env.example
├── docker-compose.yml
└── README.md
```

## Configuration model

Use both files, but for different purposes:
- `.env`: user and environment settings, secrets, deployment-specific values
- `configs/config.json`: non-secret defaults (timeouts, retries, batching, taxonomy file locations)

Priority order:
1. CLI flags (where available)
2. Environment variables (`.env`, Docker env vars, Portainer env vars)
3. `configs/config.json`
4. Hardcoded fallback defaults

## Quick start (Docker, recommended)

1. Clone the repo.

```bash
git clone https://github.com/thekannen/mealie-organizer.git
cd mealie-organizer
```

2. Create your environment file.

```bash
cp .env.example .env
```

3. Edit `.env`.

Required for all modes:
- `MEALIE_URL`
- `MEALIE_API_KEY`

Provider selection:
- `CATEGORIZER_PROVIDER=ollama` or `chatgpt`

If using Ollama:
- `OLLAMA_URL`
- `OLLAMA_MODEL`

If using ChatGPT/OpenAI-compatible:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- Optional: `OPENAI_BASE_URL` for compatible providers

4. Build and start.

```bash
docker compose up -d --build
```

5. Watch logs.

```bash
docker compose logs -f mealie-organizer
```

6. Optional one-shot runs.

```bash
# Categorize once
docker compose run --rm -e RUN_MODE=once mealie-organizer

# Taxonomy refresh once (safe merge mode)
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer

# Cookbook sync once
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer
```

## Runtime modes

Container behavior is controlled by env vars:
- `TASK`: `categorize`, `taxonomy-refresh`, `taxonomy-audit`, `cookbook-sync`
- `RUN_MODE`: `once` or `loop`
- `RUN_INTERVAL_SECONDS`: loop interval (default `21600`)

Defaults in `docker-compose.yml` run categorize in loop mode every 6 hours.

## Taxonomy refresh behavior

`TASK=taxonomy-refresh` supports two modes:
- `merge` (default): keep existing organizer data, add missing template values
- `replace`: delete existing categories/tags, then recreate from template (destructive)

Set via:
- `.env`: `TAXONOMY_REFRESH_MODE=merge|replace`
- or runtime override: `-e TAXONOMY_REFRESH_MODE=replace`

## Dry-run mode

Set `DRY_RUN=true` to preview write operations.

In dry-run mode:
- Taxonomy imports/deletes are printed as `[plan]`
- Cookbook create/update/delete is printed as `[plan]`
- Recipe metadata writes are skipped

## Taxonomy templates

Template files live in `configs/taxonomy/`:
- `categories.json`
- `tags.json`
- `cookbooks.json`

Current templates include an `Originals` category/cookbook for manually created or non-URL-import recipes.

### Cookbook filter note

Cookbook queries can be defined with category/tag names in `cookbooks.json`. During sync, the manager resolves names to IDs so Mealie's cookbook editor displays filters correctly.

## Update and redeploy

Use the helper script:

```bash
./scripts/docker/update.sh
```

Useful options:
- `--skip-git-pull`
- `--no-build`
- `--branch <name>`
- `--prune`

Manual equivalent:

```bash
git pull
docker compose up -d --build --remove-orphans mealie-organizer
```

## Versioning

This repo uses SemVer with a single source of truth in `VERSION`.

- Package metadata reads version from `VERSION` (via `pyproject.toml` dynamic version)
- Runtime `mealie_organizer.__version__` resolves to installed package version, or `VERSION` when running from source
- Release helper: `scripts/release.sh`

Examples:

```bash
# bump patch (e.g. 0.1.0 -> 0.1.1)
scripts/release.sh patch

# bump minor and create git tag
scripts/release.sh minor --tag

# set exact version
scripts/release.sh 1.0.0 --tag
```

## Local development (macOS/Linux)

1. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
pip install -e .
```

3. Create env file.

```bash
cp .env.example .env
```

4. Run tools.

```bash
# Categorizer
PYTHONPATH=src python3 -m mealie_organizer.recipe_categorizer

# Taxonomy refresh (merge)
PYTHONPATH=src python3 -m mealie_organizer.taxonomy_manager refresh \
  --mode merge \
  --categories-file configs/taxonomy/categories.json \
  --tags-file configs/taxonomy/tags.json \
  --cleanup --cleanup-only-unused --cleanup-delete-noisy

# Cookbook sync
PYTHONPATH=src python3 -m mealie_organizer.cookbook_manager sync

# Taxonomy audit
PYTHONPATH=src python3 -m mealie_organizer.audit_taxonomy
```

Installed CLI aliases after `pip install -e .`:
- `mealie-categorizer`
- `mealie-taxonomy`
- `mealie-cookbooks`
- `mealie-taxonomy-audit`

## Ubuntu helper script

You can bootstrap on Ubuntu with:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

Or remote-run:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/ubuntu_setup_mealie.sh | bash
```

Notable flags:
- `--setup-cron`
- `--cron-schedule "0 */6 * * *"`
- `--provider <ollama|chatgpt>`
- `--install-ollama`
- `--update`

## Troubleshooting

- `MEALIE_URL is not configured`: make sure `.env` has a real URL, not placeholder text.
- `source: no such file or directory: .venv/bin/activate`: create the venv first with `python3 -m venv .venv`.
- Ollama in Docker cannot connect to host: set `OLLAMA_URL=http://host.docker.internal:11434/api` and keep `extra_hosts` in compose.
- Frequent provider retry warnings: reduce concurrency (`BATCH_SIZE`, `MAX_WORKERS`), increase request timeout, or use stronger model capacity.

## Testing

```bash
python3 -m pytest
```
