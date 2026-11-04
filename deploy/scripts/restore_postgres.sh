#!/bin/sh
set -eu

if [ "${ALLOW_RESTORE:-}" != "true" ]; then
  echo "Restore refused. Set ALLOW_RESTORE=true after verifying the target." >&2
  exit 2
fi

if [ -z "${RESTORE_FILE:-}" ]; then
  echo "RESTORE_FILE must name a dump below /backups." >&2
  exit 2
fi

case "${RESTORE_FILE}" in
  /backups/*.dump) ;;
  *)
    echo "RESTORE_FILE must be an absolute /backups/*.dump path." >&2
    exit 2
    ;;
esac

test -f "${RESTORE_FILE}"
test -f "${RESTORE_FILE}.sha256"
sha256sum -c "${RESTORE_FILE}.sha256"

pg_restore \
  --host="${POSTGRES_HOST:-db}" \
  --port="${POSTGRES_PORT:-5432}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --clean \
  --if-exists \
  --no-owner \
  "${RESTORE_FILE}"

echo "Restore completed from ${RESTORE_FILE}."
