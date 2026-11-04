> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Staging deployment architecture v0.7.1a

## Runtime boundary

```text
Browser
  -> Cloudflare DNS and HTTPS proxy
  -> Netcup and host firewalls: 80/443 only for web traffic
  -> Caddy: TLS, compression, security headers
  -> FastAPI + current durable in-process worker: private port 8000
  -> PostgreSQL: private port 5432
```

Caddy is the only Compose service with published ports. PostgreSQL and the app
remain reachable only inside the Compose network. The topology is portable:
Netcup is the current operator choice, not a dependency in application code.

## Capacity boundary

The first staging node is a Netcup VPS 500 G12 with 4 GB RAM. It is a measured
starting point for 10–30 invited users, not a high-availability promise. Search,
language-model, and most route computation is performed by external providers.
One app process and bounded provider work keep initial local demand modest.

CPU, memory, disk, provider concurrency, p50/p90 latency, and background queue
age decide whether to resize. Extra same-host block storage is deliberately not
required for the first checkpoint.

## Why one app process

The current background scheduler lives in the application process and claims
durable tasks from PostgreSQL. One process is therefore the safe first staging
topology. More Uvicorn workers are not a free performance switch: process
coordination must first move into a separately supervised worker contract.

## Data and health boundary

PostgreSQL is the staging system of record. The `app_data` volume exists only
for application files that cannot live in Git. Images contain code and
dependencies, never environment files or user data.

The container starts only after PostgreSQL is healthy, upgrades the schema, and
then serves traffic. `/health/live` tests the process. `/health/ready` also
executes a database query. Neither probe calls an LLM, search engine, route
provider, or email provider.

## Secret and configuration boundary

For this single-node staging increment, secrets are supplied from a mode-600
server file excluded from Git and release archives. Provider-specific staging
keys and provider-side spending caps reduce blast radius.

The preflight reads configuration locally, makes no provider calls, and prints
no credentials. It blocks a non-PostgreSQL database, weak or placeholder
database password, local environment, local authentication, insecure cookies,
invalid public HTTPS origin, or absent operator allowlist.

Moving secrets into a dedicated secret manager is later operational hardening;
it does not require a domain-model rewrite.

## Backup boundary

The packaged tool creates a PostgreSQL custom-format dump and checksum with
bounded local retention. The invited alpha additionally requires encrypted
off-server transfer to a separate EU failure domain, monitoring, and a proven
restore into a disposable environment. A Netcup snapshot or volume can
complement this but cannot be the only backup.

## Next architectural increments

v0.7.1b adds controlled invitations, verified email, recovery, proxy-aware rate
limits, and CSRF review. v0.7.1c adds redacted monitoring, alerts, off-server
backup automation, and the restore drill. Legal and operational review and the
actual staging release candidate remain separate gates before invitations.

