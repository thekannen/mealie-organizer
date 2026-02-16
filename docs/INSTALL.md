# Install

## Option 1: GHCR image (recommended)

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

## Option 2: Repo clone

```bash
git clone https://github.com/thekannen/mealie-organizer.git
cd mealie-organizer
cp .env.example .env
# edit .env values

docker compose up -d mealie-organizer
```

## Option 3: Bootstrap installer script

```bash
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/scripts/install/bootstrap_webui.sh -o /tmp/bootstrap_webui.sh
bash /tmp/bootstrap_webui.sh --output-dir ./mealie-organizer-webui --web-port 4820
cd mealie-organizer-webui
# edit .env
docker compose up -d
```

## Required volumes

- `./configs` -> `/app/configs`
- `./cache` -> `/app/cache`
- `./logs` -> `/app/logs`
- `./reports` -> `/app/reports`

## Required env at startup

- `MO_WEBUI_MASTER_KEY` or `MO_WEBUI_MASTER_KEY_FILE`
- If no user exists yet: `WEB_BOOTSTRAP_PASSWORD`