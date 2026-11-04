> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0b — Accounts, alpha controls, and durable imports

v0.7.0b consolidates the account-security line, invited-alpha controls, and
durable Explore import work under one tested release identity. It deliberately
preserves accepted discovery, matching, routing, profile extraction, and
tenant-owned data behavior.

## Release-composition repair

The prior source overlay combined background-job-import code with an older
account module. The packaged tests expected the current registration and
username contracts, so collection failed before product behavior could be
tested.

v0.7.0b uses the complete compatible account and tenant-isolation foundation,
then adds the background workflow changes on top. `RegistrationMode` and
`USERNAME_MAX_LENGTH` remain first-class production contracts rather than being
patched into tests or bypassed.

## Durable Explore imports

- Selected Explore URLs are stored as a private, ordered import batch belonging
  to the active workspace.
- Verification and extraction run as a persisted `job_import` task when the
  background worker is enabled.
- “Save and run Match” chains a successful import into the established
  background Match task.
- Import payloads are deleted after completion and are not mixed into the
  metadata-only operational task record.
- Existing synchronous behavior remains a local fallback when the worker is
  deliberately disabled.

## Search and guided-profile corrections

- The current structured Compass origin takes precedence over older extracted
  location facts, preventing stale locations from redirecting Explore.
- “Hide remote-only roles” filters the current result cards immediately and
  does not trigger another provider search.
- Guided Compass clarification questions retain section suggestions.
- Frontend selection counts only visible Explore cards after client-side
  filtering.

## Account controls

- Usernames are normalized with Unicode NFKC, trimmed, collapsed to single
  spaces, limited to 32 characters, and unique case-insensitively.
- Sign-in emails remain normalized, immutable, and unique account identifiers.
- Username changes require the current password.
- Password changes require the current password and revoke every active
  server-side session for that account.
- Permanent deletion is available through a collapsed danger section so it
  remains discoverable without dominating the Account page.
- The header account chip is turquoise and safely truncates long usernames.

Migration `0014_account_security` is additive. Existing usernames are normalized
and bounded during upgrade. Case-insensitive legacy collisions receive stable
numeric suffixes before the unique database index is created.

## Operator maintenance

Home no longer renders provider statistics, provider configuration, or a link to
the maintenance surface. `/operations` is unlinked and requires:

1. account authentication; and
2. an exact normalized email match in `BETTEROPTION_OPERATOR_EMAILS`.

Unauthorized accounts receive a 404 response. The response is marked
`Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`.

This is authorization, not security through an obscure URL. It avoids adding a
user-facing role hierarchy while the controlled alpha has one or a few named
operators.

## Security boundary

The release ZIP excludes `.env`, databases, profile records, sessions, CVs,
uploads, and local data. Passwords remain scrypt hashes and browser session
tokens remain opaque with only their SHA-256 hashes stored.

Migration `0016_background_job_imports` follows the existing alpha-readiness
migration and adds only the private import-batch tables.

Before internet exposure the deployment still requires HTTPS-only cookies,
PostgreSQL, invite/email verification and recovery, login rate limits, trusted
proxy configuration, encrypted backups, alerting, dependency scanning,
penetration testing, a deletion audit, and legal review. v0.7.0b does not claim
public-production readiness.
