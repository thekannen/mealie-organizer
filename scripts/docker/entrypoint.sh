#!/usr/bin/env bash
set -euo pipefail

TASK="${TASK:-categorize}"
RUN_MODE="${RUN_MODE:-once}"
RUN_INTERVAL_SECONDS="${RUN_INTERVAL_SECONDS:-21600}"
PROVIDER="${PROVIDER:-}"

run_task() {
  case "$TASK" in
    categorize)
      if [ -n "$PROVIDER" ]; then
        python -m mealie_organizer.recipe_categorizer --provider "$PROVIDER"
      else
        python -m mealie_organizer.recipe_categorizer
      fi
      ;;
    taxonomy-refresh)
      TAXONOMY_REFRESH_MODE="${TAXONOMY_REFRESH_MODE:-merge}"
      python -m mealie_organizer.taxonomy_manager refresh \
        --mode "$TAXONOMY_REFRESH_MODE" \
        --categories-file configs/taxonomy/categories.json \
        --tags-file configs/taxonomy/tags.json \
        --cleanup --cleanup-only-unused --cleanup-delete-noisy
      ;;
    taxonomy-audit)
      python -m mealie_organizer.audit_taxonomy
      ;;
    cookbook-sync)
      python -m mealie_organizer.cookbook_manager sync
      ;;
    *)
      echo "[error] Unknown TASK '$TASK'. Use categorize, taxonomy-refresh, taxonomy-audit, or cookbook-sync."
      exit 1
      ;;
  esac
}

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
