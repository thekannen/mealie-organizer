# Update

## GHCR deployment

```bash
docker compose pull mealie-organizer
docker compose up -d --remove-orphans mealie-organizer
```

## Repo-clone deployment

```bash
git pull --ff-only
docker compose build --pull mealie-organizer
docker compose up -d --remove-orphans mealie-organizer
```

## Post-update checks

1. Open `http://localhost:4820/organizer`
2. Confirm login succeeds
3. Confirm `/organizer/api/v1/health` returns `ok=true`
4. Queue a dry-run task and verify run logs

## Notes

- `TASK=webui-server` is the primary runtime mode.
- `TASK=plugin-server` still forwards to webui-server with a deprecation warning.