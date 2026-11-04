> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2c

`v0.7.2c` is an Explore-quality and Compass-clarity release. It changes the
matching identity to `matching-v0.7.2c` because salary requirements now carry
an explicit currency, but it does not add a database migration.

## Explore controls and result cards

- Explore has a live **maximum distance** slider from 25 to 1,000 km. The
  1,000 km endpoint means **Any distance**. Changing it filters the already
  returned cards immediately and does not spend another provider request.
- The distance limit applies only to non-remote jobs with a known straight-line
  distance. Remote jobs remain governed by the existing remote/work-arrangement
  filters, and jobs without a reliable distance remain visible rather than
  receiving invented precision.
- A card now starts with one compact metadata line for selection, provider,
  employer and location. The job title occupies its own line in the current
  sans-serif product typeface. Longer employer names can wrap and expose their
  complete value instead of being truncated beside the title.
- The Operations daily provider table now explains that its failure categories
  aggregate all operations since 00:00 UTC. The exact current search remains
  visible in Explore's **What the last source run contributed** disclosure.

## Provider request repairs

### OpenWebNinja JSearch

- BetterOption still uses the direct OpenWebNinja
  [`GET /jsearch/search-v2`](https://www.openwebninja.com/api/jsearch) endpoint
  and `x-api-key` authentication.
- The request now follows the current minimal contract: `query`, optional
  country/language and optional `work_from_home`. The undocumented `fields` and
  `num_pages` parameters are no longer sent; they were the request-shape delta
  correlated with the recent live HTTP 4xx response, but owner live acceptance
  is still required before claiming causality. The cursor-based v2 interface is
  not confused with old page-count pagination.
- A request error stops later synonym variants while preserving an earlier
  successful partial result. Timeout, plan, rate, transport and request
  failures remain separate, fixed-text and secret-safe.
- The offline suite proves the request shape. Owner acceptance still requires
  the explicit one-request live probe because the release process does not have
  access to the owner's key or plan.

### JobsPipe via Apify

- One over-constrained actor input has been replaced by up to four small,
  independent actor runs. Each run sends one documented OR-filter group—either
  `searchTerms` or `descriptionKeywords`—and never combines both as an
  accidental AND condition.
- The run set uses concise one-keyword role/skill searches, country-scoped
  variants and one bounded country-free role variant. This allows a strong
  nearby cross-border job to compete without making every result worldwide.
- Runs share a provider-wide time bound and a 300-candidate aggregate cap.
  IDs/URLs are deduplicated before the normal relevance and straight-line
  distance ranking. Each actor run is still a separately billable operation.

### All Jobs Scraper via Apify

- BetterOption now starts one asynchronous AgentX actor run, polls that same run
  within the Explore budget and fetches its dataset by ID. A transient timeout
  never starts an automatic second paid run.
- A completed or available partial dataset can be used; a run without usable
  rows remains an attributed `AllJobsUnavailableError`. This makes a slow Apify
  incident distinguishable from a rejected request.
- On the asynchronous start, Apify's `maxItems` limits pay-per-result charging;
  it does not promise that the actor writes no additional rows. BetterOption's
  separate dataset-fetch and parsing limit bounds consumed rows to 300.
- Actor, result and cost limits remain separate from EURES and JobsPipe.

### Brave Web Search

- `search_lang` now follows the generated query language instead of assuming
  that every role query uses the location's language.
- The requested `extra_snippets` are included in plausibility checks and result
  summaries rather than discarded.
- A second page is requested only when Brave's
  `query.more_results_available` signal is true. The former one-month webpage
  index-freshness restriction is removed because it is not a reliable job
  publication-date filter.

Exa and EURES keep their already productive request shapes.

## Compass salary currency

- The annual gross salary tile has a compact selector for 39 supported ISO
  currencies. New and legacy profiles default to EUR.
- Saved salary requirements include the ISO currency, for example
  `CHF 65000`, so a bare number no longer loses its unit.
- Deterministic numeric salary comparisons run only when profile and vacancy
  currencies match. BetterOption does not invent a static foreign-exchange
  conversion; a different or missing currency remains explicit Unknown.
- Currency-free legacy salary facts remain readable as EUR for compatibility.

The optional Programming languages tile is also smaller and visually quieter.

## Product and cost decision

Fantastic.jobs is deliberately not a runtime provider in this release. Its
short trial and fixed paid entry tier make it a candidate for one manual,
bounded marginal-yield benchmark during the `v0.7.3` cost checkpoint—not for a
credential, background importer or normal Explore fan-out today. See the
[cost and business-plan checkpoint](../../discontinued-product-planning/cost-and-business-plan.md).

## Identity and compatibility

- Application and source release: `0.7.2c`
- Python package metadata: PEP 440 may display `0.7.2rc0`
- Matching algorithm: `matching-v0.7.2c`
- Database migration head: unchanged at `0030_verified_job_posters`
- Release archive: `betteroption_v0_7_2c.zip`
- Git tag: `v0.7.2c`

Existing accounts, personas, jobs, application history and database rows remain
compatible. Existing results under `matching-v0.7.2` are intentionally marked
for recalculation because currency-aware matching has a new algorithm identity.

Use the [local release guide](../local-guides/local-v0.7.2c.md) for the exact backup,
installation, test, acceptance, dump and Git commands; the
[provider setup](../providers/discovery-provider-setup-v0.7.2c.md) and
[source review](../providers/job-source-review-v0.7.2c.md) define the current request and
hosted-use boundaries.
