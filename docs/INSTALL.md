# Install

CookDex is deployed from GitHub Container Registry (`ghcr.io/thekannen/cookdex`).

## 1. Download the compose file

```bash
mkdir -p cookdex && cd cookdex
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/compose.ghcr.yml -o compose.yaml
```

No `.env` file is required. To override defaults (port, base path, etc.), optionally download and edit `.env.example`:

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/cookdex/main/.env.example -o .env
```

## 2. Start the service

```bash
docker compose pull cookdex
docker compose up -d cookdex
```

## 3. Open the Web UI and complete setup

Open `http://localhost:4820/cookdex` in your browser.

1. Create your admin account (first-time setup screen).
2. Navigate to **Settings**.
3. Enter your **Mealie Server URL** and **Mealie API Key**.
4. Click **Test Mealie** to verify the connection.

## Required volumes

| Host path | Container path | Purpose |
|---|---|---|
| `./configs` | `/app/configs` | Taxonomy JSON config files |
| `./cache` | `/app/cache` | SQLite state database and encryption key |
| `./logs` | `/app/logs` | Task run log files |
| `./reports` | `/app/reports` | Audit and maintenance reports |

The `./cache` volume stores the state database and the auto-generated encryption key. Keep this volume persistent.

## Updating

```bash
docker compose pull cookdex
docker compose up -d --remove-orphans cookdex
```

After updating, verify login and check `/cookdex/api/v1/health`.

## Notes

- All runtime settings are managed from the Settings page after login.
- Secrets are encrypted at rest using an auto-generated key (stored in `./cache`).
- An optional `.env` file can pre-seed settings or override defaults for headless deployments.
