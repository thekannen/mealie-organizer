#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-mealie-organizer}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-false}"
NO_BUILD="${NO_BUILD:-false}"
PRUNE="${PRUNE:-false}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  --repo-root <path>   Repo root path (default: script-derived repo root)
  --branch <name>      Git branch to update from (default: main)
  --service <name>     Docker Compose service name (default: mealie-organizer)
  --skip-git-pull      Skip git fetch/pull step
  --no-build           Restart without rebuilding image
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

if [ ! -d "$REPO_ROOT/.git" ]; then
  echo "[error] Not a git repo: $REPO_ROOT"
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

if ! command -v git >/dev/null 2>&1; then
  echo "[error] git is required."
  exit 1
fi

cd "$REPO_ROOT"

echo "[start] Repo: $REPO_ROOT"
echo "[start] Service: $SERVICE"

echo "[start] Current commit: $(git rev-parse --short HEAD)"

if [ "$SKIP_GIT_PULL" != true ]; then
  echo "[start] Updating source from origin/$BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  echo "[ok] Updated commit: $(git rev-parse --short HEAD)"
else
  echo "[skip] Git pull skipped"
fi

if [ "$NO_BUILD" = true ]; then
  echo "[start] Restarting service without rebuild"
  "${COMPOSE_CMD[@]}" up -d --no-build --remove-orphans "$SERVICE"
else
  echo "[start] Rebuilding and restarting service"
  "${COMPOSE_CMD[@]}" up -d --build --remove-orphans "$SERVICE"
fi

echo "[ok] Service status"
"${COMPOSE_CMD[@]}" ps "$SERVICE"

if [ "$PRUNE" = true ]; then
  echo "[start] Pruning dangling images"
  docker image prune -f
fi

echo "[done] Update complete"
