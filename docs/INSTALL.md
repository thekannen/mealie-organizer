# Install

## Standard Deployment (GHCR)

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
```

Edit `.env`:

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

Start:

```bash
docker compose -f compose.yaml pull cookdex
docker compose -f compose.yaml up -d cookdex
```

Open:

`http://localhost:4820/cookdex`

## Required volumes

- `./configs` -> `/app/configs`
- `./cache` -> `/app/cache`
- `./logs` -> `/app/logs`
- `./reports` -> `/app/reports`

## Notes

- GHCR is the deployment baseline for this project.
- Runtime variable management is available in the Web UI after login.
- Secrets are encrypted at rest using `MO_WEBUI_MASTER_KEY`.