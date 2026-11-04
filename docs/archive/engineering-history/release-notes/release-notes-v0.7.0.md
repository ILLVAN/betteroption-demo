> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0 release notes

v0.7.0 introduces the first account and tenant-isolation boundary while keeping
the accepted local workflow unchanged by default.

## Account mode

`BETTEROPTION_AUTH_MODE=local` remains the default. Controlled account testing
can opt in with:

```dotenv
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=first_user
BETTEROPTION_AUTH_SESSION_DAYS=30
BETTEROPTION_AUTH_SECURE_COOKIE=false
```

The first registered owner claims any existing unowned Compass workspaces and
their saved-job access. After that owner is created, registration should be set
to `disabled`. `open` is intended only for a controlled multi-account isolation
test.

Passwords are stored as salted scrypt hashes. Browser sessions use random opaque
tokens; only SHA-256 token hashes are persisted. The cookie is HttpOnly and
SameSite=Lax. Set `BETTEROPTION_AUTH_SECURE_COOKIE=true` only when the service is
behind HTTPS.

## Tenant boundary

The account owns one or more profile workspaces. All existing private data is
already attached to that workspace:

- Compass input and structured facts;
- CV text and review proposals;
- saved-job access grants;
- Match runs and evidence results;
- feedback and application-state history;
- Explore snapshots;
- background tasks.

Every browser route resolves the current account and scopes workspace and saved
job access accordingly. A second account cannot enumerate or open another
account's Compass, Archive, Match result, job detail, or background task.

Public advertisement sources, reachability observations, and revisions remain a
shared corpus. A tenant sees a source only after an explicit saved-job access
grant. Deleting an account removes its private graph and grants without deleting
a public source that another tenant may use.

## Export and deletion

The Account page provides:

- a JSON export of the authenticated account and private workspace graph;
- permanent deletion after password verification and explicit typed
  confirmation.

Exports contain no password hash, session token, API key, or `.env` value.
Deletion revokes every session and cascades through the private workspace graph.

## Explore progress

Explore's persisted task still decides completion. While external providers are
working, the page now shows time-smoothed apparent progress capped at 92%.
It can no longer look frozen at 0%, and it cannot claim 100% until the database
records a successful task.

## Deliberate limits

This release is suitable for local and controlled account-boundary testing. It
is not yet a public or invited online alpha. v0.7.1 still requires PostgreSQL,
HTTPS, secure production cookies, email verification and recovery, invitation
and rate-limit controls, backups, monitoring, legal review, and operational
deletion verification.

