> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# Deployment options for the invited alpha

> **Historical record — superseded.** Use the executable
> [`v0.7.2k` Netcup + Cloudflare runbook](../engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md)
> and its [current capacity decision](hosting-and-public-roadmap-v0.7.2i.md).
> The current default is Netcup VPS 1000 G12 with a dedicated worker and
> Tunnel-only ingress; the provider/example below is not an active order
> recommendation.

This decision record separates three concerns that are easy to conflate:

1. the domain and DNS control plane;
2. the public HTTP edge;
3. the application origin that runs Python, background work, and PostgreSQL.

## Recommended topology

Use Cloudflare for the registered domain, authoritative DNS, and proxied web
traffic. Run BetterOption on one small German or EU virtual machine for the
first invited alpha:

```text
Browser
  -> Cloudflare DNS / HTTPS proxy
  -> Caddy reverse proxy
  -> FastAPI web process
  -> durable BetterOption worker
  -> PostgreSQL
  -> encrypted off-server backups
```

The first server should be a shared-vCPU VM with approximately 4 vCPU, 8 GB
RAM, and 80 GB disk. A Hetzner CX33 is a reasonable starting point. The smaller
2 vCPU / 4 GB class can run a staging instance, but leaves little headroom for
web requests, background extraction, matching, PostgreSQL, and operating-system
cache at the same time.

This is an alpha topology, not the final scaling architecture. Keep the web
process, worker, and database as separate services even when they initially
share one machine. That makes later migration to managed PostgreSQL or
additional workers incremental rather than a rewrite.

## Why the current shared cPanel plan is not the app origin

hosting.com documents a Python Selector that can create a Python application,
virtual environment, requirements installation, environment variables, and a
Passenger entry point. That is useful for a small Python site or a static
marketing companion.

BetterOption also needs:

- an independently supervised background worker;
- durable task recovery;
- PostgreSQL migrations and backup control;
- predictable long-running process behavior;
- deployment-level health checks and logs;
- a controlled upgrade and rollback path.

Those requirements make shared cPanel an unnecessarily fragile production
target. Its existing capacity is still useful for `corecut.net` and, if
desired, a separate static WorkLifeBalance landing page.

## Adding the domain to cPanel, only if a landing page is desired

In cPanel:

1. Open **Domains**.
2. Choose **Create a New Domain**.
3. Enter `betteroption.example`.
4. Clear **Share document root**.
5. Choose a dedicated document root outside the existing site's
   `public_html` tree.
6. Submit the new domain.

Because Cloudflare is authoritative for the domain, create the public DNS
records in Cloudflare. Adding a domain to cPanel does not move DNS authority.
Do not point the production app to cPanel if the VM topology above is used.

## Initial DNS layout

- `app.betteroption.example`: proxied `A` or `AAAA` record to the application VM.
- `betteroption.example`: either the same application, or a landing page with a
  clear link to the app.
- email and provider-verification records: DNS-only unless the provider
  explicitly supports Cloudflare proxying.

The origin firewall should accept public web traffic only through the intended
reverse-proxy path and restrict SSH to trusted administration addresses or a
private access mechanism. Cloudflare does not replace host patching, database
backups, or server monitoring.

## First-alpha operating checklist

Before invitations:

- switch production from SQLite to PostgreSQL;
- run the FastAPI web service and worker as separate supervised services;
- terminate HTTPS at Caddy and keep Cloudflare encryption end-to-end;
- set secure cookies and account authentication;
- store API keys only as server secrets, never in Git or an image;
- take encrypted daily PostgreSQL backups to a different provider or location;
- test a restore, not just backup creation;
- add uptime, error, disk, memory, and worker-heartbeat monitoring;
- add invitation control, email verification/recovery, and rate limiting;
- complete the legal/provider review gates already listed in the roadmap.

## Current cost anchor

At the July 2026 German list price, a Hetzner CX33 is about EUR 10.10 per month
including 19% VAT, excluding optional extras such as backups or additional
addresses. Treat this as the compute floor. Provider APIs, email delivery,
off-server backups, monitoring, and support remain separate unit-economics
lines in Operations.
