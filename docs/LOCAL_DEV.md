# Local Dev Testing

Run the web UI locally without building a Docker image. This starts the Python backend (which serves the built frontend) directly on your machine.

## Prerequisites

- Python 3.11+ with the repo installed (`pip install -e .`)
- Node 18+ (for frontend builds)
- A `.env` file in the repo root (copy from `.env.example`)

## 1. Install dependencies (one-time)

```bash
pip install -e ".[dev]"
cd web && npm install && cd ..
```

## 2. Build the frontend

```bash
cd web && npm run build && cd ..
```

The backend serves files from `web/dist/` automatically when the directory exists.

## 3. Set minimal env vars

Your `.env` needs at least these for the UI to start. For local testing without a real Mealie instance, use placeholder values:

```bash
# .env
MEALIE_URL=http://127.0.0.1:9000/api
MEALIE_API_KEY=placeholder
WEB_BOOTSTRAP_USER=admin
WEB_BOOTSTRAP_PASSWORD=DevPass-1
MO_WEBUI_MASTER_KEY=local-dev-testing-key
WEB_COOKIE_SECURE=false
```

`WEB_COOKIE_SECURE=false` is required for `http://localhost` (no HTTPS).

## 4. Start the server

```bash
python -m cookdex.webui_server.main
```

Open `http://localhost:4820/cookdex`.

## Quick restart loop

After making backend changes, Ctrl-C and re-run step 4. For frontend changes, rebuild first:

```bash
cd web && npm run build && cd .. && python -m cookdex.webui_server.main
```

Or as a one-liner:

```bash
cd web && npm run build && cd .. && python -m cookdex.webui_server.main
```

## Vite dev server (frontend-only hot reload)

If you're only editing frontend code and want instant hot reloading, run Vite's dev server alongside the Python backend:

**Terminal 1** — backend:
```bash
python -m cookdex.webui_server.main
```

**Terminal 2** — Vite dev server with API proxy:
```bash
cd web && npm run dev
```

Then open the Vite URL (usually `http://localhost:5173`). You'll need to add a proxy config to `web/vite.config.js` for API calls to reach the backend:

```js
// web/vite.config.js
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  server: {
    proxy: {
      "/cookdex/api": "http://localhost:4820",
    },
  },
});
```

## Running tests

```bash
python -m pytest
```

Tests use their own in-memory fixtures and don't need `.env` or a running server.

## Automated QA loop

The QA script builds the frontend, starts the server, and runs Playwright smoke tests:

```bash
python scripts/qa/run_local_webui_qa.py --iterations 1
```

This requires Playwright browsers to be installed (`cd web && npx playwright install`).

## Troubleshooting

| Problem | Fix |
|---|---|
| `MO_WEBUI_MASTER_KEY is required` | Set it in `.env` |
| 401 on login (cookie not sticking) | Set `WEB_COOKIE_SECURE=false` in `.env` |
| UI shows "build missing" | Run `cd web && npm run build` |
| Port already in use | Set `WEB_BIND_PORT=4821` in `.env` |
| `configs/config.json` not found | Create it: `mkdir -p configs && echo '{"providers":{},"parser":{}}' > configs/config.json` |
