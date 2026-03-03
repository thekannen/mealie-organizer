# Repository Hygiene

Use the cleanup script to keep local working copies small and consistent without touching tracked source files.

## Quick Usage

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/clean_repo.ps1
```

This removes transient local artifacts:
- Python/test caches (`__pycache__`, `.pytest_*`, `.ruff_cache`, `.coverage*`)
- Build outputs (`build/`, `dist/`, `web/dist/`, `web/.vite/`)
- QA artifacts (`web/reports/`, `qa-*.png`)

## Optional Cleanup Levels

Remove local dependencies too (largest space savings):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/clean_repo.ps1 -IncludeDependencies
```

Also remove local runtime data and reports:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/clean_repo.ps1 -IncludeRuntime
```

Preview what would be deleted without deleting anything:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/clean_repo.ps1 -DryRun
```

## Recommended Routine

1. Run dry-run weekly when actively developing.
2. Run default cleanup before opening a PR.
3. Use `-IncludeDependencies` only when you explicitly want to reinstall environments.
4. Use `-IncludeRuntime` only after exporting any logs/reports you need.
