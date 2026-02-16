#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/thekannen/mealie-organizer.git}"
REPO_REF="${REPO_REF:-main}"
WORKSPACE="${WORKSPACE:-$HOME/mealie-organizer}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
OUTPUT_DIR="${OUTPUT_DIR:-mealie-plugin}"
PUBLIC_PORT="${PUBLIC_PORT:-}"
MEALIE_UPSTREAM="${MEALIE_UPSTREAM:-}"
ORGANIZER_UPSTREAM="${ORGANIZER_UPSTREAM:-}"
PLUGIN_BASE_PATH="${PLUGIN_BASE_PATH:-/mo-plugin}"

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --repo-url <url>           Git repository URL (default: $REPO_URL)
  --repo-ref <ref>           Branch/tag/ref to checkout (default: $REPO_REF)
  --workspace <dir>          Local clone path (default: $WORKSPACE)
  --project-root <dir>       Mealie deployment root where bundle is generated (default: current directory)
  --output-dir <dir>         Output directory under project root (default: $OUTPUT_DIR)
  --public-port <port>       Preserve this public host port for Mealie URL
  --mealie-upstream <url>    Gateway upstream for Mealie UI/API
  --organizer-upstream <url> Gateway upstream for organizer plugin server
  --plugin-base-path <path>  Plugin URL base path (default: $PLUGIN_BASE_PATH)
  -h, --help                 Show help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --repo-ref)
      REPO_REF="$2"
      shift 2
      ;;
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --public-port)
      PUBLIC_PORT="$2"
      shift 2
      ;;
    --mealie-upstream)
      MEALIE_UPSTREAM="$2"
      shift 2
      ;;
    --organizer-upstream)
      ORGANIZER_UPSTREAM="$2"
      shift 2
      ;;
    --plugin-base-path)
      PLUGIN_BASE_PATH="$2"
      shift 2
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

if ! command -v git >/dev/null 2>&1; then
  echo "[error] git is required."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "[error] python3 is required."
  exit 1
fi

if [ -d "$WORKSPACE/.git" ]; then
  echo "[start] Updating existing repository: $WORKSPACE"
  git -C "$WORKSPACE" fetch origin "$REPO_REF"
  git -C "$WORKSPACE" checkout "$REPO_REF"
  git -C "$WORKSPACE" pull --ff-only origin "$REPO_REF"
else
  echo "[start] Cloning repository: $REPO_URL -> $WORKSPACE"
  git clone --branch "$REPO_REF" --depth 1 "$REPO_URL" "$WORKSPACE"
fi

GENERATOR="$WORKSPACE/scripts/install/generate_plugin_bundle.py"
if [ ! -f "$GENERATOR" ]; then
  echo "[error] Missing generator script: $GENERATOR"
  exit 1
fi

CMD=(
  python3 "$GENERATOR"
  --project-root "$PROJECT_ROOT"
  --output-dir "$OUTPUT_DIR"
  --plugin-base-path "$PLUGIN_BASE_PATH"
)
if [ -n "$PUBLIC_PORT" ]; then
  CMD+=(--public-port "$PUBLIC_PORT")
fi
if [ -n "$MEALIE_UPSTREAM" ]; then
  CMD+=(--mealie-upstream "$MEALIE_UPSTREAM")
fi
if [ -n "$ORGANIZER_UPSTREAM" ]; then
  CMD+=(--organizer-upstream "$ORGANIZER_UPSTREAM")
fi

echo "[start] Generating plugin gateway bundle in $PROJECT_ROOT/$OUTPUT_DIR"
"${CMD[@]}"

echo "[done] Bundle created."
echo "Review these files:"
echo "  - $PROJECT_ROOT/mealie-plugin.config.json"
echo "  - $PROJECT_ROOT/$OUTPUT_DIR/nginx.conf"
echo "  - $PROJECT_ROOT/$OUTPUT_DIR/compose.plugin-gateway.yml"
echo "  - $PROJECT_ROOT/$OUTPUT_DIR/README.generated.md"
