#!/bin/sh
set -eu
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="/backups/betteroption-${timestamp}.dump"

mkdir -p /backups
pg_dump \
  --host="${POSTGRES_HOST:-db}" \
  --port="${POSTGRES_PORT:-5432}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --format=custom \
  --compress=9 \
  --file="${target}"
sha256sum "${target}" > "${target}.sha256"

find /backups -type f -name "betteroption-*.dump" \
  -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
find /backups -type f -name "betteroption-*.dump.sha256" \
  -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete

echo "Created ${target} and checksum."
