> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2

`v0.7.2` is the consolidation release after the `v0.7.1a`–`v0.7.1s`
refinement cycle. It does not replace accepted workflows or widen the hosting
boundary. It reduces dense UI, repairs the configured JSearch source, makes
language evidence explicit, and turns the route to a first online private alpha
into one evidence-gated plan.

## Explore and scanning

- Filters and query context are available in compact expandables instead of
  occupying the result surface.
- Source contribution keeps its existing status tiles but is collapsed until
  the user asks for it. Cost/source architecture prose is removed from the
  normal scanning path.
- Explore alone uses full-width compact result rows suited to 100+ candidates.
  Archive, Home and Match retain their existing cards.
- Saved employer portal links move behind one **Portal links** expandable.
- **Exa** is the user-facing label; the historical internal provider key remains
  compatible with stored operations and results.

## Compass and matching

- Spoken languages are editable Experience evidence with search, explicit
  enablement and beginner/intermediate/professional/native levels.
- Programming languages use a separate optional expandable editor with the same
  compact controls.
- Saved language evidence is profile/persona-owned, contributes to guided
  Experience readiness, own-value evidence and rematch fingerprinting, and is
  available before a Match begins.
- Explicit job-language levels such as CEFR labels are treated as soft evidence.
  A missing required language still matters, but a plausible user level is not
  converted into an unnecessarily harsh blocker.
- Standard train, car and bicycle limits remain part of mobility scoring without
  appearing again as duplicate Compass checks. Truly custom modes remain
  visible, and the UI calls rail travel **train**, not transit.
- The optional CV path becomes an expandable primary Compass tile. Provider
  details remain in expandable explanations rather than page headings.

## Routing and job detail

- Route evidence leads with one representative duration. The observed range is
  retained as smaller secondary evidence rather than competing with the main
  value.
- Employer relationship controls receive enough width for readable **Your
  value** fields and saved-correction status.
- The organisation-type prompt is shortened; the redundant “Multiple types can
  apply” sentence is removed.

## OpenWebNinja JSearch

The observed `0.7.1s` failure was a response-processing defect. The current
`search-v2` success envelope places vacancies under `data.jobs`; the previous
adapter required `data` itself to be a list and raised `JSearchResponseError`
for valid HTTP 200 responses.

`v0.7.2`:

- accepts the canonical nested envelope plus bounded compatible variants;
- validates success/error envelopes before parsing vacancy rows;
- separates authentication, plan, rate-limit, availability, request and schema
  categories without retaining request or response material;
- stops query fan-out after a rate limit instead of spending further allowance;
- prints fixed `detail` and `next_step` guidance from the explicit live
  diagnostic while keeping keys, queries, URLs and bodies absent.

## Release and documentation

- `scripts/dump_release.ps1` builds the reviewed source ZIP through the same
  release builder used by tests. It validates the exact archive name and removes
  a stale or partial artifact at that path before building.
- The root README is now the current operating guide rather than an accumulating
  release history.
- `docs/README.md` distinguishes current guidance from historical records.
- `docs/archive/discontinued-product-planning/roadmap-to-private-alpha.md` is the single canonical route from this
  local release to a fully online, invitation-only `v0.8.0` cohort.
- The compliance README now names the current product baseline without implying
  that its external review or operational gates are complete.

## Identity and compatibility

- Application: `0.7.2`
- Python package: `0.7.2`
- Matching algorithm: `matching-v0.7.2`
- Release archive: `betteroption_v0_7_2.zip`
- Git tag: `v0.7.2`
- Database migration head: unchanged at `0030_verified_job_posters`

Existing `.env`, SQLite/PostgreSQL data, CV text, personas, Compass facts, jobs,
matches and application history remain compatible. No migration is introduced
for language preferences; they use the existing confirmed-evidence model. An
existing `v0.7.1s` `.env` keeps its values by design, so the local guide includes
one exact-string update for its three public outbound User-Agent overrides.

## Validation boundary

The release gate is formatting, lint, the complete regression suite, bytecode
compilation, targeted UI/provider/language tests, and inspection of the built
archive for forbidden runtime/private material. Live provider success still
depends on the configured account, plan, quota and network and must be checked
with the explicit secret-safe diagnostic.

This remains a localhost evaluation release. It does not authorize invitations
or a hosted alpha; follow the current roadmap and compliance launch record.
