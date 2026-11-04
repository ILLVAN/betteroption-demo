#!/bin/sh
set -eu

while true; do
  sh /scripts/backup_postgres.sh
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
