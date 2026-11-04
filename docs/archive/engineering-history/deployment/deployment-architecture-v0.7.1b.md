> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1b access and deployment architecture

## Public request boundary

```text
Browser
  |
  | HTTPS
  v
Cloudflare proxy
  |
  | HTTPS
  v
Caddy :443
  |
  | private Compose network
  v
FastAPI app ---- PostgreSQL
```

Caddy is the only container that publishes host ports. FastAPI port `8000` and
PostgreSQL port `5432` remain private. Secrets live only in
`deploy/.env.staging`, which is mode `600` and excluded from Git and release
archives.

## Account creation

```text
Owner /operations
  -> exact email + expiry
  -> random invitation secret
  -> SHA-256 hash stored
  -> fragment link displayed once

Invitee opens /invite#token=...
  -> browser removes fragment
  -> same-origin form submission
  -> hash lookup + expiry/revocation/replay checks
  -> account created for exact email
  -> email_verified_at set
  -> invitation atomically consumed
```

Direct registration is rejected in `invite_only` mode. Existing owner accounts
are marked verified by the additive migration so an upgrade does not lock out
the operator.

## Recovery

Only an allowlisted operator can issue recovery links. The link is hashed,
single-use, short-lived, and displayed once. A successful password change
consumes the token and revokes all account sessions in the same transaction.

## CSRF boundary

Every state-changing browser method is checked against the configured public
origin in staging and production. A valid `Origin` is preferred; otherwise the
request must have a same-origin `Referer`. Missing, credential-bearing,
cross-origin, malformed, or non-HTTPS origins fail closed.

This is a same-origin CSRF defense rather than a per-form synchronizer token.
It relies on HTTPS, secure cookies, strict SameSite cookies, and the configured
canonical public origin.

## Rate-limit privacy

Authentication limits are persisted in PostgreSQL so restarts do not reset the
window. The stored subject is an HMAC using a deployment-specific secret. The
raw email and client address cannot be recovered from the ledger.

Cloudflare's `CF-Connecting-IP` is accepted only when
`BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=true`. That switch is unsafe while
the origin accepts direct Internet requests. Leave it false until the origin
boundary is independently reviewed and enforced.

## Tenant isolation

Invitation acceptance creates a normal account and workspace. It does not add
shared access. Existing repository grants, workspace ownership checks, job
detail authorization, Compass ownership, background task ownership, export,
and deletion rules remain unchanged. Cross-account job and profile URLs return
404.

## Operator visibility

`/operations` is authenticated and additionally restricted by the normalized
`BETTEROPTION_OPERATOR_EMAILS` allowlist. It is unlinked for normal users,
returns 404 to unauthorized accounts, sends no-store/no-index headers, and
shows:

- invitation readiness;
- accounts and verification state;
- recent invitation status and revocation;
- one-time password-recovery issuance;
- provider availability, budgets, and payload-free usage metadata.

It never displays password hashes, session hashes, token hashes, provider keys,
prompts, CV text, profile text, job text, or model responses.

## Failure and rollback boundary

The deployment order is database start, additive migration, secret-free
preflight, and full service replacement. The migration does not remove account
or workspace data. Roll back application source only after checking schema
compatibility; preserve and verify a pre-deployment PostgreSQL dump.

