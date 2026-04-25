# Getting Started

## 1) Start the service

```bash
docker compose pull cookdex
docker compose up -d cookdex
```

No `.env` file is required.

## 2) Open the Web UI

`https://localhost:4820/cookdex` (accept the self-signed certificate warning)

## 3) Create your admin account

On first visit, the setup screen prompts you to create an admin user. Choose a username and a strong password (at least 8 characters, mixed case, with a digit).

## 4) Configure Mealie connection

After login, go to **Settings** and enter:

- **Mealie Server URL** — e.g. `http://mealie:9000/api`
- **Mealie API Key** — your Mealie API token

In Mealie, API tokens are created from your user profile under **API Tokens**. Copy the token when Mealie shows it; it is only shown once.

If CookDex and Mealie run in the same Docker network, use the Mealie service name instead of `localhost`. `localhost` inside the CookDex container means the CookDex container itself.

Click **Test Mealie** to verify. The dashboard shows a banner until both values are set.

## 5) Verify health

```bash
curl -k https://localhost:4820/cookdex/api/v1/health
```

## 6) Run a dry task

- Open **Tasks**
- Pick `ingredient-parse`
- Keep `dry_run=true`
- Queue run and inspect logs
