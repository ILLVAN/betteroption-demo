#!/bin/sh
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "${project_root}"

if [ ! -f deploy/.env.staging ]; then
  echo "Missing deploy/.env.staging. Copy the example and add server secrets first." >&2
  exit 1
fi

if [ ! -s deploy/cloudflared-token ]; then
  echo "Missing deploy/cloudflared-token. Add the remotely managed Tunnel token first." >&2
  exit 1
fi

chmod 600 deploy/.env.staging
chmod 600 deploy/cloudflared-token
docker compose --env-file deploy/.env.staging config --quiet
docker compose --env-file deploy/.env.staging build migrate app worker retention
docker compose --env-file deploy/.env.staging up --detach --wait db
docker compose --env-file deploy/.env.staging up --no-deps migrate
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
docker compose --env-file deploy/.env.staging up --detach --build --wait
docker compose --env-file deploy/.env.staging ps

echo "Staging deployment requested. Verify the Access-protected HTTPS endpoint."
echo "A successful preflight does not authorize external invitations while warnings remain."
