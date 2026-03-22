#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# CookDex Direct DB Tunnel Setup Wizard
#
# Run this on the machine where CookDex's Docker container lives.
# It generates an SSH key, copies it to your Mealie host, enables
# the volume mount in compose.yaml, configures the SSH settings
# in CookDex, and restarts the container.
#
# Usage:  docker cp cookdex:/app/scripts/setup-db-tunnel.sh /tmp/setup-db-tunnel.sh && bash /tmp/setup-db-tunnel.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
RESET='\033[0m'

info()  { echo -e "${CYAN}[info]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${RESET}  $*"; }
err()   { echo -e "${RED}[error]${RESET} $*"; }
step()  { echo -e "\n${BOLD}── Step $1 ──${RESET}"; }

KEY_NAME="cookdex_mealie"
KEY_PATH="$HOME/.ssh/$KEY_NAME"
CONTAINER_KEY_PATH="/app/.ssh/$KEY_NAME"
COMPOSE_FILES=("compose.yaml" "compose.yml" "compose.ghcr.yml" "docker-compose.yaml" "docker-compose.yml")

# ── Find CookDex directory ──────────────────────────────────────
find_cookdex_dir() {
  for dir in "$(pwd)" "$HOME/cookdex" "/opt/cookdex" "/root/cookdex"; do
    for f in "${COMPOSE_FILES[@]}"; do
      if [ -f "$dir/$f" ]; then
        echo "$dir"
        return
      fi
    done
  done
  echo ""
}

find_compose_file() {
  local dir="$1"
  for f in "${COMPOSE_FILES[@]}"; do
    if [ -f "$dir/$f" ]; then
      echo "$dir/$f"
      return
    fi
  done
  echo ""
}

find_state_db() {
  local dir="$1"
  for path in "$dir/cache/webui/state.db" "$dir/cache/state.db"; do
    if [ -f "$path" ]; then
      echo "$path"
      return
    fi
  done
  echo ""
}

# ── Welcome ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       CookDex Direct DB Tunnel Setup Wizard         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "This wizard sets up an SSH tunnel so CookDex can connect"
echo -e "to your Mealie database directly for fast bulk operations."
echo ""
echo -e "${DIM}Run this on the machine where CookDex Docker runs.${RESET}"
echo ""

# ── Locate CookDex ──────────────────────────────────────────────
COOKDEX_DIR="$(find_cookdex_dir)"
if [ -z "$COOKDEX_DIR" ]; then
  echo -e -n "Where is your CookDex directory? ${DIM}(e.g. /root/cookdex)${RESET}: "
  read -r COOKDEX_DIR
  COOKDEX_DIR="${COOKDEX_DIR/#\~/$HOME}"
fi

COMPOSE_FILE="$(find_compose_file "$COOKDEX_DIR")"
if [ -z "$COMPOSE_FILE" ]; then
  err "No compose file found in $COOKDEX_DIR"
  exit 1
fi

ok "Found CookDex at ${BOLD}$COOKDEX_DIR${RESET}"

# ── Step 1: Collect Mealie host info ────────────────────────────
step "1/5: Mealie Host Info"
echo ""
echo -e "Enter the ${BOLD}IP address${RESET} or hostname of the machine running Mealie."
echo -e "${DIM}This is the server CookDex will SSH into to read the database.${RESET}"
echo ""
echo -e -n "${BOLD}Mealie host IP:${RESET} "
read -r MEALIE_HOST

if [ -z "$MEALIE_HOST" ]; then
  err "Mealie host is required."
  exit 1
fi

echo ""
echo -e "Enter the ${BOLD}SSH username${RESET} on that machine."
echo -e "${DIM}This user needs to be able to run 'docker' commands on the Mealie host.${RESET}"
echo ""
echo -e -n "${BOLD}SSH user${RESET} ${DIM}(default: root)${RESET}: "
read -r SSH_USER
SSH_USER="${SSH_USER:-root}"

ok "Will connect as ${BOLD}$SSH_USER@$MEALIE_HOST${RESET}"

# ── Step 2: SSH Key ─────────────────────────────────────────────
step "2/5: SSH Key"

if [ -f "$KEY_PATH" ]; then
  ok "SSH key already exists at $KEY_PATH"
else
  info "Generating SSH key..."
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -q
  ok "Created $KEY_PATH"
fi

echo ""
info "Copying public key to $SSH_USER@$MEALIE_HOST..."
echo -e "${DIM}You'll be asked for $SSH_USER's password — this is the only time.${RESET}"
echo ""

if ssh-copy-id -i "${KEY_PATH}.pub" "$SSH_USER@$MEALIE_HOST" 2>/dev/null; then
  ok "Public key installed"
else
  warn "ssh-copy-id failed. Trying manual method..."
  cat "${KEY_PATH}.pub" | ssh "$SSH_USER@$MEALIE_HOST" \
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
  ok "Public key installed (manual method)"
fi

echo ""
info "Verifying passwordless SSH..."
if ssh -i "$KEY_PATH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
    "$SSH_USER@$MEALIE_HOST" "echo OK" >/dev/null 2>&1; then
  ok "SSH connection verified"
else
  err "SSH verification failed. Check that the key was copied correctly."
  exit 1
fi

# ── Step 3: Volume mount ────────────────────────────────────────
step "3/5: Docker Volume Mount"

if grep -q "$KEY_NAME" "$COMPOSE_FILE" 2>/dev/null; then
  if grep -qE '^\s*#.*'"$KEY_NAME" "$COMPOSE_FILE" 2>/dev/null; then
    info "Uncommenting SSH key volume in $COMPOSE_FILE..."
    sed -i 's|^\(\s*\)#\s*\(- .*'"$KEY_NAME"'.*\)|\1\2|' "$COMPOSE_FILE"
    ok "Volume mount enabled"
  else
    ok "SSH key volume already enabled"
  fi
else
  info "Adding SSH key volume to $COMPOSE_FILE..."
  # Find the last volume line and append after it
  LAST_VOL_LINE=$(grep -n '^\s*-.*:/app/' "$COMPOSE_FILE" | tail -1 | cut -d: -f1)
  if [ -n "$LAST_VOL_LINE" ]; then
    INDENT=$(sed -n "${LAST_VOL_LINE}p" "$COMPOSE_FILE" | sed 's/\(^\s*\).*/\1/')
    sed -i "${LAST_VOL_LINE}a\\${INDENT}- ${KEY_PATH}:${CONTAINER_KEY_PATH}:ro" "$COMPOSE_FILE"
    ok "Volume mount added"
  else
    warn "Could not find volumes section. Add this line manually under volumes:"
    echo "      - ${KEY_PATH}:${CONTAINER_KEY_PATH}:ro"
  fi
fi

# ── Step 4: Save settings to CookDex ───────────────────────────
step "4/5: Configure CookDex Settings"

STATE_DB="$(find_state_db "$COOKDEX_DIR")"
SETTINGS_SAVED=false

if [ -n "$STATE_DB" ]; then
  # Try sqlite3 CLI first, then fall back to docker exec with Python
  if command -v sqlite3 >/dev/null 2>&1; then
    NOW="$(date -u +%Y-%m-%dT%H:%M:%S)Z"
    sqlite3 "$STATE_DB" <<SQL
INSERT INTO app_settings(key, value_json, updated_at) VALUES('MEALIE_DB_SSH_HOST', '"$MEALIE_HOST"', '$NOW')
  ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at;
INSERT INTO app_settings(key, value_json, updated_at) VALUES('MEALIE_DB_SSH_USER', '"$SSH_USER"', '$NOW')
  ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at;
INSERT INTO app_settings(key, value_json, updated_at) VALUES('MEALIE_DB_SSH_KEY', '"$CONTAINER_KEY_PATH"', '$NOW')
  ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at;
SQL
    SETTINGS_SAVED=true
    ok "SSH settings saved to CookDex"
  fi
fi

if [ "$SETTINGS_SAVED" = false ]; then
  # Fall back to docker exec — works even without sqlite3 on the host
  if docker exec cookdex python3 -c "
from pathlib import Path
from cookdex.webui_server.state import StateStore
s = StateStore(db_path=Path('/app/cache/webui/state.db'))
s.set_settings({
    'MEALIE_DB_SSH_HOST': '$MEALIE_HOST',
    'MEALIE_DB_SSH_USER': '$SSH_USER',
    'MEALIE_DB_SSH_KEY': '$CONTAINER_KEY_PATH',
})
print('OK')
" 2>/dev/null | grep -q OK; then
    SETTINGS_SAVED=true
    ok "SSH settings saved to CookDex"
  fi
fi

if [ "$SETTINGS_SAVED" = false ]; then
  warn "Could not auto-configure settings. Set these in Settings > Direct DB:"
  echo "      SSH Tunnel Host: $MEALIE_HOST"
  echo "      SSH Tunnel User: $SSH_USER"
  echo "      SSH Key Path:    $CONTAINER_KEY_PATH"
fi

# ── Step 5: Restart container ───────────────────────────────────
step "5/5: Restart Container"

echo ""
echo -e "Ready to restart CookDex with the SSH key mounted."
echo -e -n "${BOLD}Restart now?${RESET} ${DIM}[Y/n]${RESET}: "
read -r RESTART_CONFIRM
RESTART_CONFIRM="${RESTART_CONFIRM:-y}"

if [[ "$RESTART_CONFIRM" =~ ^[Yy] ]]; then
  info "Restarting CookDex..."
  cd "$COOKDEX_DIR"
  if docker compose up -d cookdex 2>/dev/null; then
    ok "Container restarted"
  elif docker-compose up -d cookdex 2>/dev/null; then
    ok "Container restarted"
  else
    err "Failed to restart. Run 'docker compose up -d cookdex' manually."
  fi
else
  warn "Skipped restart. Run 'docker compose up -d cookdex' when ready."
fi

# ── Done ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║                    Setup Complete!                   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Last step:${RESET}"
echo ""
echo -e "  1. Open CookDex in your browser"
echo -e "  2. Go to ${BOLD}Settings${RESET} → click ${BOLD}Auto-detect DB${RESET}"
echo -e "  3. Click ${BOLD}Apply Changes${RESET}, then ${BOLD}Test DB${RESET} to confirm"
echo ""
echo -e "  ${DIM}CookDex will SSH into $MEALIE_HOST, find your Mealie"
echo -e "  database, and fill in all credentials automatically.${RESET}"
echo ""
