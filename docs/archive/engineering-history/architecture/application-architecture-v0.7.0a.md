> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.7.0a

v0.7.0a introduces the account and tenant boundary without forcing it onto the
existing local product workflow. Authentication is disabled by default. In that
mode, every request continues to use the reserved local tenant and existing
profiles, jobs, CV evidence, match runs, and application history behave exactly
as before.

## Ownership model

| Aggregate | Ownership in v0.7.0a |
| --- | --- |
| Account and browser session | Tenant-owned |
| Profile workspace and Compass | Tenant-owned |
| CV text and review state | Tenant-owned through its profile workspace |
| Archive membership | Tenant-owned |
| Job source, fetched revision, and extraction | Shared public corpus |
| Match result, feedback, application history, and task | Tenant-owned through its profile workspace |
| Provider-operation ledger | Service-level metadata; visible only to the first local administrator when authentication is enabled |

The shared job corpus is intentional. Two tenants can save the same public
advertisement without duplicating its source history, while deleting it from one
Archive removes only that tenant's membership. The shared source is deleted only
after its final membership is removed.

## Request boundary

Authentication middleware resolves one account session before product handlers
run and installs that account's tenant identifier in a request-safe context.
Repositories apply the tenant identifier to every profile, CV, and Archive
operation. A workspace identifier from another tenant therefore resolves as
not found rather than leaking whether it exists.

Background Match work does not inherit an HTTP request context. Its handler
resolves the owning tenant from the persisted workspace, enters that tenant
scope, and only then reads profile and job data.

## Credential and session storage

- Passwords use the standard-library `scrypt` password derivation function with
  an independent random salt for every account.
- Raw passwords are never stored.
- Browser sessions use cryptographically random bearer tokens.
- Only a SHA-256 digest of each session token is stored in the database.
- Cookies are `HttpOnly`, `SameSite=Strict`, and can be marked `Secure` for an
  HTTPS deployment.
- Unsafe cross-origin browser requests are rejected when account mode is active.

## Legacy-data adoption

Migration `0012_accounts_and_tenants` creates the reserved local tenant,
assigns all existing profile workspaces to it, and creates local-tenant Archive
memberships for existing jobs. The first registered account owns that tenant and
is the local administrator. No profile, job, CV, result, or history rewrite is
required.

## Deliberate limits

This is an account-boundary foundation, not a public authentication service.
v0.7.0a does not yet provide email verification, password recovery, invitations,
account export, complete account deletion, deployment rate limiting, or an
external session store. Registration is closed after the first account unless
the operator explicitly enables it.

The next v0.7.0 increment must complete export/deletion and harden deployment
controls before any invited online alpha.
