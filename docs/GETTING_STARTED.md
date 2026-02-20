# Getting Started

## 1) Configure startup env

Copy `.env.example` to `.env` and set:

- `MEALIE_URL`
- `MEALIE_API_KEY`
- `WEB_BOOTSTRAP_PASSWORD`
- `MO_WEBUI_MASTER_KEY`

## 2) Launch service

```bash
docker compose pull cookdex
docker compose up -d cookdex
```

## 3) Open Web UI

`http://localhost:4820/cookdex`

## 4) First login

- Username: `WEB_BOOTSTRAP_USER` (default `admin`)
- Password: `WEB_BOOTSTRAP_PASSWORD`

## 5) Verify health

```bash
curl http://localhost:4820/cookdex/api/v1/health
```

## 6) Configure runtime variables in UI

Use **Environment Variables** in the UI to manage `.env`-style runtime keys and secrets.

## 7) Run a dry task

- Open **Run Task**
- Pick `ingredient-parse`
- Keep `dry_run=true`
- Queue run and inspect logs