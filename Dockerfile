FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEALIE_ORGANIZER_ROOT=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY configs ./configs

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir .

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/cache /app/logs /app/reports \
    && chown -R app:app /app \
    && chmod +x /app/scripts/docker/entrypoint.sh

USER app

ENTRYPOINT ["/app/scripts/docker/entrypoint.sh"]
CMD []
