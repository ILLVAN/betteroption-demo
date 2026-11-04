FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN addgroup --system betteroption \
    && adduser --system --ingroup betteroption --home /app betteroption

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY deploy/scripts/start_app.sh /usr/local/bin/start-betteroption

RUN python -m pip install --no-cache-dir ".[extraction,deployment]" \
    && chmod 0555 /usr/local/bin/start-betteroption \
    && mkdir -p /app/local-data \
    && chown -R betteroption:betteroption /app

USER betteroption

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/start-betteroption"]
