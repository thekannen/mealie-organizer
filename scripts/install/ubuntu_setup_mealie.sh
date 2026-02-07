#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REPO_URL="https://github.com/thekannen/mealie-scripts.git"
REPO_BRANCH="main"
TARGET_DIR="$HOME/mealie-scripts"
USE_CURRENT_REPO=false
UPDATE_ONLY=false
PROVIDER="ollama"
INSTALL_OLLAMA=false
SKIP_APT_UPDATE=false
SETUP_CRON=false
CRON_SCHEDULE="15 2 * * *"

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --repo-url <url>             Repository URL to clone/update.
  --repo-branch <branch>       Repository branch to use (default: main).
  --target-dir <dir>           Target directory for cloned repo.
  --use-current-repo           Skip clone/update and use script's current repo.
  --update                     Only update the repo from GitHub, then exit.
  --provider <ollama|chatgpt>  Provider preference for categorizer runs.
  --install-ollama             Install Ollama if missing.
  --skip-apt-update            Skip apt-get update.
  --setup-cron                 Install/update cron jobs.
  --cron-schedule <schedule>   Cron schedule for selected provider.
                               Default: "15 2 * * *" (empty disables cron job)
  -h, --help                   Show this help text.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --repo-branch)
      REPO_BRANCH="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --use-current-repo)
      USE_CURRENT_REPO=true
      shift
      ;;
    --update)
      UPDATE_ONLY=true
      shift
      ;;
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --install-ollama)
      INSTALL_OLLAMA=true
      shift
      ;;
    --skip-apt-update)
      SKIP_APT_UPDATE=true
      shift
      ;;
    --setup-cron)
      SETUP_CRON=true
      shift
      ;;
    --cron-schedule)
      CRON_SCHEDULE="$2"
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

if [ "$PROVIDER" != "ollama" ] && [ "$PROVIDER" != "chatgpt" ]; then
  echo "[error] --provider must be either 'ollama' or 'chatgpt'."
  exit 1
fi

if [ "$USE_CURRENT_REPO" = true ]; then
  REPO_ROOT="$DEFAULT_REPO_ROOT"
else
  REPO_ROOT="$TARGET_DIR"
fi

install_packages() {
  if [ "$SKIP_APT_UPDATE" = false ]; then
    echo "[start] Updating apt package index"
    sudo apt-get update -y
  fi

  echo "[start] Installing core packages"
  sudo apt-get install -y python3 python3-venv python3-pip curl git cron

  echo "[start] Enabling cron service"
  sudo systemctl enable --now cron >/dev/null 2>&1 || true
}

sync_repo() {
  if [ "$USE_CURRENT_REPO" = true ]; then
    echo "[ok] Using current repository: $REPO_ROOT"
    return
  fi

  if [ -d "$REPO_ROOT/.git" ]; then
    echo "[start] Updating existing repo in $REPO_ROOT"
    git -C "$REPO_ROOT" fetch origin "$REPO_BRANCH"
    git -C "$REPO_ROOT" checkout "$REPO_BRANCH"
    git -C "$REPO_ROOT" pull --ff-only origin "$REPO_BRANCH"
  else
    echo "[start] Cloning repo to $REPO_ROOT"
    git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$REPO_ROOT"
  fi
}

update_only_repo() {
  if ! command -v git >/dev/null 2>&1; then
    echo "[error] git is required for --update mode."
    exit 1
  fi
  sync_repo
  echo "[done] Repo update complete"
  echo "Repo path: $REPO_ROOT"
}

setup_python() {
  echo "[start] Configuring Python virtual environment"
  cd "$REPO_ROOT"

  if [ ! -f "requirements.txt" ]; then
    echo "[error] requirements.txt not found in $REPO_ROOT"
    exit 1
  fi

  if [ ! -d .venv ]; then
    python3 -m venv .venv
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  pip install -e .

  if [ ! -f .env ]; then
    cp .env.example .env
    echo "[ok] Created .env from .env.example"
  else
    echo "[ok] Existing .env detected; leaving unchanged"
  fi
}

setup_ollama() {
  if [ "$INSTALL_OLLAMA" = false ]; then
    return
  fi

  if command -v ollama >/dev/null 2>&1; then
    echo "[ok] Ollama already installed"
  else
    echo "[start] Installing Ollama"
    curl -fsSL https://ollama.com/install.sh | sh
  fi
}

add_or_replace_cron_line() {
  local label="$1"
  local line="$2"
  local cron_tmp

  cron_tmp="$(mktemp)"
  crontab -l 2>/dev/null | sed "/# ${label}\\$/d" > "$cron_tmp" || true
  printf '%s\n' "$line" >> "$cron_tmp"
  crontab "$cron_tmp"
  rm -f "$cron_tmp"
}

remove_cron_line() {
  local label="$1"
  local cron_tmp

  cron_tmp="$(mktemp)"
  crontab -l 2>/dev/null | sed "/# ${label}\\$/d" > "$cron_tmp" || true
  crontab "$cron_tmp"
  rm -f "$cron_tmp"
}

setup_cron_jobs() {
  if [ "$SETUP_CRON" = false ]; then
    return
  fi

  echo "[start] Configuring cron jobs"
  mkdir -p "$REPO_ROOT/logs"

  if [ "$PROVIDER" = "ollama" ] && [ -n "$CRON_SCHEDULE" ]; then
    add_or_replace_cron_line \
      "MEALIE_OLLAMA_CATEGORIZER" \
      "$CRON_SCHEDULE /bin/bash -lc 'cd \"$REPO_ROOT\" && . .venv/bin/activate && python -m mealie_scripts.recipe_categorizer_ollama >> logs/cron_ollama.log 2>&1' # MEALIE_OLLAMA_CATEGORIZER"
    remove_cron_line "MEALIE_CHATGPT_CATEGORIZER"
    echo "[ok] Cron job set for Ollama categorizer: $CRON_SCHEDULE"
  elif [ "$PROVIDER" = "chatgpt" ] && [ -n "$CRON_SCHEDULE" ]; then
    add_or_replace_cron_line \
      "MEALIE_CHATGPT_CATEGORIZER" \
      "$CRON_SCHEDULE /bin/bash -lc 'cd \"$REPO_ROOT\" && . .venv/bin/activate && python -m mealie_scripts.recipe_categorizer_chatgpt >> logs/cron_chatgpt.log 2>&1' # MEALIE_CHATGPT_CATEGORIZER"
    remove_cron_line "MEALIE_OLLAMA_CATEGORIZER"
    echo "[ok] Cron job set for ChatGPT categorizer: $CRON_SCHEDULE"
  else
    echo "[ok] Cron schedule empty; no categorizer job installed."
  fi

  echo "[ok] Current crontab entries:"
  crontab -l | rg 'MEALIE_.*_CATEGORIZER' || true
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "[error] python3 is required. Install Python 3.10+ and rerun."
  exit 1
fi

if [ "$UPDATE_ONLY" = true ]; then
  update_only_repo
  exit 0
fi

install_packages
sync_repo
setup_python
setup_ollama
setup_cron_jobs

echo "[done] Ubuntu setup complete"
echo "Repo path: $REPO_ROOT"
echo "Next: edit $REPO_ROOT/.env and run categorizer scripts."
