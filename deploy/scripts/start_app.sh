#!/bin/sh
set -eu

if [ "${BETTEROPTION_AUTH_MODE:-}" != "accounts" ]; then
  echo "Refusing online startup: BETTEROPTION_AUTH_MODE must be accounts." >&2
  exit 1
fi

if [ "${BETTEROPTION_AUTH_SECURE_COOKIE:-}" != "true" ]; then
  echo "Refusing online startup: BETTEROPTION_AUTH_SECURE_COOKIE must be true." >&2
  exit 1
fi

case "${BETTEROPTION_RUN_STARTUP_MIGRATIONS:-true}" in
  true)
    python -m betteroption.deployment migrate
    ;;
  false)
    ;;
  *)
    echo "Refusing online startup: BETTEROPTION_RUN_STARTUP_MIGRATIONS must be true or false." >&2
    exit 1
    ;;
esac

exec python -m uvicorn betteroption.web.app:create_app \
  --factory \
  --host "${BETTEROPTION_WEB_HOST:-0.0.0.0}" \
  --port "${BETTEROPTION_WEB_PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --no-access-log \
  --workers 1
