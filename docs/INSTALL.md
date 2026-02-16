# Install

## Standard Deployment (GHCR)

```bash
mkdir -p mealie-organizer && cd mealie-organizer
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/compose.ghcr.yml -o compose.yaml
```

Edit `.env`:

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

Start:

```bash
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d mealie-organizer
```

Open:

`http://localhost:4820/organizer`

## Required volumes

- `./configs` -> `/app/configs`
- `./cache` -> `/app/cache`
- `./logs` -> `/app/logs`
- `./reports` -> `/app/reports`

## Notes

- GHCR is the deployment baseline for this project.
- Runtime variable management is available in the Web UI after login.
- Secrets are encrypted at rest using `MO_WEBUI_MASTER_KEY`.