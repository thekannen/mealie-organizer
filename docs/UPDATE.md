# Update

## GHCR deployment update

```bash
docker compose -f compose.ghcr.yml pull cookdex
docker compose -f compose.ghcr.yml up -d --remove-orphans cookdex
```

## Post-update checks

1. Open `http://localhost:4820/cookdex`
2. Verify login succeeds
3. Verify `/cookdex/api/v1/health` returns `ok=true`
4. Queue one dry-run task and inspect logs