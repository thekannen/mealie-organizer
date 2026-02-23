FROM node:20-alpine AS web-build
WORKDIR /web
COPY web/package*.json ./
RUN npm install --no-audit --no-fund
COPY web ./
RUN npm run build:docker

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COOKDEX_ROOT=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md VERSION ./
COPY src ./src
COPY scripts ./scripts
COPY configs ./configs
COPY web ./web
COPY --from=web-build /web/dist ./web/dist

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir '.[db]'

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/cache /app/logs /app/reports /app/web/dist \
    && chown -R app:app /app \
    && chmod +x /app/scripts/docker/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD if [ "${WEB_SSL:-true}" = "false" ]; then \
        curl -f http://localhost:${WEB_BIND_PORT:-4820}${WEB_BASE_PATH:-/cookdex}/api/v1/health; \
      else \
        curl -fk https://localhost:${WEB_BIND_PORT:-4820}${WEB_BASE_PATH:-/cookdex}/api/v1/health; \
      fi || exit 1

ENTRYPOINT ["/app/scripts/docker/entrypoint.sh"]
CMD []