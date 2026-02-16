# Getting Started

## 1. Prepare environment

Copy `.env.example` to `.env` and set:

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

## 2. Start service

```bash
docker compose up -d mealie-organizer
```

## 3. Open Web UI

`http://localhost:4820/organizer`

## 4. First login

- Username: `WEB_BOOTSTRAP_USER` (default `admin`)
- Password: `WEB_BOOTSTRAP_PASSWORD`

## 5. Validate health

```bash
curl http://localhost:4820/organizer/api/v1/health
```

Expected:

```json
{"ok":true,"base_path":"/organizer"}
```

## 6. Run first dry task from UI

- Open **Run Task**
- Choose `ingredient-parse`
- Keep `dry_run=true`
- Click **Queue Run**
- Inspect run log in **Run History**

## Notes

- Write-capable options are blocked by default.
- Enable dangerous task behavior with per-task policy toggles in the UI.
- Scheduling and secrets are also managed in the UI.