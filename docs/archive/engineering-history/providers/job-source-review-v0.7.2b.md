> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider source review — v0.7.2b

Status: local evaluation only · 4 August 2026

This record supersedes the current operating boundary in the
[v0.7.2a JobsPipe review](job-source-review-v0.7.2a.md) without rewriting that
historical document. It records technical request contracts and open hosted-use
decisions; it is not a legal opinion or a conclusion that source collection is
permitted merely because an actor is sold by another organisation.

## All Jobs Scraper via Apify

- Actor: [`agentx/all-jobs-scraper`](https://apify.com/agentx/all-jobs-scraper)
- Published [input schema](https://apify.com/agentx/all-jobs-scraper/input-schema),
  [output schema](https://apify.com/agentx/all-jobs-scraper/output-schema) and
  [API](https://apify.com/agentx/all-jobs-scraper/api/openapi)
- BetterOption provider/permission: `apify-all-jobs` / `all-jobs`
- One synchronous dataset run, bounded below Apify's 300-second synchronous
  ceiling; `max_results` defaults to 60 per platform and API `maxItems` defaults
  to 300 across the returned dataset
- Required actor input: one bounded role keyword, a full country name and the
  per-platform result maximum
- Optional input: the user-selected coarse location, configured platforms,
  remote-only choice, a 30-day freshness expression and an actor-supported
  distance in miles. BetterOption still applies its own local kilometre radius.
- Output retained: platform, official/platform source link, vacancy identity,
  title, employer, structured location, remote/work model, description, job
  type/level/function/skills, salary evidence and publication date
- Output discarded: email addresses, telephone numbers, social links and other
  contact fields not needed for Explore

When `BETTEROPTION_APIFY_ALL_JOBS_PLATFORMS` is blank, the actor selects all
platforms available for the country. That can include LinkedIn, Indeed,
Glassdoor, Bundesagentur and StepStone in Germany. `official_url` is preferred;
`platform_url` is used only when no official link is present.

The operator-controlled `BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD` is
sent only when greater than zero. Its default `0` means no configured monetary
cap and must not be read as free. The separate estimated-cost value is metadata
for BetterOption's ledger, not an Apify billing control.

## JobsPipe via Apify

- Actor: [`jobspipe/jobspipe-job-search`](https://apify.com/jobspipe/jobspipe-job-search)
- Published [input schema](https://apify.com/jobspipe/jobspipe-job-search/input-schema)
  and [OpenAPI](https://apify.com/jobspipe/jobspipe-job-search/api/openapi)
- Country values are ISO alpha-2. The actor wrapper has no city or radius input;
  nationwide retrieval followed by local distance ranking is therefore the
  intended contract, not a country-detection failure.
- `searchTerms` holds at most three role/title alternatives. Later desired
  terms use `descriptionKeywords`; explicit seniority targets use `seniority`;
  only the documented junior/mid/senior/lead values are sent;
  `postedWithinDays` defaults to 60; `remote` is omitted unless remote-only.
- `maxItems` defaults to 300 in both actor input and API dataset cap.

Direct JobsPipe service APIs expose richer location filters but require a
separate JobsPipe credential. BetterOption does not silently change provider,
recipient or credential contract.

## Other reviewed request contracts

- **OpenWebNinja JSearch:** documented `GET /jsearch/search-v2`, `x-api-key`,
  focused query plus country/language and optional remote-only flag. A comma-
  separated `fields` projection retains every field consumed by the parser.
  Transport phases and the whole provider run are separately bounded.
- **Brave Web Search:** documented Web Search endpoint and
  `X-Subscription-Token`; market/language, metric units, freshness, extra
  snippets and only the available coarse location headers are sent. BetterOption
  does not call Brave Answers.
- **Exa:** documented `/search` with bounded semantic queries, country hint,
  excluded aggregator domains and highlights. The known-good shape is retained.
- **EURES via Apify:** documented country codes, role keywords and 30-result
  bound are retained because the current observed yield is healthy.

## Local activation and hosted gate

All technically configured providers are separate Account choices. New/default
local preference sets enable them, while any explicit saved disable choice
continues to win. A shared Apify token never merges EURES, JobsPipe and All Jobs
into one permission, operation row, label or cost estimate.

Staging and production still require the global processor-review flag. All Jobs
also requires `BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=true`; it remains
greyed out in hosted Account settings without that actor-specific decision.

Before external testers use either scraping actor, the operator still needs
documented decisions on contractual role, DPA/subprocessors/transfers, dataset
retention and deletion, each upstream source's collection/reuse/attribution and
removal terms, lawful basis and notices, quality/freshness/expiry, security and
incident handling, price/cost caps, and an independent disable/rollback path.
