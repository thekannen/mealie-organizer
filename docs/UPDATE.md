# Update Mealie Organizer

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

This document covers update flows by deployment path.

## 1) GHCR Public Image (Recommended)

Commands below assume the no-clone setup from `INSTALL.md` with `compose.yaml`.

### Stay on latest

```bash
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d --no-build --remove-orphans mealie-organizer
```

### Pin to a specific release tag

Set in `.env`:

```env
MEALIE_ORGANIZER_TAG=v2026.02.6
```

Then deploy:

```bash
docker compose -f compose.yaml pull mealie-organizer
docker compose -f compose.yaml up -d --no-build --remove-orphans mealie-organizer
```

### If you cloned the full repo, helper script option

```bash
./scripts/docker/update.sh --source ghcr
```

Common flags:
- `--skip-git-pull` to skip repo pull step
- `--prune` to clean dangling images

### Roll back quickly

1. Set previous tag in `.env` (`MEALIE_ORGANIZER_TAG=...`)
2. Run pull + up again

---

## 2) Your Own Custom Image

1. Rebuild from source:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build mealie-organizer
```

2. Tag and push:

```bash
docker tag mealie-organizer:local ghcr.io/<your-user>/mealie-organizer:<new-tag>
docker push ghcr.io/<your-user>/mealie-organizer:<new-tag>
```

3. Update `.env`:

```env
MEALIE_ORGANIZER_IMAGE=ghcr.io/<your-user>/mealie-organizer
MEALIE_ORGANIZER_TAG=<new-tag>
```

4. Redeploy:

```bash
docker compose pull mealie-organizer
docker compose up -d --no-build --remove-orphans mealie-organizer
```

---

## 3) Full Local Ubuntu Manual (No Docker)

1. Pull source:

```bash
git pull --ff-only origin main
```

2. Update Python environment:

```bash
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

3. Run whichever tool you use:

```bash
mealie-categorizer
```

Optional helper:

```bash
./scripts/install/ubuntu_setup_mealie.sh --update
```

---

## `update.sh` Status

`scripts/docker/update.sh` is kept and current.

- Preferred when running from a cloned repo: `--source ghcr`
- Available but deprecated for routine deployment: `--source local`

If you run outside a git checkout, use:

```bash
./scripts/docker/update.sh --source ghcr --skip-git-pull
```
