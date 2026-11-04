> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider source review — v0.7.2c

Status: local evaluation only · 4 August 2026

This record supersedes the current operating boundary in the
[v0.7.2b review](job-source-review-v0.7.2b.md) without rewriting that historical
document. It records request contracts and open hosted-use decisions; it is not
legal advice. Purchasing an intermediary's scraper or dataset does not by
itself transfer every contractual, privacy or source-right responsibility to
that intermediary.

## OpenWebNinja JSearch

- Product: [OpenWebNinja JSearch](https://www.openwebninja.com/api/jsearch)
- BetterOption provider: `openwebninja-jsearch`
- Authentication: direct OpenWebNinja key in the `x-api-key` header
- Current request: `GET /jsearch/search-v2` with `query`, optional resolved
  `country`/`language`, and optional `work_from_home`
- Removed request parameters: `fields` and `num_pages`; the current v2
  interface is cursor-based, and these undocumented parameters were the
  request-shape delta correlated with the recent live 4xx response. A fresh
  owner probe is required before assigning causality.
- Data retained: public vacancy identity, title, employer, location/work model,
  description/tags, salary and publication/source evidence consumed by Explore
- Data not stored in provider telemetry: query, location, URL, response body or
  key

Offline contract tests cannot prove a specific account's live authentication,
plan, quota or current provider behavior. One explicit synthetic owner-key probe
remains a release-acceptance requirement.

## JobsPipe via Apify

- Actor:
  [`jobspipe/jobspipe-job-search`](https://apify.com/jobspipe/jobspipe-job-search)
- Published
  [input schema](https://apify.com/jobspipe/jobspipe-job-search/input-schema)
  and [OpenAPI](https://apify.com/jobspipe/jobspipe-job-search/api/openapi)
- BetterOption provider/permission: `apify-jobspipe` / `jobspipe`
- Up to four independent actor runs, each with exactly one OR-filter group:
  one keyword in `searchTerms` or one in `descriptionKeywords`
- Country-scoped requests plus one bounded country-free role request; no city
  or radius exists in the wrapper, so local relevance/distance ranking owns the
  final order
- Aggregate BetterOption return cap: 300 after ID/URL deduplication

The previous request put title and description filters together, making the
groups an AND constraint and suppressing broad useful results. More small actor
runs can improve recall but also multiply billed runs; cost records and daily/
workflow caps must use the real run count.

## All Jobs Scraper via Apify

- Actor: [`agentx/all-jobs-scraper`](https://apify.com/agentx/all-jobs-scraper)
- Published
  [input schema](https://apify.com/agentx/all-jobs-scraper/input-schema),
  [output schema](https://apify.com/agentx/all-jobs-scraper/output-schema) and
  [API](https://apify.com/agentx/all-jobs-scraper/api/openapi)
- BetterOption provider/permission: `apify-all-jobs` / `all-jobs`
- Exactly one asynchronous paid run start; bounded waits/polls address that run;
  its dataset is fetched separately; no automatic paid rerun after a timeout
- `max_results` is per selected platform; async-run `maxItems` limits charged
  pay-per-result dataset items but does not guarantee the actor writes only
  that many rows; BetterOption's separate dataset GET/parser limit caps rows
  consumed at 300
- Output retained: platform/source, vacancy identity, title, employer,
  structured location/work model, description/skills, salary and publication
  evidence
- Output discarded: email, telephone, social and other contact enrichment

The observed 266.9-second `AllJobsUnavailableError` occurred during a visible
Apify platform issue. That is consistent with temporary platform/upstream
unavailability and does not prove a malformed request. Keep it as a failed
billable run in cost/reliability measurement, inspect
[Apify status](https://status.apify.com/) and the existing run, and never hide
it with an automatic second actor start.

## Brave Web Search

- Product: Brave Web Search, not Brave Answers
- Contract:
  [Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)
  with `X-Subscription-Token`
- Query language follows the generated German/English role query; market UI
  locale and rounded coarse location hints remain separate
- `extra_snippets` are consumed as candidate evidence
- page two is conditional on `query.more_results_available`
- the prior `freshness=pm` parameter is removed because it represents indexed
  webpage freshness, not verified vacancy publication recency

Brave rows remain untrusted web candidates and pass the common URL,
plausibility, availability and deduplication policy before Explore. Low yield is
therefore not repaired by weakening the source-safety boundary.

## Stable providers

- **Exa:** documented `/search` with bounded semantic queries, country hint,
  highlights and excluded raw-aggregator domains; known-good behavior retained.
- **EURES via Apify:** bounded role keyword, ISO country and 30-result contract;
  known-good behavior retained.
- **You.com, Arbeitnow and configured ATS boards:** existing contracts and
  common source policy retained.

## Fantastic.jobs

Fantastic.jobs is not a `v0.7.2c` recipient or processor: BetterOption has no
runtime credential, adapter, background ingestion or scheduled API call. The
observed seven-day/50-request/500-job trial and fixed paid entry tier make it a
manual benchmark candidate only. Any later integration requires a fresh
contract, pricing, DPA/subprocessor/transfer, retention/deletion, attribution/
removal and marginal-yield decision.

## Local activation and hosted gate

Every technically configured provider is a separate Account choice. One shared
Apify credential does not merge EURES, JobsPipe and All Jobs into one recipient,
operation row, permission or cost estimate.

Staging and production still require the global processor-review flag. All Jobs
also requires `BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=true`; without that
actor-specific decision it stays unavailable in hosted Account settings.

Before friend invitations, document for the exact enabled bundle:

- contractual role, current plan, DPA, subprocessors and transfers;
- each upstream source's access/reuse/attribution/removal conditions;
- lawful basis, notices, minimisation, retention and provider-side deletion;
- quality, freshness, expired-job removal and incident handling;
- measured price, failure billing, hard budget caps and independent disable;
- an owner-approved launch record. Close friendship and low traffic do not
  remove these gates.
