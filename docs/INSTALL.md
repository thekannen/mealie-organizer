# Install

CookDex is deployed from GitHub Container Registry (`ghcr.io/thekannen/cookdex`).

## 1. Download config files

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
```

## 2. Configure environment

Edit `.env` and set the required values:

| Variable | Description |
|---|---|
| `MEALIE_URL` | Mealie API base URL (e.g. `http://mealie:9000/api`) |
| `MEALIE_API_KEY` | Mealie API key with write access |
| `WEB_BOOTSTRAP_PASSWORD` | Initial admin password (omit to use first-time registration flow) |
| `MO_WEBUI_MASTER_KEY` | Fernet key for encrypting secrets at rest |

## 3. Start the service

```bash
docker compose pull cookdex
docker compose up -d cookdex
```

## 4. Open the Web UI

`http://localhost:4820/cookdex`

Log in with the `WEB_BOOTSTRAP_USER` (default `admin`) and the password from `WEB_BOOTSTRAP_PASSWORD`.

## Required volumes

| Host path | Container path | Purpose |
|---|---|---|
| `./configs` | `/app/configs` | Taxonomy JSON config files |
| `./cache` | `/app/cache` | SQLite state database |
| `./logs` | `/app/logs` | Task run log files |
| `./reports` | `/app/reports` | Audit and maintenance reports |

## Updating

```bash
docker compose pull cookdex
docker compose up -d --remove-orphans cookdex
```

After updating, verify login and check `/cookdex/api/v1/health`.

## Notes

- Runtime variable management is available in the Web UI after login.
- Secrets are encrypted at rest using `MO_WEBUI_MASTER_KEY`.
- GHCR is the standard deployment path for this project.
