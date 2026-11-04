> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Hetzner and Cloudflare staging runbook

This runbook deploys `staging.betteroption.example` before the root domain is
used for real testers. Cloudflare remains the authoritative DNS provider.
Hetzner runs Docker, Caddy, BetterOption, and PostgreSQL on one EU server.

This is a staging topology, not a claim that the invited alpha is legally or
operationally ready.

## 1. Create the Hetzner server

Create a fresh Ubuntu 24.04 server, preferably using an SSH key rather than a
password. A 2-vCPU/4-GB instance is a practical staging floor. Choose more
memory if simultaneous extraction, matching, and database work becomes
noticeably constrained.

In the Hetzner Cloud Firewall allow only:

- TCP 22 from the administrator's current IP address;
- TCP 80 from the internet;
- TCP 443 from the internet;
- UDP 443 from the internet if HTTP/3 is desired.

Do not open PostgreSQL port 5432. `compose.yaml` publishes only Caddy; the app
and database communicate on the private Docker network.

Enable Hetzner server backups for host-level recovery. They complement, but do
not replace, application-consistent PostgreSQL dumps.

Official references:

- [Hetzner Docker CE image](https://docs.hetzner.com/cloud/apps/list/docker-ce/)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Hetzner server backups](https://docs.hetzner.com/cloud/servers/getting-started/enabling-backups/)

## 2. Put the source on the server

Use a private Git checkout or securely copy the clean release source to:

```bash
/opt/betteroption
```

Do not copy the Windows `.env`, SQLite database, CV text, or `local-data` to
staging. Start with an empty PostgreSQL database and a new first account.

## 3. Configure Cloudflare DNS

Create an `A` record:

```text
staging.betteroption.example -> HETZNER_IPV4
```

Add an `AAAA` record only if the server has working IPv6 and the firewall is
configured for it.

For the first certificate check, use **DNS only** so Caddy can reach the
origin directly. After HTTPS is healthy, the record may be changed to
**Proxied** and Cloudflare SSL/TLS mode must be **Full (strict)**. Do not use
Flexible mode: encryption must continue from Cloudflare to Caddy.

Official references:

- [Cloudflare proxied DNS records](https://developers.cloudflare.com/dns/proxy-status/)
- [Cloudflare Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)

Cloudflare proxying hides the origin from ordinary DNS lookups and adds edge
protection, but Cloudflare still processes connection metadata. Reflect the
chosen proxy mode accurately in the privacy notice.

## 4. Create the staging environment

On the server:

```bash
cd /opt/betteroption
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging
openssl rand -hex 32
```

Put the generated value into `POSTGRES_PASSWORD`. Then configure:

- `SITE_ADDRESS=staging.betteroption.example`;
- the real operator email;
- a server-side OpenAI project key;
- optional Brave, Exa, Google Routes, and openrouteservice keys;
- conservative provider-operation and cost ceilings;
- the current legal-draft metadata.

Never commit `deploy/.env.staging`, paste it into an issue, or bake it into the
Docker image. Use a separate provider project/key for staging where the
provider supports it, with its own spending cap.

## 5. Start and verify staging

If Docker and the Compose plugin are already installed:

```bash
cd /opt/betteroption
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging logs --tail=200 app caddy db
```

The app container refuses online startup unless account mode and secure cookies
are enabled. It migrates PostgreSQL to the packaged Alembic head before starting
one Uvicorn process.

Verify:

```bash
curl --fail https://staging.betteroption.example/health/live
curl --fail https://staging.betteroption.example/health/ready
```

Expected readiness includes `"status":"ready"` and
`"database":"postgresql"`.

Register the first owner account. Immediately afterwards change:

```dotenv
BETTEROPTION_REGISTRATION_MODE=disabled
```

Then apply the configuration change:

```bash
docker compose --env-file deploy/.env.staging up --detach
```

Open registration is not an invitation system.

## 6. Back up and prove restore

Create a logical dump:

```bash
mkdir -p deploy/backups
docker compose --env-file deploy/.env.staging --profile tools run --rm backup \
  sh /scripts/backup_postgres.sh
```

The command creates a compressed custom-format dump and SHA-256 checksum.
Local retention defaults to 14 days. A same-server copy is useful for operator
mistakes but is not disaster recovery.

Before inviting users:

1. copy dumps to encrypted storage outside this server;
2. restrict access to the operator;
3. restore a selected dump into a disposable PostgreSQL database;
4. record the successful test date;
5. only then set `BETTEROPTION_BACKUP_RESTORE_TESTED=true`.

The packaged restore script requires both a checksum and an explicit
`ALLOW_RESTORE=true` guard. Never test it against the only staging database.

## 7. Deploy updates

For each accepted version:

```bash
cd /opt/betteroption
git pull --ff-only
docker compose --env-file deploy/.env.staging build app
docker compose --env-file deploy/.env.staging up --detach
docker compose --env-file deploy/.env.staging ps
```

The app performs forward schema migration before serving. Take a database dump
before any migration-bearing release. A code rollback is not automatically a
database rollback.

## Remaining v0.7.1 gates

Do not invite external testers solely because staging answers over HTTPS.
Still required:

- controlled invitations and verified email ownership;
- password recovery;
- CSRF and request-rate review under the deployed proxy topology;
- uptime, exception, disk, database, worker, and backup alerts;
- encrypted off-server backups and a recorded restore drill;
- reviewed legal texts and processor/provider agreements;
- incident and support procedures;
- a tested deployment rollback and account-deletion audit.
