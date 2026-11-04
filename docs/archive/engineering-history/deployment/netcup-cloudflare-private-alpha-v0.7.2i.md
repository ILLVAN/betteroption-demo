> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Netcup + Cloudflare first private-alpha deployment — v0.7.2i

> **Superseded — do not deploy from this document.** The first server deploy
> moved to the `v0.7.2k` Ubuntu 24.04 runbook. It retains the corrected sudo/SSH
> order, privacy-safe logging boundary and final worker acceptance steps:
> [`netcup-cloudflare-private-alpha-v0.7.2k.md`](netcup-cloudflare-private-alpha-v0.7.2k.md).

Status: operator runbook dated 5 August 2026. This is the first server deploy;
`v0.7.2h` was never deployed. The server therefore starts with a new PostgreSQL
database. Never upload the local SQLite database, local `.env`, test personas,
CVs, job text, provider responses, uploads, sessions, or local backups.

This sequence is intentionally stop-gated. A successful container start is not
permission to invite testers.

## 0. Fixed decisions and required records

- Host: Netcup VPS 1000 G12, preferably Nuremberg and a flexible billing term
  if the final checkout still offers them.
- OS: Debian 13 amd64, minimal image, no hosting control panel.
- Ingress: Cloudflare Tunnel only. Compose publishes no app, Caddy, metrics, or
  PostgreSQL host port.
- Perimeter: a deny-by-default Cloudflare Access application with exact email
  membership exists before the public hostname route.
- Authentication: Access plus the application's own accounts. Bootstrap uses
  `first_user` once, then immediately changes to `invite_only`.
- Runtime: one web container and one dedicated durable task-worker container.
- Data: fresh PostgreSQL; local and server installations remain independent.

Create an operator record outside the server containing the accepted Netcup
order, invoice, term/cancellation date, location, server identifier, initial IP,
verified SSH host-key fingerprint, immutable `v0.7.2i` Git commit/tag, release
ZIP SHA-256, Cloudflare zone/tunnel/application identifiers, and the people who
can perform recovery. Do not put secrets in that record.

Stop if the delivered archive/hash or tag/commit does not match the release
handoff, the server is not empty, Access cannot be configured first, or the
operator has no independent way back through Netcup's console.

## 1. Order and initialize the VPS

At checkout verify the real VAT-inclusive price, VPS 1000 resources, location,
IPv4 treatment, billing interval, minimum term, and cancellation date. Install
Debian 13 from Netcup's Server Control Panel. Add only the operator's existing
SSH public key and keep the rescue console available.

On the operator machine set real values. Verify the SSH fingerprint through the
Netcup console before accepting it:

```sh
ALPHA_HOST="alpha.example.com"
ORIGIN_IP="203.0.113.10"
OPERATOR_CIDR="198.51.100.24/32"

test "${ALPHA_HOST}" != "alpha.example.com"
test "${ORIGIN_IP}" != "203.0.113.10"
test "${OPERATOR_CIDR}" != "198.51.100.24/32"
ssh-keygen -R "${ORIGIN_IP}"
ssh root@"${ORIGIN_IP}"
```

The documentation addresses are non-routable examples. Keep the initial root
session open until a second, hardened login has been proven.

## 2. Create the operator and harden SSH

In the initial root session:

```sh
adduser --disabled-password --gecos "" wlb
usermod -aG sudo wlb
install -d -m 700 -o wlb -g wlb /home/wlb/.ssh
install -m 600 -o wlb -g wlb /root/.ssh/authorized_keys \
  /home/wlb/.ssh/authorized_keys
```

Open a second terminal and prove `ssh wlb@<origin-ip>`. Only then create
`/etc/ssh/sshd_config.d/10-worklifebalance.conf` with:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
AllowUsers wlb
```

Validate before reload:

```sh
sshd -t
systemctl reload ssh
```

Install the host firewall and unattended security updates. Replace the example
CIDR before enabling UFW:

```sh
sudo apt-get update
sudo apt-get install --yes ufw unattended-upgrades ca-certificates curl git jq

OPERATOR_CIDR="198.51.100.24/32"
test "${OPERATOR_CIDR}" != "198.51.100.24/32"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from "${OPERATOR_CIDR}" to any port 22 proto tcp comment 'operator SSH'
sudo ufw enable
sudo ufw status verbose
sudo systemctl enable --now unattended-upgrades
```

There must be no inbound rule for 80, 443, 2000, 5432, or 8000. If the operator
IP is not stable, design a narrow tested SSH path first; do not expose password
SSH as a workaround.

## 3. Install Docker from its official Debian repository

Use Docker's maintained Debian instructions, not the convenience script:

```sh
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: trixie
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install --yes docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker wlb
```

Docker documents that published ports can bypass UFW rules. This release uses
only internal `expose` entries; never add a Compose `ports:` shortcut. End the
session, sign in again, then verify:

```sh
docker version
docker compose version
docker run --rm hello-world
```

Membership in the `docker` group is root-equivalent. Do not add testers or
ordinary accounts to it.

## 4. Stage exactly v0.7.2i

Recommended private-Git path:

```sh
sudo install -d -m 750 -o wlb -g wlb /srv/betteroption
git clone --filter=blob:none "<PRIVATE_READ_ONLY_REPOSITORY_URL>" \
  /srv/betteroption/app
cd /srv/betteroption/app
git fetch --tags --prune
git switch --detach v0.7.2i
git status --short
git rev-parse HEAD
git tag --points-at HEAD
```

`git status --short` must be empty and the printed commit must equal the release
handoff. Use a read-only deploy key. Do not deploy a moving branch.

Archive alternative: transfer only `betteroption_v0_7_2i.zip`, compare it with
the published SHA-256 on both machines, inspect the file list, and extract into
a new `/srv/betteroption/releases/v0.7.2i` directory. Do not unpack over a
running release. The archive must not contain `.env`, a database, `local-data`,
`uploads`, `deploy/backups`, or `deploy/cloudflared-token`.

## 5. Create Cloudflare Access before the route

In Cloudflare Zero Trust:

1. Configure an approved identity method, for example one-time PIN.
2. Go to **Access controls → Applications → Create new application →
   Self-hosted and private → Add public hostname**.
3. Enter only the exact alpha hostname and all paths. Do not use a wildcard.
4. Create an **Allow** policy whose Include selector contains the owner's exact
   normalized email. Do not use `Everyone`, a whole email domain, `Bypass`, or
   “login method = OTP” as the membership rule.
5. Choose a short session duration, save, then run the policy tester with the
   owner address and a non-member address. Owner must match; non-member must not.
6. If external health monitoring is required, create a separate, narrower
   service-auth application for `/health/ready` and a dedicated expiring service
   token. Never create a public health bypass.

Cloudflare states that Access applications deny by default and recommends
creating Access before the tunnel route; without it, a published route is
public. See [self-hosted Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).

Do not create the hostname route yet.

## 6. Create server-only configuration

On the server:

```sh
cd /srv/betteroption/app
test ! -e deploy/.env.staging
test ! -e deploy/cloudflared-token
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging

openssl rand -hex 32
openssl rand -hex 32
sudoedit deploy/.env.staging
```

Use the two generated values separately for `POSTGRES_PASSWORD` and
`BETTEROPTION_AUTH_RATE_LIMIT_SECRET`. Set at least:

```dotenv
SITE_ADDRESS=alpha.example.com
BETTEROPTION_PUBLIC_BASE_URL=https://alpha.example.com
POSTGRES_DB=betteroption
POSTGRES_USER=betteroption
POSTGRES_PASSWORD=<first-random-hex>
BETTEROPTION_AUTH_RATE_LIMIT_SECRET=<second-random-hex>
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=first_user
BETTEROPTION_AUTH_SECURE_COOKIE=true
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
BETTEROPTION_OPERATOR_EMAILS=owner@example.com
BETTEROPTION_APP_ENVIRONMENT=staging
BETTEROPTION_BACKGROUND_WORKER_ENABLED=false
BETTEROPTION_BACKGROUND_WORKER_EXTERNAL=true
BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=20
BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=120
BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0.40
BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD=0.40
```

Keep `BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=false` until the actor review,
budget, and account billing are explicitly approved. `maxItems` is a readback
limit; `maxTotalChargeUsd` is the monetary run ceiling.

Add server-side provider keys only after each processor/source review. Never
reuse a developer's broad personal API key. Keep legal, processor, incident,
and restore readiness flags `false` until each gate has actually passed.

Check file mode and confirm ignored secret/runtime paths:

```sh
chmod 600 deploy/.env.staging
stat -c '%a %n' deploy/.env.staging
git check-ignore .env deploy/.env.staging deploy/cloudflared-token \
  local-data local-backups deploy/backups uploads
git status --short
```

## 7. Create the remotely managed tunnel secret and route

Only after Access exists, go to **Networking → Tunnels**, create a remotely
managed tunnel such as `wlb-private-alpha`, and copy its connector token once.
On the server:

```sh
cd /srv/betteroption/app
install -m 600 /dev/null deploy/cloudflared-token
sudoedit deploy/cloudflared-token
test -s deploy/cloudflared-token
chmod 600 deploy/cloudflared-token deploy/.env.staging
```

Paste only the token, not a shell command. In the tunnel dashboard add one
published application route:

- hostname: the exact alpha hostname;
- service: `http://caddy:80`;
- **Protect with Access**: enabled;
- no catch-all hostname and no route to localhost, HTTPS, app:8000, or the
  origin IP.

Cloudflare documents remotely managed routes in its
[Tunnel dashboard guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

## 8. Static preflight before first start

```sh
cd /srv/betteroption/app
grep '^BETTEROPTION_REGISTRATION_MODE=first_user$' deploy/.env.staging
grep '^BETTEROPTION_BACKGROUND_WORKER_ENABLED=false$' deploy/.env.staging
grep '^BETTEROPTION_BACKGROUND_WORKER_EXTERNAL=true$' deploy/.env.staging
grep '^BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false$' deploy/.env.staging
docker compose --env-file deploy/.env.staging config --quiet
docker compose --env-file deploy/.env.staging config > /tmp/wlb-compose-rendered.yml
```

Inspect `/tmp/wlb-compose-rendered.yml` locally on the server. It contains
resolved secrets; do not upload or paste it. Confirm services `db`, `app`,
`worker`, `retention`, `caddy`, `cloudflared`, and `backup-scheduler`, and
confirm there is no `ports:` section.

```sh
docker compose --env-file deploy/.env.staging build migrate app worker retention
docker compose --env-file deploy/.env.staging up --detach --wait db
docker compose --env-file deploy/.env.staging up --no-deps migrate
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
```

The first empty-database preflight may warn about unfinished operator-managed
reviews. It must not report a configuration error. Do not mark warnings complete
merely to silence them.

## 9. Deploy the empty server once

```sh
cd /srv/betteroption/app
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --tail=120 \
  app worker db caddy cloudflared retention backup-scheduler
docker compose --env-file deploy/.env.staging exec -T cloudflared \
  cloudflared tunnel ready
```

All long-running services must be healthy/running with no restart loop. The
worker must be a separate service; the app must not start an embedded worker.
No local data was migrated: this deployment's PostgreSQL volume is the only
server source of truth.

## 10. Bootstrap exactly one owner, then close registration

In a private browser:

1. Visit the alpha hostname and authenticate through Access with the exact owner
   email.
2. Open `/register`, create the owner account, and sign in.
3. Open Operations and confirm that this first database account is Admin.
4. Stop immediately if any other account exists or the owner is not Admin.

On the server change exactly:

```dotenv
BETTEROPTION_REGISTRATION_MODE=invite_only
```

Redeploy and verify:

```sh
cd /srv/betteroption/app
grep '^BETTEROPTION_REGISTRATION_MODE=invite_only$' deploy/.env.staging
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
```

An anonymous `/register` request must no longer create an account. Keep one
primary admin now; add the named recovery admin before inviting friends.

## 11. Mandatory network and task acceptance

From a machine outside Netcup:

```sh
ALPHA_HOST="alpha.example.com"
ORIGIN_IP="203.0.113.10"
test "${ALPHA_HOST}" != "alpha.example.com"
test "${ORIGIN_IP}" != "203.0.113.10"

curl -I "https://${ALPHA_HOST}/"
nc -zvw3 "${ORIGIN_IP}" 80
nc -zvw3 "${ORIGIN_IP}" 443
nc -zvw3 "${ORIGIN_IP}" 2000
nc -zvw3 "${ORIGIN_IP}" 5432
nc -zvw3 "${ORIGIN_IP}" 8000
```

The hostname must challenge through Access. Every direct-origin web, metrics,
and database probe must fail. A non-member email must be denied by Access.

On the server:

```sh
sudo ss -lntup
docker compose --env-file deploy/.env.staging ps
docker stats --no-stream
free -h
df -h
```

Only the intended SSH listener may be public. Then test durable work:

1. Start an Explore search in the browser.
2. While it is running, restart only the web container:
   `docker compose --env-file deploy/.env.staging restart app`.
3. Return to the stored task. The separate worker must continue; the task may
   reconnect but must not become a permanent 94% illusion.
4. Start another non-essential task and press **Abort task**. It must become
   cancelled, never retry, and never block the next task for that persona.
5. Restart the worker during a disposable task. Its lease must expire and the
   task must safely resume rather than remain permanently running.

After the origin-negative test passes, `BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS`
may be changed to `true` so authentication rate limits use the visitor address.
Set it back to `false` if any direct web listener is ever restored.

## 12. Backup and isolated restore drill

Create one on-demand dump:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging run --rm backup \
  sh /scripts/backup_postgres.sh
ls -l deploy/backups
docker compose --env-file deploy/.env.staging run --rm backup sh -c \
  'for checksum in /backups/betteroption-*.dump.sha256; do sha256sum -c "$checksum"; done'
```

Copy an encrypted backup off the VPS using the operator's reviewed backup tool
and storage account. A same-host dump is not disaster recovery.

Restore the newest dump into an isolated verification database, never over the
live database:

```sh
cd /srv/betteroption/app
latest_dump="$(find deploy/backups -maxdepth 1 -type f \
  -name 'betteroption-*.dump' -printf '%f\n' | sort | tail -n 1)"
test -n "${latest_dump}"

docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'createdb -U "$POSTGRES_USER" betteroption_restore_verify'
docker compose --env-file deploy/.env.staging run --rm \
  -e POSTGRES_DB=betteroption_restore_verify \
  -e ALLOW_RESTORE=true \
  -e RESTORE_FILE="/backups/${latest_dump}" \
  backup sh /scripts/restore_postgres.sh
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d betteroption_restore_verify -c "\\dt"'
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'dropdb -U "$POSTGRES_USER" betteroption_restore_verify'
```

Record the dump hash, start/end time, table check, off-host copy location, and
operator. Only then set `BETTEROPTION_BACKUP_RESTORE_TESTED=true` and redeploy.

## 13. Alpha invitation gate

Before the first friend is invited, all must be true:

- exactly two named human admins exist: owner and recovery operator;
- Access contains each tester's exact email and denies a non-member;
- registration is `invite_only`, invitation expiry works, and account/persona
  isolation has been manually checked;
- legal/privacy/operator details are real and reviewed;
- processor inventory, retention, incident response, provider budgets, and
  off-host restore drill are complete;
- All Jobs remains disabled or uses the `20/120/$0.40` cap with a reviewed
  billing account;
- external monitoring uses Access service credentials and alerts on app,
  worker, tunnel, backup, disk, and restart failure;
- no origin port or secret/runtime file is public or tracked by Git.

## 14. Routine deploy and rollback rule

Before every later deploy, create and copy an off-host backup, verify the new
immutable tag/hash, read its migrations, and run Compose config/preflight. Then
use `deploy/scripts/deploy_staging.sh` and repeat health/origin checks.

Database migrations are forward-moving. Do not simply check out an older tag
after a new migration: an older release may not know the newer Alembic head.
Rollback means restoring the matching pre-deploy database backup together with
the prior code, or shipping a reviewed forward fix. Record which path was used.

Daily operator checks:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --since=24h \
  app worker cloudflared backup-scheduler
docker stats --no-stream
free -h
df -h
```

Track p50/p95 page latency separately from external-provider time, task queue
age/depth, lease recoveries, RSS/swap/OOM, CPU steal/load, database and backup
growth, disk headroom, and container restarts. Upgrade to VPS 2000 only when
these measurements show local resource pressure. Do not buy 4000/8000 to mask
an external provider or single-worker bottleneck.
