# Docker Deployment with GHCR

> For self-host install/update flows, use `INSTALL.md` and `UPDATE.md`.
> This document is focused on GHCR registry behavior and publishing details.

This project now defaults to pulling prebuilt images from GitHub Container Registry (GHCR):

- `ghcr.io/thekannen/mealie-organizer:<tag>`

The container runtime behavior is still controlled by your local `.env` file and mounted folders.

## 1) GitHub CLI Setup (publisher side)

Install and authenticate `gh` on the machine where you manage GitHub settings:

```bash
gh --version
gh auth login
gh auth status
```

Validate the target repository and Actions permissions:

```bash
gh repo view thekannen/mealie-organizer --json name,owner,defaultBranchRef,isPrivate,url
gh api repos/thekannen/mealie-organizer/actions/permissions
gh api repos/thekannen/mealie-organizer/actions/permissions/workflow
```

Notes:

- The publish workflow uses `GITHUB_TOKEN` with `packages: write`.
- The package is intended to be public for pull-without-login deployments.

## 2) Publish Images to GHCR

Publishing is automatic via `.github/workflows/publish-ghcr.yml` on:

- push to `main`
- push tags like `v1.2.3`
- manual `workflow_dispatch`

Generated tags include:

- `latest` (default branch)
- `v*` (tag pushes)
- `sha-<shortsha>` (all publishes)

## 3) Deploy from GHCR (default)

`docker-compose.yml` is GHCR-first. Configure optional image/tag in `.env`:

```env
MEALIE_ORGANIZER_IMAGE=ghcr.io/thekannen/mealie-organizer
MEALIE_ORGANIZER_TAG=latest
```

Deploy:

```bash
docker compose pull mealie-organizer
docker compose up -d --no-build --remove-orphans mealie-organizer
```

## 4) Pin and Roll Back

Pin to a release tag:

```env
MEALIE_ORGANIZER_TAG=v1.2.3
```

Then redeploy:

```bash
docker compose pull mealie-organizer
docker compose up -d --no-build --remove-orphans mealie-organizer
```

## 5) Local Build Override

For local source builds, add `docker-compose.build.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build mealie-organizer
```

Optional local image name:

```env
MEALIE_ORGANIZER_LOCAL_IMAGE=mealie-organizer:local
```

## 6) Using the Update Script

Use the helper script in GHCR mode (default):

```bash
./scripts/docker/update.sh --source ghcr
```

Use local source mode (deprecated; kept for compatibility):

```bash
./scripts/docker/update.sh --source local
```

## 7) User-Controlled Settings Remain Local

All user/runtime settings remain editable on the deployment host:

- `.env` for secrets and runtime flags
- `./configs` mounted to `/app/configs`
- `./cache`, `./logs`, `./reports` mounted for state/output

Changing images does not remove this local control model.
