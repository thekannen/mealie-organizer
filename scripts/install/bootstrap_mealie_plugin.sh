#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/thekannen/mealie-organizer.git}"
REPO_REF="${REPO_REF:-main}"
WORKSPACE="${WORKSPACE:-$HOME/mealie-organizer}"
PROJECT_ROOT="${PROJECT_ROOT:-auto}"
OUTPUT_DIR="${OUTPUT_DIR:-mealie-plugin}"
PUBLIC_PORT="${PUBLIC_PORT:-}"
MEALIE_UPSTREAM="${MEALIE_UPSTREAM:-}"
ORGANIZER_UPSTREAM="${ORGANIZER_UPSTREAM:-}"
PLUGIN_BASE_PATH="${PLUGIN_BASE_PATH:-/mo-plugin}"

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --repo-url <url>           Repository URL (git clone or GitHub archive) (default: $REPO_URL)
  --repo-ref <ref>           Branch/tag/ref to checkout (default: $REPO_REF)
  --workspace <dir>          Local clone path (default: $WORKSPACE)
  --project-root <dir|auto>  Mealie deployment root where bundle is generated.
                             Use auto-discovery when omitted (default: auto)
  --output-dir <dir>         Output directory under project root (default: $OUTPUT_DIR)
  --public-port <port>       Preserve this public host port for Mealie URL
  --mealie-upstream <url>    Gateway upstream for Mealie UI/API
  --organizer-upstream <url> Gateway upstream for organizer plugin server
  --plugin-base-path <path>  Plugin URL base path (default: $PLUGIN_BASE_PATH)
  -h, --help                 Show help
USAGE
}

discover_project_root() {
  local start_dir="$1"
  local dir="$start_dir"

  while [ "$dir" != "/" ]; do
    if [ -f "$dir/docker-compose.yml" ] || [ -f "$dir/docker-compose.yaml" ] || [ -f "$dir/compose.yaml" ] || [ -f "$dir/compose.yml" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done

  for candidate in "$HOME/mealie" "/opt/mealie" "/srv/mealie"; do
    if [ -f "$candidate/docker-compose.yml" ] || [ -f "$candidate/docker-compose.yaml" ] || [ -f "$candidate/compose.yaml" ] || [ -f "$candidate/compose.yml" ]; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "[error] python3 is required."
  exit 1
fi

if [ "${PROJECT_ROOT}" = "auto" ] || [ -z "${PROJECT_ROOT}" ]; then
  if detected_root="$(discover_project_root "$PWD")"; then
    PROJECT_ROOT="$detected_root"
    echo "[info] Auto-detected Mealie stack directory: $PROJECT_ROOT"
  else
    echo "[error] Could not auto-detect Mealie stack directory."
    echo "Run again with --project-root <path-containing-compose-file>."
    exit 1
  fi
fi

if [ ! -d "$PROJECT_ROOT" ]; then
  echo "[error] --project-root does not exist: $PROJECT_ROOT"
  exit 1
fi

if command -v git >/dev/null 2>&1; then
  if [ -d "$WORKSPACE/.git" ]; then
    echo "[start] Updating existing repository: $WORKSPACE"
    git -C "$WORKSPACE" fetch origin "$REPO_REF"
    git -C "$WORKSPACE" checkout "$REPO_REF"
    git -C "$WORKSPACE" pull --ff-only origin "$REPO_REF"
  else
    echo "[start] Cloning repository: $REPO_URL -> $WORKSPACE"
    git clone --branch "$REPO_REF" --depth 1 "$REPO_URL" "$WORKSPACE"
  fi
else
  if ! command -v curl >/dev/null 2>&1; then
    echo "[error] Either git or curl is required to fetch mealie-organizer sources."
    exit 1
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "[error] tar is required for curl-based source download."
    exit 1
  fi

  repo_http="${REPO_URL%.git}"
  case "$repo_http" in
    https://github.com/*)
      archive_url="${repo_http}/archive/refs/heads/${REPO_REF}.tar.gz"
      ;;
    *)
      echo "[error] REPO_URL must be a GitHub URL when git is unavailable."
      echo "Install git or set REPO_URL to a GitHub repository."
      exit 1
      ;;
  esac

  tmp_archive="$(mktemp)"
  tmp_extract="$(mktemp -d)"
  trap 'rm -f "$tmp_archive"; rm -rf "$tmp_extract"' EXIT

  echo "[start] Downloading source archive: $archive_url"
  curl -fsSL "$archive_url" -o "$tmp_archive"
  tar -xzf "$tmp_archive" -C "$tmp_extract"
  extracted_root="$(find "$tmp_extract" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$extracted_root" ]; then
    echo "[error] Unable to extract repository archive."
    exit 1
  fi
  rm -rf "$WORKSPACE"
  mkdir -p "$(dirname "$WORKSPACE")"
  mv "$extracted_root" "$WORKSPACE"
  echo "[ok] Downloaded source to: $WORKSPACE"
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
