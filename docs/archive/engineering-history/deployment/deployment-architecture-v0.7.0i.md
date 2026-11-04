> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Staging deployment architecture v0.7.0i

## Runtime boundary

```text
Browser
  -> Cloudflare DNS (optional HTTPS proxy after origin verification)
  -> Hetzner firewall: 80/443 only for web traffic
  -> Caddy: TLS, compression, security headers
  -> FastAPI + current durable in-process worker: private port 8000
  -> PostgreSQL: private port 5432
```

Caddy is the only Compose service with published ports. PostgreSQL and the app
remain reachable only inside the Compose network.

## Why one app process

The current background scheduler lives in the application process and claims
durable tasks from PostgreSQL. One process is therefore the safe first staging
topology. More Uvicorn workers are not a free performance switch: process
coordination must first move into a separately supervised worker contract.

## Data boundary

PostgreSQL is the staging system of record. The `app_data` volume exists only
for application files that cannot live in Git. Images contain code and
dependencies, never environment files or user data.

The container starts only after PostgreSQL is healthy, upgrades the schema, and
then serves traffic. `/health/live` tests the process. `/health/ready` also
executes a database query. Neither probe calls an LLM, search engine, route
provider, or email provider.

## Secret boundary

For this single-node staging increment, secrets are supplied from a mode-600
server file that is excluded from Git and release archives. This is intentionally
smaller than a full secret-management platform. Provider-specific staging keys
and provider-side spending caps reduce blast radius.

Moving secrets into a dedicated secret manager is a later operational hardening
step; it does not require a domain-model rewrite.

## Backup boundary

The packaged tool creates a PostgreSQL custom-format dump and checksum with
bounded local retention. This proves that the database can be exported in an
application-aware form. A production-grade backup system additionally needs
encryption, off-server transfer, monitoring, and a restore drill.

## Next architectural increment

v0.7.1 should separate background execution from the web process, implement the
invitation and recovery boundary, add proxy-aware throttling and monitoring,
and complete off-server backup automation before the first external invitation.
