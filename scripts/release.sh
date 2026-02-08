#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION_FILE="$REPO_ROOT/VERSION"

usage() {
  cat <<USAGE
Usage: $(basename "$0") <patch|minor|major|x.y.z> [--tag]

Examples:
  scripts/release.sh patch
  scripts/release.sh minor --tag
  scripts/release.sh 1.4.0 --tag
USAGE
}

if [ $# -lt 1 ]; then
  usage
  exit 1
fi

BUMP_TARGET="$1"
CREATE_TAG=false
if [ "${2:-}" = "--tag" ]; then
  CREATE_TAG=true
elif [ $# -gt 1 ]; then
  echo "[error] Unknown option: $2"
  usage
  exit 1
fi

if [ ! -f "$VERSION_FILE" ]; then
  echo "[error] VERSION file not found: $VERSION_FILE"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "[error] git is required"
  exit 1
fi

CURRENT="$(tr -d '[:space:]' < "$VERSION_FILE")"
if ! [[ "$CURRENT" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  echo "[error] VERSION must be SemVer (x.y.z). Found: $CURRENT"
  exit 1
fi

major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
patch="${BASH_REMATCH[3]}"

case "$BUMP_TARGET" in
  patch)
    patch=$((patch + 1))
    ;;
  minor)
    minor=$((minor + 1))
    patch=0
    ;;
  major)
    major=$((major + 1))
    minor=0
    patch=0
    ;;
  *)
    if [[ "$BUMP_TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      NEW_VERSION="$BUMP_TARGET"
    else
      echo "[error] Invalid target '$BUMP_TARGET'. Use patch|minor|major|x.y.z"
      exit 1
    fi
    ;;
esac

NEW_VERSION="${NEW_VERSION:-$major.$minor.$patch}"

echo "$NEW_VERSION" > "$VERSION_FILE"

echo "[ok] Version bumped: $CURRENT -> $NEW_VERSION"
echo "[next] Commit and push changes:"
echo "       git add VERSION pyproject.toml src/mealie_organizer/__init__.py"
echo "       git commit -m 'chore(release): v$NEW_VERSION'"

if [ "$CREATE_TAG" = true ]; then
  if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
    echo "[error] Tag v$NEW_VERSION already exists"
    exit 1
  fi
  git tag "v$NEW_VERSION"
  echo "[ok] Created tag: v$NEW_VERSION"
  echo "[next] Push with tag:"
  echo "       git push && git push origin v$NEW_VERSION"
fi
