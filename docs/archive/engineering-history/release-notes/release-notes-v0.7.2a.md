> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2a

`v0.7.2a` is a focused reliability and density update on top of `v0.7.2`.
It keeps the current matching model and database head while repairing the live
JSearch transport path, adding a distinct JobsPipe source, and folding Match
run context and destructive controls away from the normal scanning surface.

## OpenWebNinja JSearch

- The direct OpenWebNinja contract remains the documented
  `GET /jsearch/search-v2` endpoint with the key in `x-api-key`.
- Provider-created clients now respect the operating system's HTTPS proxy and
  certificate environment. This fixes Windows/network configurations that can
  reach other services but require environment routing for this host.
- The explicit one-request diagnostic no longer merges DNS/connectivity, TLS,
  proxy, timeout and provider HTTP failures into one generic network outcome.
  Every printed category and next step remains fixed and secret-safe.
- Request queries, URLs, response bodies and keys remain absent from logs,
  diagnostics and provider-operation rows.

## JobsPipe via Apify

- Explore gains the separate `jobspipe/jobspipe-job-search` actor through the
  official synchronous Apify dataset endpoint.
- JobsPipe and EURES may share `APIFY_API_TOKEN`, but they have different
  provider IDs, Account permissions, actor endpoints, result labels, limits,
  operation rows and cost settings.
- The new JobsPipe permission defaults off. A pre-existing Apify token or EURES
  approval cannot silently widen the recipient set; the account owner must
  enable **JobsPipe via Apify** explicitly.
- One JobsPipe run receives bounded title alternatives, an offline-resolved
  country code, the remote-only flag and at most 150 requested results. It does
  not receive the complete Compass, account/persona identity, CV or ratings.
- Stable IDs are deduplicated; malformed rows fail closed; public source/apply
  URLs, date, location, tags and any stated salary are mapped into the ordinary
  Explore candidate contract.
- Hosted environments still fail closed until processor review is complete.
- The current recipient/source boundary and the remaining alpha blockers are
  recorded in the [v0.7.2a JobsPipe source review](../providers/job-source-review-v0.7.2a.md).

## Match page

- **Info** and **Run facts** are closed native disclosures with compact summary
  lines instead of stacked full-width panels.
- Stale Compass/model notices remain discoverable through a visible **Review
  notices** state without occupying the page by default.
- **Select jobs to delete** is a separate closed disclosure. Its live count,
  select-all control, confirmation flow and disabled-until-selected button are
  preserved.
- Explore's accepted compact layout is unchanged.

## Identity and compatibility

- Application and package: `0.7.2a`
- Matching algorithm: unchanged at `matching-v0.7.2`
- Database migration head: unchanged at `0030_verified_job_posters`
- Release archive: `betteroption_v0_7_2a.zip`
- Git tag: `v0.7.2a`

Existing `.env`, databases, accounts, personas, Compass evidence, jobs,
matches, ratings and application history remain compatible. The installer
preserves runtime data. The new JobsPipe limit and cost settings have safe
defaults when an existing `.env` does not yet contain them.

The [local release guide](../local-guides/local-v0.7.2a.md) is the single release hand-off for
backup, installation, environment upgrade, JSearch/JobsPipe checks, the full
test gate, manual acceptance, source dump and reviewed Git push/tag commands.

## Validation boundary

The release gate consists of formatting, lint, the complete regression suite,
bytecode compilation, focused JSearch/JobsPipe/Match-disclosure tests, and a
forbidden-content scan of the built archive. Live provider success still
depends on the configured key/token, entitlement, allowance and local route.

This remains a localhost evaluation release. JobsPipe is a new
community-maintained actor and must complete the documented provider/source,
processor, transfer, retention and reuse review before external-alpha use.
