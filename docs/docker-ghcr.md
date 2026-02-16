# Docker Deployment with GHCR

This project is deployed from GitHub Container Registry:

- `ghcr.io/thekannen/cookdex:<tag>`

## Pull and run

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
# edit required values in .env

docker compose -f compose.yaml pull cookdex
docker compose -f compose.yaml up -d cookdex
```

## Required env values

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

## Update

```bash
docker compose -f compose.yaml pull cookdex
docker compose -f compose.yaml up -d --remove-orphans cookdex
```

## Runtime control

Use the Web UI at `/cookdex` for runtime environment variables, scheduling, safety policies, and runs.