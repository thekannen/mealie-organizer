# Docker Deployment with GHCR

This project is deployed from GitHub Container Registry:

- `ghcr.io/thekannen/mealie-organizer:<tag>`

## Pull and run

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/compose.ghcr.yml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/.env.example -o .env
# edit required values in .env

docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d mealie-organizer
```

## Required env values

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

## Update

```bash
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d --remove-orphans mealie-organizer
```

## Runtime control

Use the Web UI at `/organizer` for runtime environment variables, scheduling, safety policies, and runs.