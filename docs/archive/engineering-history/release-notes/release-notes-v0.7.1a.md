> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.7.1a

v0.7.1a is a staging-readiness release for the invited online alpha. It keeps
the accepted discovery, matching, routing, account, and workflow behavior from
v0.7.0i and changes only the deployment boundary and operator documentation.

## Delivered

- a provider-neutral single-node Docker topology targeting a Netcup VPS behind
  Cloudflare-managed DNS;
- a secret-free deployment preflight that blocks unsafe staging configuration;
- an explicit public HTTPS origin setting;
- a deployment script that builds and validates the application before bringing
  the staging services up;
- a Netcup and Cloudflare runbook from server order through owner bootstrap,
  backup verification, and rollback;
- an exact release sequence and parallel legal, security, quality, and tester
  operations plan through the first invited alpha.

## Hard deployment checks

The preflight blocks staging when any of these conditions is true:

- the database is not PostgreSQL;
- the database password is short or resembles a placeholder;
- the application environment is not `staging` or `production`;
- account authentication is not enabled;
- secure cookies are disabled;
- the public base URL is not an absolute credential-free HTTPS URL;
- no operator email is configured.

Warnings remain visible for registration bootstrap, absent extraction
credentials, unconfigured cost estimates or monetary limits, and incomplete
legal, processor, incident, or backup-restore readiness. A warning-free
preflight is an engineering signal, not legal approval.

## Deliberate limits

This release does not deploy a server, change matching, invite users, add
payments, or claim that draft legal text is reviewed. Email verification,
recovery, throttling, monitoring, off-server encrypted backup automation, and
the operational invitation process remain subsequent v0.7.1 gates.

