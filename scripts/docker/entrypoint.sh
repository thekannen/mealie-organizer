#!/usr/bin/env bash
set -euo pipefail

# ── Fix volume permissions + seed configs on first launch ───────
# Docker-created/bind-mounted paths may be owned by root. Ensure
# app can write to runtime directories and that required taxonomy
# JSON files exist before dropping privileges.
if [ "$(id -u)" = "0" ]; then
  for dir in /app/configs /app/configs/taxonomy /app/cache /app/logs /app/reports; do
    mkdir -p "$dir"
  done

  # If a host bind-mount has empty/missing config files, seed from
  # image-baked defaults so maintenance stages can run immediately.
  if [ -d /app/configs.defaults ]; then
    if [ ! -s /app/configs/config.json ] && [ -f /app/configs.defaults/config.json ]; then
      cp /app/configs.defaults/config.json /app/configs/config.json || true
    fi
    for file in categories.json tags.json cookbooks.json labels.json tools.json units_aliases.json tag_rules.json; do
      if [ ! -s "/app/configs/taxonomy/$file" ] && [ -f "/app/configs.defaults/taxonomy/$file" ]; then
        cp "/app/configs.defaults/taxonomy/$file" "/app/configs/taxonomy/$file" || true
      fi
    done
  fi

  for dir in /app/configs /app/cache /app/logs /app/reports; do
    chown -R app:app "$dir" 2>/dev/null || true
  done

  # Verify the app user can write to critical directories.
  for dir in /app/configs /app/configs/taxonomy /app/cache /app/logs /app/reports; do
    if ! su -s /bin/sh app -c "touch '$dir/.write_test' 2>/dev/null && rm -f '$dir/.write_test'" 2>/dev/null; then
      echo "[warn] app user cannot write to $dir — tasks may fail. Check host directory ownership."
    fi
  done

  # If SSH keys are mounted (possibly read-only), copy to a writable location.
  if [ -d /app/.ssh ]; then
    SSH_DIR="/tmp/.ssh-app"
    mkdir -p "$SSH_DIR"
    cp -a /app/.ssh/* "$SSH_DIR/" 2>/dev/null || true
    chown -R app:app "$SSH_DIR" 2>/dev/null || true
    find "$SSH_DIR" -type f -exec chmod 600 {} \; 2>/dev/null || true
    find "$SSH_DIR" -type d -exec chmod 700 {} \; 2>/dev/null || true
    export HOME="/tmp/app-home"
    mkdir -p "$HOME"
    ln -sfn "$SSH_DIR" "$HOME/.ssh"
  fi

  exec gosu app "$0" "$@"
fi

TASK="${TASK:-webui-server}"
RUN_MODE="${RUN_MODE:-once}"
RUN_INTERVAL_SECONDS="${RUN_INTERVAL_SECONDS:-21600}"
PROVIDER="${PROVIDER:-}"
CLEANUP_APPLY="${CLEANUP_APPLY:-false}"
MAINTENANCE_APPLY_CLEANUPS="${MAINTENANCE_APPLY_CLEANUPS:-false}"

# Use absolute in-container defaults so packaged installs resolve taxonomy files reliably.
export TAXONOMY_CATEGORIES_FILE="${TAXONOMY_CATEGORIES_FILE:-/app/configs/taxonomy/categories.json}"
export TAXONOMY_TAGS_FILE="${TAXONOMY_TAGS_FILE:-/app/configs/taxonomy/tags.json}"
export COOKBOOKS_FILE="${COOKBOOKS_FILE:-/app/configs/taxonomy/cookbooks.json}"
export LABELS_FILE="${LABELS_FILE:-/app/configs/taxonomy/labels.json}"
export TOOLS_FILE="${TOOLS_FILE:-/app/configs/taxonomy/tools.json}"
export UNITS_ALIAS_FILE="${UNITS_ALIAS_FILE:-/app/configs/taxonomy/units_aliases.json}"

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

run_task() {
  case "$TASK" in
    categorize)
      if [ -n "$PROVIDER" ]; then
        python -m cookdex.recipe_categorizer --provider "$PROVIDER"
      else
        python -m cookdex.recipe_categorizer
      fi
      ;;
    taxonomy-refresh)
      TAXONOMY_REFRESH_MODE="${TAXONOMY_REFRESH_MODE:-merge}"
      python -m cookdex.taxonomy_manager refresh \
        --mode "$TAXONOMY_REFRESH_MODE" \
        --categories-file configs/taxonomy/categories.json \
        --tags-file configs/taxonomy/tags.json \
        --cleanup --cleanup-only-unused --cleanup-delete-noisy
      ;;
    taxonomy-audit)
      python -m cookdex.audit_taxonomy
      ;;
    cookbook-sync)
      python -m cookdex.cookbook_manager sync
      ;;
    ingredient-parse)
      python -m cookdex.ingredient_parser
      ;;
    webui-server)
      python -m cookdex.webui_server.main
      ;;
    plugin-server)
      echo "[warn] TASK=plugin-server is deprecated; forwarding to TASK=webui-server."
      python -m cookdex.webui_server.main
      ;;
    foods-cleanup)
      if is_true "$CLEANUP_APPLY"; then
        python -m cookdex.foods_manager cleanup --apply
      else
        python -m cookdex.foods_manager cleanup
      fi
      ;;
    units-cleanup)
      if is_true "$CLEANUP_APPLY"; then
        python -m cookdex.units_manager cleanup --apply
      else
        python -m cookdex.units_manager cleanup
      fi
      ;;
    labels-sync)
      if is_true "$CLEANUP_APPLY"; then
        python -m cookdex.labels_manager --apply
      else
        python -m cookdex.labels_manager
      fi
      ;;
    tools-sync)
      if is_true "$CLEANUP_APPLY"; then
        python -m cookdex.tools_manager --apply
      else
        python -m cookdex.tools_manager
      fi
      ;;
    data-maintenance)
      if is_true "$MAINTENANCE_APPLY_CLEANUPS"; then
        python -m cookdex.data_maintenance --apply-cleanups
      else
        python -m cookdex.data_maintenance
      fi
      ;;
    *)
      echo "[error] Unknown TASK '$TASK'. Use webui-server, categorize, taxonomy-refresh, taxonomy-audit, cookbook-sync, ingredient-parse, plugin-server, foods-cleanup, units-cleanup, labels-sync, tools-sync, or data-maintenance."
      exit 1
      ;;
  esac
}

if [ "$TASK" = "webui-server" ] || [ "$TASK" = "plugin-server" ]; then
  run_task
  exit 0
fi

if [ "$RUN_MODE" = "loop" ]; then
  if ! [[ "$RUN_INTERVAL_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "[error] RUN_INTERVAL_SECONDS must be an integer."
    exit 1
  fi

  echo "[start] Loop mode enabled (task=$TASK, interval=${RUN_INTERVAL_SECONDS}s)"
  while true; do
    run_task
    echo "[sleep] Waiting ${RUN_INTERVAL_SECONDS}s"
    sleep "$RUN_INTERVAL_SECONDS"
  done
fi

if [ "$RUN_MODE" != "once" ]; then
  echo "[error] RUN_MODE must be either 'once' or 'loop'."
  exit 1
fi

run_task
