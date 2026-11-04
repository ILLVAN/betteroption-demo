> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local environment audit — v0.7.2d

This is a secret-free review of the local configuration shown during the
`v0.7.2d` iteration. It does not reproduce credential values.

## Localhost: current shape is appropriate

These choices fit a single-machine development run:

- `BETTEROPTION_APP_ENVIRONMENT=local`
- account mode with account-owned personas and legacy local personas disabled
- SQLite under `local-data`
- empty public base URL
- secure cookies and trusted Cloudflare headers disabled
- loopback host `127.0.0.1`
- the in-process persistent background worker enabled
- all configured discovery providers called in parallel, followed by local
  deduplication and ranking

`BETTEROPTION_REGISTRATION_MODE=open` is acceptable only while intentionally
creating local test accounts. Change it to `disabled` and restart once those
accounts exist; existing accounts can still sign in.

## Cleanup and hardening

1. Replace the legacy `BETTEROPTION_EXA_FALLBACK_MIN_RESULTS` name with
   `BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS`. It is ignored while
   `BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true`, but the canonical name avoids
   implying that Exa has privileged fallback status.
2. Keep numeric cost fields present. A zero estimate means *unpriced*, not free.
   A zero daily or workflow USD limit disables that monetary guard. Enter measured
   prices and non-zero limits before invitations.
3. Keep provider keys only in `.env`; never copy them to examples, diagnostics,
   screenshots or release archives.
4. Keep the public-service User-Agent version. Transitous, Valhalla and Nominatim
   need an identifiable client. The GitHub address can be replaced later by a
   stable public contact page, but removing all contact information is worse.
5. Keep the background poll/retry values grouped together. A durable task may be
   resumed after a restart; `v0.7.2d` makes task creation atomic and explicitly
   requeues an interrupted claim during graceful shutdown.

Specific values from the reviewed local snapshot are valid but deserve an
intentional choice:

- `BETTEROPTION_PROVIDER_DAILY_OPERATION_LIMIT=6000` and
  `BETTEROPTION_PROVIDER_ACTION_OPERATION_LIMIT=1000` are much more permissive
  than the current reference values `1000` and `200`. Lower them while measuring
  costs unless the larger allowance is deliberate.
- `BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0` disables the actor-level
  monetary charge guard. Configure it from the actual Actor contract before
  repeated or hosted use.
- `BETTEROPTION_ARBEITNOW_PAGES=8` is an intentional narrower scan than the
  current reference value `30`. Keep 8 for speed or remove/update the override
  when broader keyless coverage is more important.
- `BETTEROPTION_MOBILITY_PRIVACY_MODE=balanced` explicitly permits Google-first
  routing when a Google Routes key is configured. Use `privacy_first` if that is
  not the desired local trade-off.
- The shown legal draft versions predate the packaged terms/privacy versions.
  Read the packaged drafts, then align `BETTEROPTION_LEGAL_TERMS_VERSION` and
  `BETTEROPTION_LEGAL_PRIVACY_VERSION` deliberately; changing them can require
  accounts to acknowledge the updated text.

The checked and sorted reference is [`.env.example`](../../../../.env.example). Running
`scripts/diagnose_config.py` reports effective state, duplicate assignments,
legacy aliases and hosted-readiness warnings without printing credentials.

## Before private online alpha

Move to the hardened staging shape in
[`deploy/.env.staging.example`](../../../../deploy/.env.staging.example):

- `BETTEROPTION_APP_ENVIRONMENT=staging`
- public HTTPS base URL and secure cookies
- `invite_only` or `disabled` registration
- PostgreSQL rather than SQLite
- deployment-specific authentication rate-limit secret
- explicit operator email allow-list
- completed controller/contact fields and reviewed legal versions
- only reviewed hosted providers enabled
- real provider unit prices and non-zero daily/workflow cost ceilings
- tested backup/restore and incident procedure

Do not reuse local credentials or the local authentication-rate secret on the
server. Provider activation remains an account choice; configuring a key does not
make its results rank higher.
