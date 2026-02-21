#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--tag] [--set x.y.z] [--dry-run]

Bumps the CalVer version (year.month.build) and optionally creates a git tag.

Options:
  --tag       Create a git tag for the new version
  --set X.Y.Z Force a specific version instead of auto-incrementing
  --dry-run   Preview the version bump without writing

Examples:
  scripts/release.sh                # auto-bump build number
  scripts/release.sh --tag          # bump + tag
  scripts/release.sh --set 2026.3.1 # force version
USAGE
}

BUMP_ARGS=()
CREATE_TAG=false

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)
      CREATE_TAG=true
      shift
      ;;
    --set)
      BUMP_ARGS+=(--set "$2")
      shift 2
      ;;
    --dry-run)
      BUMP_ARGS+=(--dry-run)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

OUTPUT=$(python3 "$SCRIPT_DIR/bump_version.py" "${BUMP_ARGS[@]}")
echo "$OUTPUT"

# Extract the new version from bump_version.py output
if echo "$OUTPUT" | grep -q "dry run"; then
  exit 0
fi

NEW_VERSION=$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")

echo "[next] Commit and push:"
echo "       git add VERSION web/package.json"
echo "       git commit -m 'chore(release): v$NEW_VERSION'"

if [ "$CREATE_TAG" = true ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[error] git is required for tagging"
    exit 1
  fi
  if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
    echo "[error] Tag v$NEW_VERSION already exists"
    exit 1
  fi
  git tag "v$NEW_VERSION"
  echo "[ok] Created tag: v$NEW_VERSION"
  echo "[next] Push with tag:"
  echo "       git push && git push origin v$NEW_VERSION"
fi
