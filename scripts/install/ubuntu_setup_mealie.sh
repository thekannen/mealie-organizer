#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_OLLAMA=false
SKIP_APT_UPDATE=false

for arg in "$@"; do
  case "$arg" in
    --install-ollama)
      INSTALL_OLLAMA=true
      ;;
    --skip-apt-update)
      SKIP_APT_UPDATE=true
      ;;
    *)
      echo "[error] Unknown argument: $arg"
      echo "Usage: $0 [--install-ollama] [--skip-apt-update]"
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "[error] python3 is required. Install Python 3.10+ and rerun."
  exit 1
fi

if [ "$SKIP_APT_UPDATE" = false ]; then
  echo "[start] Updating apt package index"
  sudo apt-get update -y
fi

echo "[start] Installing core packages"
sudo apt-get install -y python3 python3-venv python3-pip curl

if [ "$INSTALL_OLLAMA" = true ]; then
  if command -v ollama >/dev/null 2>&1; then
    echo "[ok] Ollama already installed"
  else
    echo "[start] Installing Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
fi

echo "[start] Configuring Python virtual environment"
cd "$REPO_ROOT"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[ok] Created .env from .env.example"
else
  echo "[ok] Existing .env detected; leaving unchanged"
fi

echo "[done] Ubuntu setup complete"
echo "Next: edit .env, then run a categorizer script from repo root."
