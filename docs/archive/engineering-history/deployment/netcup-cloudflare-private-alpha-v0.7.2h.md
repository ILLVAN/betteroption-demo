> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Netcup + Cloudflare private-alpha runbook — v0.7.2h

> **Superseded — do not deploy from this document.** Neither `h`, `i`, nor `j`
> was deployed. Use the current `v0.7.2k` Ubuntu 24.04 first-deploy runbook:
> [`netcup-cloudflare-private-alpha-v0.7.2k.md`](netcup-cloudflare-private-alpha-v0.7.2k.md).

Status: executable preparation and acceptance sequence, dated 5 August 2026.
Nothing in this document means that a VPS was ordered, a deployment succeeded,
or a tester may be invited. Record the real command output and gate decisions
when the work is performed.

This runbook replaces the direct-origin steps in the historical `v0.7.1b`
staging guide. Its non-negotiable boundary is:

- Cloudflare Access application and exact-owner policy exist **before** a
  hostname route exists;
- Cloudflare Tunnel is the only web ingress and routes to `http://caddy:80`;
- Compose publishes no host port for Caddy, FastAPI or PostgreSQL;
- the remotely managed connector token lives only in the mode-`600`, ignored
  `deploy/cloudflared-token` Docker-secret source file;
- product login remains behind Access;
- staging uses `first_user` only for the clean owner bootstrap, then switches
  immediately to `invite_only`;
- no friend is invited until the roadmap, compliance, cost and recovery gates
  pass.

The governing decision is
[`hosting-and-public-roadmap-v0.7.2h.md`](../../discontinued-product-planning/hosting-and-public-roadmap-v0.7.2h.md).
Use the release's current local guide and published SHA-256 before transferring
source to the server.

## 1. Order and record the host

At Netcup checkout, confirm the VPS 500 G12 class, Nuremberg location, Debian 13,
contract term, VAT-inclusive total, IPv4 treatment and cancellation date. Save
the order, invoice and recovery details under the controlled business-domain
vendor identity. Do not copy the displayed price from this runbook into the
cost ledger; record the accepted checkout value and effective date.

In Netcup's Server Control Panel, install Debian 13, add the operator SSH public
key, record the initial IPv4 address and keep the rescue-console recovery path.
Do not install a web control panel or open ports 80/443.

On the operator machine, use explicit placeholders and verify the first host key
through Netcup's console before accepting it:

```sh
ALPHA_HOST="alpha.example.com"
ORIGIN_IP="203.0.113.10"
OPERATOR_CIDR="198.51.100.24/32"

test "${ALPHA_HOST}" != "alpha.example.com"
test "${ORIGIN_IP}" != "203.0.113.10"
test "${OPERATOR_CIDR}" != "198.51.100.24/32"
ssh root@"${ORIGIN_IP}"
```

Use the real alpha hostname and addresses; the documentation ranges above can
never identify a live server.

## 2. Create the deploy user and close inbound traffic

From the initial root session, create one named deploy account. Copy only the
already verified SSH key, then prove a second session before disabling root and
password login:

```sh
adduser --disabled-password --gecos "" wlb
usermod -aG sudo wlb
install -d -m 700 -o wlb -g wlb /home/wlb/.ssh
install -m 600 -o wlb -g wlb /root/.ssh/authorized_keys \
  /home/wlb/.ssh/authorized_keys
```

Open a second terminal and confirm `ssh wlb@<origin-ip>` works. Only then add a
small `/etc/ssh/sshd_config.d/10-worklifebalance.conf` drop-in:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

Validate before reloading:

```sh
sshd -t
systemctl reload ssh
```

Install the host firewall, replacing the example CIDR with the fixed operator
address. Keep the original console/session available until the new SSH path has
been tested again.

```sh
apt-get update
apt-get install --yes ufw ca-certificates curl git

OPERATOR_CIDR="198.51.100.24/32"
test "${OPERATOR_CIDR}" != "198.51.100.24/32"
ufw default deny incoming
ufw default allow outgoing
ufw allow from "${OPERATOR_CIDR}" to any port 22 proto tcp comment 'operator SSH'
ufw enable
ufw status verbose
```

There must be no inbound allow rule for 80, 443, 5432, 8000 or 2000. Outbound
DNS, HTTPS and Cloudflare Tunnel connectivity remain allowed. If the operator
IP is not stable, design and test a separate narrow SSH access path before
enabling the firewall; do not temporarily expose password SSH to the world.

Install Docker Engine and the Compose plugin from the
[official Debian repository](https://docs.docker.com/engine/install/debian/),
then verify the installed versions. Docker warns that published container ports
can bypass UFW; this repository therefore uses only `expose`, not `ports`, for
the web stack. The external negative test in section 7 remains mandatory.

```sh
usermod -aG docker wlb
```

Membership in the `docker` group is effectively root access. Grant it only to
the named deploy operator, end the session, sign in again as `wlb`, and then
verify:

```sh
docker version
docker compose version
```

## 3. Stage one accepted source revision

Use the project's private repository or verified release archive. The example
below deliberately requires an accepted immutable ref; never deploy a moving
branch by accident.

```sh
WLB_SOURCE_URL="replace-with-private-repository-url"
WLB_SOURCE_REF="replace-with-accepted-v0.7.2h-tag-or-commit"
test "${WLB_SOURCE_URL}" != "replace-with-private-repository-url"
test "${WLB_SOURCE_REF}" != "replace-with-accepted-v0.7.2h-tag-or-commit"

sudo install -d -m 750 -o wlb -g wlb /srv/betteroption
git clone "${WLB_SOURCE_URL}" /srv/betteroption/app
cd /srv/betteroption/app
git fetch --tags --prune
git switch --detach "${WLB_SOURCE_REF}"
git status --short
git rev-parse HEAD
```

Use an authenticated read-only transport for the private source. If an archive
is used instead, compare it with the published SHA-256 before extraction and
keep the accepted archive off-host. Never transfer a local `.env`, SQLite
database, CV, uploads, provider responses or `local-data/`.

Prepare server-only configuration and independent random secrets:

```sh
cd /srv/betteroption/app
test ! -e deploy/.env.staging
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging
openssl rand -hex 32
openssl rand -hex 32
sudoedit deploy/.env.staging
```

Enter the two generated values separately for the database password and auth
rate-limit HMAC. Before bootstrap, verify at least these exact contracts:

```dotenv
SITE_ADDRESS=alpha.example.com
BETTEROPTION_PUBLIC_BASE_URL=https://alpha.example.com
BETTEROPTION_REGISTRATION_MODE=first_user
BETTEROPTION_AUTH_SECURE_COOKIE=true
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
BETTEROPTION_OPERATOR_EMAILS=owner@example.com
```

Use the real hostname and one exact owner email. Keep incomplete legal,
processor, incident and restore flags `false`; a successful container start
does not make those reviews complete.

## 4. Create Access before creating the route

In Cloudflare Zero Trust, configure an approved login method such as
[one-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
Then create the self-hosted Access application for the exact
`alpha.example.com` hostname and all of its paths **while no Tunnel/DNS route
exists yet**:

1. Go to **Access controls → Applications → Add an application →
   Self-hosted**.
2. Set only the intended alpha hostname and an intentionally short session.
3. Add an **Allow** policy whose Include selector is **Emails** and whose value
   is the owner's one exact normalized email.
4. Do not use `Everyone`, an email-domain wildcard, `Bypass`, or an OTP-login-
   method selector as the membership rule.
5. Save and use the Access policy tester for the owner and one non-member.

Access applications deny unmatched identities by default; the exact policy
configuration is described in Cloudflare's
[self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
and [policy](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/)
documentation.

For external monitoring, create a distinct, expiring Access service token named
only for the alpha health monitor. Create a second, more-specific self-hosted
application for `alpha.example.com/health/ready` with a **Service Auth** policy
that includes only that token. Do not add a public bypass. Cloudflare documents
both [path precedence](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
and the required
[`CF-Access-Client-Id` / `CF-Access-Client-Secret` headers](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).
Store the secret only in the monitoring service's secret store and set an expiry
alert.

## 5. Create the remotely managed Tunnel and secret file

Only after both Access applications exist:

1. Go to **Networking → Tunnels**, create a remotely managed tunnel such as
   `wlb-private-alpha`, and copy its connector token once.
2. On the server, create the ignored Docker-secret source file and paste only
   the token—never the example Docker command—into it.

```sh
cd /srv/betteroption/app
test ! -e deploy/cloudflared-token
install -m 600 /dev/null deploy/cloudflared-token
sudoedit deploy/cloudflared-token
test -s deploy/cloudflared-token
chmod 600 deploy/cloudflared-token deploy/.env.staging
```

3. In that Tunnel, add the published application route for the exact alpha
   hostname to `http://caddy:80` and enable **Protect with Access** token
   validation. Do not point the route at `localhost`, HTTPS, the app container,
   or a public origin port.
4. Confirm no catch-all hostname route was created.

Cloudflare describes remotely managed tunnel creation and published routes in
its [dashboard guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).
Tunnel connections are outbound-only; the repository pins
`cloudflare/cloudflared:2026.7.3` and reads the connector through
`TUNNEL_TOKEN_FILE`.

## 6. Deploy once in `first_user`, then close bootstrap

Validate and deploy the exact checked-out revision:

```sh
cd /srv/betteroption/app
grep '^BETTEROPTION_REGISTRATION_MODE=first_user$' deploy/.env.staging
grep '^BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false$' deploy/.env.staging
docker compose --env-file deploy/.env.staging config --quiet
bash deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --tail=100 app cloudflared caddy
docker compose --env-file deploy/.env.staging exec -T cloudflared \
  cloudflared tunnel ready
```

In a private browser, authenticate through Access with the exact owner email,
open `/register`, create the one owner account, and confirm in `/operations`
that it is the database-backed admin. Stop if the database was not empty, a
different account exists, or the owner is not the only admin.

Immediately edit the server environment to:

```dotenv
BETTEROPTION_REGISTRATION_MODE=invite_only
```

Redeploy and prove that `first_user` is gone:

```sh
cd /srv/betteroption/app
grep '^BETTEROPTION_REGISTRATION_MODE=invite_only$' deploy/.env.staging
bash deploy/scripts/deploy_staging.sh
```

After Access login, a private browser opening `/register` must not be able to
create a second direct account. Never reopen `first_user` on a database that has
already claimed its owner.

## 7. Run the boundary and health smoke tests

Run the first block from a genuinely external network, not from the VPS or its
Docker network. It proves the origin has no direct HTTP/HTTPS listener. Replace
the documentation values and leave `--insecure` out: a TLS failure is part of
the required negative result.

```sh
ALPHA_HOST="alpha.example.com"
ORIGIN_IP="203.0.113.10"
test "${ALPHA_HOST}" != "alpha.example.com"
test "${ORIGIN_IP}" != "203.0.113.10"

if curl --noproxy '*' --silent --show-error --connect-timeout 5 --max-time 8 \
  "http://${ORIGIN_IP}/" >/dev/null; then
  echo 'FAIL: origin answered directly on port 80' >&2
  exit 1
else
  echo 'PASS: no direct origin HTTP response'
fi

if curl --noproxy '*' --silent --show-error --connect-timeout 5 --max-time 8 \
  --resolve "${ALPHA_HOST}:443:${ORIGIN_IP}" \
  "https://${ALPHA_HOST}/" >/dev/null; then
  echo 'FAIL: origin answered directly on port 443' >&2
  exit 1
else
  echo 'PASS: no direct origin HTTPS response'
fi
```

Still without an Access session, prove that the public hostname and readiness
endpoint do **not** expose the application. Access may answer with a redirect or
a non-200 denial, but never application `200`:

```sh
ACCESS_STATUS="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --max-time 15 "https://${ALPHA_HOST}/")"
READY_STATUS="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --max-time 15 \
  "https://${ALPHA_HOST}/health/ready")"

case "${ACCESS_STATUS}" in 302|401|403) ;; *)
  echo "FAIL: unexpected unauthenticated app status ${ACCESS_STATUS}" >&2; exit 1;;
esac
case "${READY_STATUS}" in 302|401|403) ;; *)
  echo "FAIL: unauthenticated health status ${READY_STATUS}" >&2; exit 1;;
esac
curl --silent --show-error --dump-header - --output /dev/null \
  --max-time 15 "https://${ALPHA_HOST}/health/ready"
```

The printed headers must be a Cloudflare Access redirect/denial, not an
application health response. Finally, verify the narrow monitor path with the
service token. Reading interactively keeps the secret out of shell history;
do not enable shell tracing.

```sh
read -r -p 'Access monitor client ID: ' CF_ACCESS_CLIENT_ID
read -r -s -p 'Access monitor client secret: ' CF_ACCESS_CLIENT_SECRET
printf '\n'
MONITOR_STATUS="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --max-time 15 \
  --header "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  --header "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  "https://${ALPHA_HOST}/health/ready")"
unset CF_ACCESS_CLIENT_SECRET
test "${MONITOR_STATUS}" = '200'
echo 'PASS: Access-authenticated readiness is 200'
```

On the VPS, prove that the host itself has no web listener and that only the
internal Compose services expose ports:

```sh
if ss -lnt | awk '$4 ~ /:(80|443)$/ {found=1} END {exit !found}'; then
  echo 'FAIL: host web listener found' >&2
  exit 1
else
  echo 'PASS: host has no listener on 80/443'
fi
docker compose --env-file deploy/.env.staging ps
ufw status verbose
```

Only after all direct-origin negatives pass may the operator set
`BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=true` and redeploy. Set it back to
`false` before restoring any public listener or non-Tunnel route.

## 8. Add the second admin, then testers

One owner admin plus sealed recovery material is enough only for the owner
rehearsal. Before the first friend invitation:

1. complete the legal/processor, spend, backup/restore, incident and isolation
   gates in the canonical roadmap;
2. add the recovery person's exact email to the Cloudflare Access allowlist;
3. issue an application invitation to the same exact email;
4. after acceptance, use Operations with password re-confirmation to promote
   that real person to `admin`;
5. confirm there are exactly two named human admins, test recovery, and keep
   ordinary non-admin accounts for daily product use.

For each later tester, add the same exact email independently to Access and to
an expiring application invitation. Keep role `member`, set only the `tester`
access tier, and keep the test/max experience beneath hard per-workflow,
per-account, daily and global cost budgets. Five admin accounts, shared
passwords and duplicate accounts for one human do not provide resilience.

## 9. Back up, restore-rehearse and roll back

Create a custom-format PostgreSQL backup before every source or schema change:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging --profile tools run --rm backup \
  sh /scripts/backup_postgres.sh
ls -lh deploy/backups/
BACKUP_FILE="$(find deploy/backups -maxdepth 1 -type f \
  -name 'betteroption-*.dump' -printf '%f\n' | sort | tail -n 1)"
test -n "${BACKUP_FILE}"
(cd deploy/backups && sha256sum -c "${BACKUP_FILE}.sha256")
```

Copy an encrypted version to a separately controlled off-host destination and
prove it can be retrieved. The same-host `deploy/backups/` directory is only a
rollback aid. Keep the decrypt credential off the VPS and record retention,
last successful copy, checksum and restore duration without recording data or
secret values.

Perform the first restore rehearsal on a disposable clone, never by overwriting
the only live database. For a confirmed incident requiring an in-place restore,
announce a write stop, take a final dump if safe, stop writers, name one verified
backup explicitly, and use the guarded script:

```sh
cd /srv/betteroption/app
RESTORE_BASENAME="betteroption-YYYYMMDDTHHMMSSZ.dump"
test -f "deploy/backups/${RESTORE_BASENAME}"
docker compose --env-file deploy/.env.staging stop app retention backup-scheduler caddy
docker compose --env-file deploy/.env.staging --profile tools run --rm \
  --env ALLOW_RESTORE=true \
  --env RESTORE_FILE="/backups/${RESTORE_BASENAME}" \
  backup sh /scripts/restore_postgres.sh
docker compose --env-file deploy/.env.staging up --detach --wait
```

Re-run every boundary and application smoke test after restore. Do not mark the
restore gate complete from backup creation alone.

For an application-only rollback, first confirm the old source supports the
current database schema. Preserve the failing revision and logs, create a fresh
pre-rollback dump, then deploy the exact last accepted immutable ref:

```sh
cd /srv/betteroption/app
git log --oneline -5
ROLLBACK_REF="replace-with-last-accepted-compatible-tag-or-commit"
test "${ROLLBACK_REF}" != \
  "replace-with-last-accepted-compatible-tag-or-commit"
git switch --detach "${ROLLBACK_REF}"
git rev-parse HEAD
bash deploy/scripts/deploy_staging.sh
```

If schema compatibility is not proven, stop writes and use the verified
pre-deployment dump instead of guessing or deleting tables. Cloudflare Access,
Tunnel and firewall controls remain in place during both rollback paths.

## Acceptance record

Before calling the owner rehearsal ready, attach dated evidence for:

- accepted source ref and release hash;
- server invoice/contract and business-domain account ownership;
- SSH recovery and firewall rules;
- Access exact-owner denial/allow tests and service-token expiry;
- Tunnel connector health, `Protect with Access`, and no catch-all route;
- external origin 80/443 negatives and unauthenticated health denial;
- one owner bootstrap followed by `invite_only`;
- encrypted off-host backup retrieval, disposable restore and rollback time;
- monitoring, spend caps, provider kill switch and named incident owner.

Passing this list authorizes only the owner rehearsal. The two-admin, cost,
compliance and support gates still decide when a named friend may be invited.
