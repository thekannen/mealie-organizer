# Getting Started: First Taxonomy Sync

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

Use this runbook right after install to bootstrap your Mealie taxonomy from this repo's templates.

## What This Sync Covers

- Categories and tags from `configs/taxonomy/categories.json` and `configs/taxonomy/tags.json`
- Cookbooks from `configs/taxonomy/cookbooks.json`
- Labels from `configs/taxonomy/labels.json`
- Tools from `configs/taxonomy/tools.json`

Optional after initial sync:

- Units cleanup from `configs/taxonomy/units_aliases.json`
- Taxonomy audit report generation

## Before You Start

1. Set `MEALIE_URL` and `MEALIE_API_KEY` in `.env`.
2. Review and customize taxonomy files under `configs/taxonomy/`.
3. Take a Mealie backup snapshot before your first apply run.

## Command Prefix

Use the command style that matches your deployment:

```bash
# GHCR no-clone layout
docker compose -f compose.yaml ...

# Repo-clone layout
docker compose ...
```

The examples below use repo-clone syntax. For GHCR no-clone, add `-f compose.yaml`.

## Step 1: Dry-Run Review

```bash
docker compose run --rm -e TASK=taxonomy-refresh -e DRY_RUN=true -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=cookbook-sync -e DRY_RUN=true -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=labels-sync -e DRY_RUN=true -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=tools-sync -e DRY_RUN=true -e RUN_MODE=once mealie-organizer
```

Review logs for planned creates/updates/deletes before applying.

## Step 2: Apply Bootstrap Sync

```bash
docker compose run --rm -e TASK=taxonomy-refresh -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=cookbook-sync -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=labels-sync -e CLEANUP_APPLY=true -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=tools-sync -e CLEANUP_APPLY=true -e RUN_MODE=once mealie-organizer
```

Notes:

- `taxonomy-refresh` writes categories/tags when `DRY_RUN` is not set to `true`.
- `labels-sync` and `tools-sync` require `CLEANUP_APPLY=true` for write mode.

## Step 3: Verify With Audit

```bash
docker compose run --rm -e TASK=taxonomy-audit -e RUN_MODE=once mealie-organizer
```

Then review `reports/taxonomy_audit_report.json`.

## Optional: Units Standardization Pass

Run this only after tuning `configs/taxonomy/units_aliases.json`.

```bash
docker compose run --rm -e TASK=units-cleanup -e RUN_MODE=once mealie-organizer
docker compose run --rm -e TASK=units-cleanup -e CLEANUP_APPLY=true -e RUN_MODE=once mealie-organizer
```
