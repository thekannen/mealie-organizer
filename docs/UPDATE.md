# Update

## GHCR deployment update

```bash
docker compose -f compose.ghcr.yml pull mealie-organizer
docker compose -f compose.ghcr.yml up -d --remove-orphans mealie-organizer
```

## Post-update checks

1. Open `http://localhost:4820/organizer`
2. Verify login succeeds
3. Verify `/organizer/api/v1/health` returns `ok=true`
4. Queue one dry-run task and inspect logs