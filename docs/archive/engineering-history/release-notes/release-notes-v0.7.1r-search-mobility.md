> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1r-search-mobility

R is a local-first search-quality and Compass-control release. It fixes the
structured Explore regression, adds two bounded optional job sources, and lets
each persona maintain a coarse starting point and modal commute limits without
requiring an exact home address.

## Explore relevance and sources

- Structured Compass searches now require real title/summary evidence for a
  desired role. Proximity can no longer lift an unrelated vacancy into a useful
  result merely because it is nearby.
- Shared raw-feed caches are re-filtered against the active persona's current
  query. Cached vacancies never carry another persona's ranking or criteria.
- OpenWebNinja JSearch is an optional primary structured source. BetterOption
  sends bounded role/location phrases through `search-v2`, records the actual
  request count and configured per-call estimate, and keeps the returned
  application URL inspectable.
- EURES via a bounded community Apify actor is an optional European source.
  It is disabled without an Apify token, capped per run, separately selectable
  under Account, and recorded in the provider ledger.
- Exa, Brave, You.com, Arbeitnow and configured public ATS boards remain
  available. Role checks, ranking and deduplication apply provider-wide. Raw
  web hits additionally fail closed on phishing, 404, error-landing and
  non-vacancy pages; structured JSearch/EURES links are reverified when the
  user selects them for the archive so anti-bot pages do not erase valid cards.
- The Kitsuno EU source directory is documented as a roadmap input rather than
  silently copied into the runtime because its data licence and per-source
  terms require explicit handling.

## Compass mobility

- Location and mobility has a dedicated optional widget for a nearby station,
  parking place or other coarse public starting point.
- A bounded location suggestion verifies and normalises the place without
  asking for an exact home address.
- Car, transit and bicycle limits use independent five-minute sliders. Untouched
  controls remain neutral; using the widget creates or replaces typed Compass
  facts which Matching already understands.
- Existing guided or typed Compass facts hydrate the widget instead of creating
  a second source of truth. Salary controls keep the same projection principle:
  `0` is neutral, a positive minimum is a boundary, and a separately set target
  is a preference.

## Applications

- A previous full Match remains sufficient for a cover-letter draft when only
  the Compass has changed. Drafting reads the latest confirmed, minimised
  Compass facts at generation time; it does not require a redundant full route,
  salary and company research run.
- A blocked job, a changed/closed source, or an inaccessible source still fails
  closed.
- **Shorter** now aims for about 30 fewer words per click while retaining the
  editable local draft and never submitting anything automatically.

## Provider and legal boundary

- Every new provider is optional, enabled only when configured, account-owned,
  budgeted and visible in Operations. Numeric price fields must contain `0` or
  a real number; `0` means used but unpriced, never free.
- Local testing can evaluate result quality with personal provider keys. Hosted
  use remains closed until the operator has completed the provider contract,
  processor/subprocessor, location, transfer, retention, deletion and incident
  review and has updated the public notice and processing records.
- Public application contacts remain public-job evidence, not permission for
  automated outreach. BetterOption never submits an application automatically.

See [the source review](../providers/job-source-review-v0.7.1r.md) for the provider-specific
engineering and review boundary.

## Release identity

- Application: `0.7.1r-search-mobility`
- Python package: `0.7.1+r.search.mobility`
- Matching algorithm: `matching-v0.7.1o`
- Database head: `0030_verified_job_posters`
- ZIP: `betteroption_v0_7_1r_search_mobility.zip`
- Git tag: `v0.7.1r-search-mobility`

## Operating boundary

Run R only as the password-protected loopback application at
`http://127.0.0.1:8000`. Do not deploy it to a server yet. Use
[the R local backup, install, acceptance and GitHub guide](../local-guides/local-search-mobility-v0.7.1r.md).
