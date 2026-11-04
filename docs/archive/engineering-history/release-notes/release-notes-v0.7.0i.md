> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0i

v0.7.0i is the first reproducible staging-deployment foundation. It preserves
the accepted v0.7.0h discovery, matching, routing, account, and workflow
behavior. Its deliberately narrow outcome is a single-node private staging
origin on Hetzner with Cloudflare-managed DNS.

## Test repair

Two reported failures came from an obsolete `tests/test_v070a1.py` file left by
a short-lived pre-account overlay. That test expected anonymous profile access
and no longer describes the account-isolated application. Both the overlay
installer and the release-test script now remove that exact stale file before
running the current suite.

The liveness response now follows its documented contract:

```json
{"status": "live", "version": "0.7.0i"}
```

## Staging topology

The release adds:

- a non-root Python 3.12 application image;
- PostgreSQL 17 with no published host port;
- the existing FastAPI process and durable in-process worker in one app
  container;
- Caddy as the only public service on ports 80 and 443;
- automatic schema migration before application startup;
- separate liveness and database-readiness probes;
- local logical PostgreSQL dumps, checksums, retention, and an explicitly gated
  restore command;
- a Hetzner and Cloudflare staging runbook.

The staging app intentionally runs one process. BetterOption's current durable
worker is in-process, so starting several independent web workers could cause
competing task execution. A separately supervised worker belongs to a later
increment.

## Secrets and release safety

`deploy/.env.staging.example` is documentation. The real
`deploy/.env.staging` remains outside Git and release archives and is restricted
to mode `600` on the server. The release builder rejects every usable `.env*`
file while retaining files ending in `.example`.

No local SQLite database, account, Compass, CV text, API key, profile, upload,
or backup is included in the ZIP.

## Deployment boundary

This release makes staging reproducible; it does not invite testers yet.
Invitation/email verification, password recovery, request throttling,
monitoring and alert delivery, encrypted off-server backups with a tested
restore, and completed legal/provider reviews remain v0.7.1 gates.

See [Hetzner and Cloudflare staging](../deployment/hetzner-cloudflare-staging-v0.7.0i.md).
