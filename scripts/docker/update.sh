#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-cookdex}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-false}"
NO_BUILD="${NO_BUILD:-false}"
PRUNE="${PRUNE:-false}"
SOURCE="${SOURCE:-ghcr}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  --repo-root <path>   Repo root path (default: script-derived repo root)
  --branch <name>      Git branch to update from (default: main)
  --service <name>     Docker Compose service name (default: cookdex)
  --source <ghcr|local> Deploy source (default: ghcr).
                       ghcr: pull image and restart without local build
                       local: use docker-compose.build.yml and build from source (deprecated)
  --skip-git-pull      Skip git fetch/pull step
  --no-build           Restart without rebuilding image (local source only)
  --prune              Run 'docker image prune -f' after update
  -h, --help           Show this help text
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --service)
      SERVICE="$2"
      shift 2
      ;;
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --skip-git-pull)
      SKIP_GIT_PULL=true
      shift
      ;;
    --no-build)
      NO_BUILD=true
      shift
      ;;
    --prune)
      PRUNE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [ "$SOURCE" != "ghcr" ] && [ "$SOURCE" != "local" ]; then
  echo "[error] --source must be 'ghcr' or 'local'."
  exit 1
fi

if [ ! -f "$REPO_ROOT/docker-compose.yml" ]; then
  echo "[error] docker-compose.yml not found in: $REPO_ROOT"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[error] Docker Compose is required (docker compose or docker-compose)."
  exit 1
fi

if [ "$SKIP_GIT_PULL" != true ]; then
  if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "[error] --skip-git-pull is false, but repo is not a git checkout: $REPO_ROOT"
    exit 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    echo "[error] git is required when git pull is enabled."
    exit 1
  fi
fi

COMPOSE_FILES=(-f docker-compose.yml)
if [ "$SOURCE" = "local" ]; then
  echo "[warn] --source local is deprecated for deployment. Prefer --source ghcr."
  if [ ! -f "$REPO_ROOT/docker-compose.build.yml" ]; then
    echo "[error] docker-compose.build.yml not found in: $REPO_ROOT"
    exit 1
  fi
  COMPOSE_FILES+=(-f docker-compose.build.yml)
fi

compose_run() {
  "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" "$@"
}

cd "$REPO_ROOT"

echo "[start] Repo: $REPO_ROOT"
echo "[start] Service: $SERVICE"
echo "[start] Source: $SOURCE"

if [ "$SKIP_GIT_PULL" != true ]; then
  echo "[start] Current commit: $(git rev-parse --short HEAD)"
  echo "[start] Updating source from origin/$BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  echo "[ok] Updated commit: $(git rev-parse --short HEAD)"
else
  echo "[skip] Git pull skipped"
fi

if [ "$SOURCE" = "ghcr" ]; then
  if [ "$NO_BUILD" = true ]; then
    echo "[warn] --no-build is ignored for --source ghcr"
  fi
  echo "[start] Pulling image from registry"
  compose_run pull "$SERVICE"
  echo "[start] Restarting service from pulled image"
  compose_run up -d --no-build --remove-orphans "$SERVICE"
else
  if [ "$NO_BUILD" = true ]; then
    echo "[start] Restarting local-source service without rebuild"
    compose_run up -d --no-build --remove-orphans "$SERVICE"
  else
    echo "[start] Rebuilding and restarting local-source service"
    compose_run up -d --build --remove-orphans "$SERVICE"
  fi
fi

echo "[ok] Service status"
compose_run ps "$SERVICE"

if [ "$PRUNE" = true ]; then
  echo "[start] Pruning dangling images"
  docker image prune -f
fi

echo "[done] Update complete"
