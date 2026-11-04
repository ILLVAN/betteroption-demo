> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.7.1b

v0.7.1b is the secure invitation-onboarding increment for the private online
alpha. It preserves the accepted discovery, matching, routing, account,
application-state, background-workflow, and staging behavior from v0.7.1a.

## Delivered

- invitation-only account creation from the operator-only Operations page;
- exact normalized-email invitations with random secrets stored only as hashes;
- automatic email verification when an exact-address invitation is accepted;
- expiring, single-use invitation and password-recovery links;
- immediate invalidation of every active session after password recovery;
- payload-free authentication throttling using HMAC identifiers;
- optional Cloudflare visitor-address handling behind an explicit trust switch;
- same-origin protection for every state-changing browser request in staging
  and production;
- owner views for accounts, verification state, pending invitations, revocation,
  and one-time recovery links;
- migration and regression coverage for authentication and tenant isolation;
- an updated Netcup/Cloudflare deployment and rollback cycle.

## Token handling

The application displays invitation and recovery links exactly once. The secret
is placed after the URL fragment marker, so it is not sent in the initial HTTP
request, reverse-proxy access log, or referrer. Browser JavaScript moves it into
the submitted form and removes the fragment from the visible URL. The database
stores only a SHA-256 hash.

An invitation is restricted to one normalized email address. Possession of the
link and successful account creation marks that address verified. The operator
must therefore deliver the link to that exact address through a trusted channel.
There is no transactional-mail provider in this release.

Password recovery is operator-issued to avoid a public account-enumeration
surface. A successful reset invalidates all existing sessions.

## Rate limiting and Cloudflare

Authentication attempt records contain only a purpose, timestamp, and an HMAC
of the normalized authentication subject and client boundary. Raw email
addresses, IP addresses, passwords, tokens, profiles, and prompts are not stored
in that table.

`BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS` defaults to `false`. Enable it only
after direct access to the origin is prevented, for example through a trusted
Cloudflare tunnel or a reviewed origin firewall/certificate design. Otherwise a
direct requester could forge the visitor-address header. With trust disabled,
rate limiting remains active but uses the direct proxy peer boundary.

## Invitation gate

The Operations page can create invitations only when:

1. account mode is active;
2. registration mode is `invite_only`;
3. legal review is recorded complete;
4. configured processors are reviewed;
5. the incident-response plan is ready; and
6. a backup restore drill is recorded complete.

These flags are operator assertions. Do not set them merely to unlock the
button. v0.7.1b does not claim legal approval or restore proof.

## Pricing configuration

Numeric cost settings must contain numeric values. Leaving them blank is a
configuration error. Use an explicit `0` only while the current price is
unknown. BetterOption treats zero as **unpriced**, never as free, and preflight
keeps the corresponding warning visible.

## Validation contract

The release suite covers invitation bypass attempts, exact-address
normalization, token hashing, expiry, revocation, replay, recovery replay,
session revocation, unverified-account rejection, rate-limit bounds, HMAC-only
storage, Cloudflare trust behavior, missing and cross-origin form submissions,
operator authorization, readiness gating, tenant isolation, migration, release
contents, and every earlier product regression.

## Remaining private-alpha gates

- redacted error and uptime monitoring;
- disk, database, worker, and provider-budget alerts;
- encrypted off-server backup automation and a documented restore result;
- reviewed legal texts, processor register, incident and support playbooks;
- staging smoke, rollback, concurrency, and tester-onboarding sign-off.

