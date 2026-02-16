# Install Mealie Organizer

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

This document covers installation paths from easiest to most manual.

## Prerequisites

- Docker + Docker Compose for paths 1 and 2
- Mealie API URL and API key
- A `.env` file

---

## 1) GHCR Public Image (Recommended)

Best for most self-hosters. No registry login and no full repo clone required.

1. Create a deployment folder and download runtime files:

```bash
mkdir -p mealie-organizer && cd mealie-organizer
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/.env.example -o .env
curl -fsSL https://raw.githubusercontent.com/thekannen/mealie-organizer/main/compose.ghcr.yml -o compose.yaml
```

2. Edit `.env` with your own settings:
- Required:
  - `MEALIE_URL`
  - `MEALIE_API_KEY`
- Optional image pinning:
  - `MEALIE_ORGANIZER_IMAGE=ghcr.io/thekannen/mealie-organizer`
  - `MEALIE_ORGANIZER_TAG=latest`

3. Deploy:

```bash
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d --no-build --remove-orphans mealie-organizer
```

4. Verify:

```bash
docker compose -f compose.yaml logs -f mealie-organizer
```

Notes:
- `compose.ghcr.yml` uses image-bundled config defaults by default.
- If you want host-managed taxonomy/templates, add `./configs:/app/configs` volume in your compose file.

---

## 2) Build And Push Your Own Image

Use this if you want custom code/images in your own registry.

1. Build from local source:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build mealie-organizer
```

2. Tag and push to your registry (example uses GHCR personal namespace):

```bash
docker tag mealie-organizer:local ghcr.io/<your-user>/mealie-organizer:custom
docker push ghcr.io/<your-user>/mealie-organizer:custom
```

3. Point deployment to your image in `.env`:

```env
MEALIE_ORGANIZER_IMAGE=ghcr.io/<your-user>/mealie-organizer
MEALIE_ORGANIZER_TAG=custom
```

4. Deploy from your pushed image:

```bash
docker compose pull mealie-organizer
docker compose up -d --no-build --remove-orphans mealie-organizer
```

Notes:
- If your registry/image is private, run `docker login` first.
- Local build deploy mode exists mainly for custom image publishing workflows.

---

## 3) Full Local Ubuntu Manual (No Docker)

Use this for complete host-level control with Python/venv.

1. Install base packages:

```bash
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git curl
```

2. Clone and install:

```bash
git clone https://github.com/thekannen/mealie-organizer.git
cd mealie-organizer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

3. Edit `.env` and run:

```bash
source .venv/bin/activate
mealie-categorizer
```

Optional helper for Ubuntu bootstrap:

```bash
./scripts/install/ubuntu_setup_mealie.sh
```

---

## What Stays User-Controlled In All Paths

- `.env` (secrets + runtime behavior)
- Optional `configs/` taxonomy and config templates (mounted when desired)
- `cache/`, `logs/`, `reports/` output/state folders
