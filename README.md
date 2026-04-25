# CookDex

<p>
  <img alt="Mealie" src="https://img.shields.io/badge/Mealie-v3-4caf50?labelColor=2e7d32&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776ab?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/github/license/thekannen/cookdex?color=f47a2a">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ed?logo=docker&logoColor=white">
</p>

CookDex is a web UI for keeping a self-hosted [Mealie](https://mealie.io) recipe library clean, searchable, and well organized.

It helps you import recipes, clean messy scraper results, keep categories and tags consistent, schedule maintenance jobs, and review library health without living in the command line.

![Overview](docs/screenshots/overview.png)

| | |
|---|---|
| ![Tasks](docs/screenshots/tasks.png) | ![Recipe Sources](docs/screenshots/recipe-sources.png) |
| ![Recipe Organization](docs/screenshots/taxonomy.png) | ![Settings](docs/screenshots/settings.png) |

## Who It Is For

CookDex is for people who already run Mealie and want help with the maintenance work that builds up over time:

- Recipes imported from many sites with inconsistent names, tags, and ingredients
- Duplicate foods, units, categories, tags, labels, or tools
- Recipes that need bulk cleanup after a large import
- A taxonomy that should be edited carefully before syncing to Mealie
- A repeatable way to run backups, audits, cleanup, and organization tasks

Most tasks start in preview mode, so you can inspect what CookDex would do before allowing live changes.

## Quick Start

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
docker compose pull cookdex
docker compose up -d cookdex
```

Open `https://your-server:4820/cookdex`, accept the self-signed certificate warning, and create the first admin account.

No `.env` file is required for normal setup. After login, open **Settings** and add:

- **Mealie Server URL**: the address for your Mealie instance plus `/api`, such as `http://mealie:9000/api`
- **Mealie API Key**: a token from your Mealie user profile

Click **Test Mealie**. When the connection passes, CookDex is ready.

## First Safe Run

Start with a read-only check:

1. Open **Tasks**.
2. Select **Health Check**.
3. Leave the default scopes enabled.
4. Click **Run** and review the log.

For cleanup tasks, keep **Preview Run** selected until the log shows exactly what you expect. CookDex will ask for an owner-level policy unlock before dangerous live changes.

## What You Can Do

CookDex includes workflows for:

- **Recipe dredging**: find recipes from curated source sites and import them into Mealie
- **Library cleanup**: remove duplicate URLs, filter junk pages, normalize names, and repair slugs
- **Ingredient parsing**: convert raw ingredient lines into structured Mealie foods, units, and quantities
- **Taxonomy editing**: draft, validate, publish, and sync categories, tags, cookbooks, labels, tools, and unit aliases
- **Recipe organization**: tag and categorize recipes with rules first, then optional AI
- **Maintenance scheduling**: run tasks once or on an interval
- **Backups and audits**: create Mealie backups and track recipe quality over time

Optional AI providers can help with categorization and parser fallback. Rule-based categorization works without any AI key.

Optional Direct DB access can make large read/write jobs much faster and can repair cases that Mealie's HTTP API cannot update. The normal path still works through the Mealie API.

## Updating

```bash
docker compose pull cookdex
docker compose up -d --remove-orphans cookdex
```

Then open CookDex and confirm you can log in. You can also check:

```bash
curl -k https://localhost:4820/cookdex/api/v1/health
```

## Privacy And Safety

CookDex runs on your server and does not include telemetry or analytics.

- Credentials are stored locally and encrypted at rest.
- Session cookies are used only for authentication.
- Tasks run with a minimal environment instead of inheriting all host variables.
- Preview mode is the default for write-capable tasks.
- If AI categorization is enabled, only the recipe text needed for that task is sent to your configured provider.

## Learn More

- [Install](docs/INSTALL.md) - deployment details and volume notes
- [Getting Started](docs/GETTING_STARTED.md) - first login and first task run
- [Tasks and API](docs/TASKS.md) - task options, schedules, safety policies, and API routes
- [Data Maintenance](docs/DATA_MAINTENANCE.md) - the staged cleanup pipeline
- [Direct DB Access](docs/DIRECT_DB.md) - optional faster database-backed operations
- [Local Dev](docs/LOCAL_DEV.md) - run and test CookDex from source
