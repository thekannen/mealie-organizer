#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-mealie-organizer-webui}"
IMAGE="${MEALIE_ORGANIZER_IMAGE:-ghcr.io/thekannen/mealie-organizer:latest}"
WEB_PORT="${WEB_PORT:-4820}"

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --output-dir <dir>   Deployment directory (default: ${OUTPUT_DIR})
  --image <image>      Container image (default: ${IMAGE})
  --web-port <port>    Host/container web port (default: ${WEB_PORT})
  -h, --help           Show this help

This script creates a minimal standalone Web UI deployment bundle:
  - docker-compose.yml
  - .env
  - README.generated.md
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --web-port)
      WEB_PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR"/{configs,cache,logs,reports}

cat >"$OUTPUT_DIR/.env" <<EOF
# Required: Mealie API endpoint and key
MEALIE_URL=http://127.0.0.1:9000/api
MEALIE_API_KEY=replace-with-mealie-api-key

# Required first boot login + encryption key
WEB_BOOTSTRAP_USER=admin
WEB_BOOTSTRAP_PASSWORD=change-me
MO_WEBUI_MASTER_KEY=replace-with-strong-master-key

# Optional
WEB_BIND_PORT=${WEB_PORT}
WEB_BASE_PATH=/organizer
WEB_STATE_DB_PATH=cache/webui/state.db
EOF

cat >"$OUTPUT_DIR/docker-compose.yml" <<EOF
services:
  mealie-organizer:
    image: ${IMAGE}
    container_name: mealie-organizer
    restart: unless-stopped
    env_file:
      - .env
    environment:
      TASK: webui-server
      RUN_MODE: once
      WEB_BIND_PORT: \\${WEB_BIND_PORT:-${WEB_PORT}}
      WEB_BASE_PATH: \\${WEB_BASE_PATH:-/organizer}
      WEB_STATE_DB_PATH: \\${WEB_STATE_DB_PATH:-cache/webui/state.db}
    ports:
      - "${WEB_PORT}:${WEB_PORT}"
    volumes:
      - ./configs:/app/configs
      - ./cache:/app/cache
      - ./logs:/app/logs
      - ./reports:/app/reports
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF

cat >"$OUTPUT_DIR/README.generated.md" <<EOF
# Mealie Organizer Web UI Deploy Bundle

## 1) Edit .env
Set at minimum:
- MEALIE_URL
- MEALIE_API_KEY
- WEB_BOOTSTRAP_PASSWORD
- MO_WEBUI_MASTER_KEY

## 2) Start

docker compose up -d

## 3) Open Web UI

http://localhost:${WEB_PORT}/organizer

Use WEB_BOOTSTRAP_USER + WEB_BOOTSTRAP_PASSWORD to login.
EOF

echo "[done] Web UI bundle generated at: ${OUTPUT_DIR}"
echo "[next] Edit ${OUTPUT_DIR}/.env then run: docker compose -f ${OUTPUT_DIR}/docker-compose.yml up -d"