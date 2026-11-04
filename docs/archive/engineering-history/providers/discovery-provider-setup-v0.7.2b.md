> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider setup — v0.7.2b

This is the current local setup and request-shape reference. Add credentials
only to the untracked `.env`, restart the app, run `diagnose_config.py`, and
then confirm the separate choices under **Account → Provider choices**.

## Complete-run behavior

```dotenv
BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true
BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=390
BETTEROPTION_DISCOVERY_AVAILABILITY_BUDGET_SECONDS=35
BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS=120
```

Every configured and Account-enabled source starts concurrently. The primary
source phase is capped at 300 seconds, actor requests at 285 seconds, JSearch at
120 seconds, and the complete stored task at 390 seconds. A normal all-provider
run may therefore take five to seven minutes. Set `CALL_ALL_PROVIDERS=false`
only when deliberately restoring the older conditional Brave/You fallback.

Explore stores at most 300 ranked cards. A provider's returned count can be
larger than its visible count after role/work-arrangement policy, URL
deduplication, seniority-tail handling and final ordering. Distance is an
offline straight-line ranking estimate; exact route calls begin only in Match.
Standalone ISO codes, English/German country names and bare German postcodes
are normalized offline before structured-provider requests.

## OpenWebNinja JSearch

Create a direct OpenWebNinja JSearch key, not a RapidAPI key:

```dotenv
OPENWEBNINJA_JSEARCH_API_KEY=
BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS=3
BETTEROPTION_OPENWEBNINJA_JSEARCH_CONNECT_TIMEOUT_SECONDS=10
BETTEROPTION_OPENWEBNINJA_JSEARCH_READ_TIMEOUT_SECONDS=90
BETTEROPTION_OPENWEBNINJA_JSEARCH_SEARCH_BUDGET_SECONDS=120
```

BetterOption calls the documented
[`GET /jsearch/search-v2`](https://www.openwebninja.com/api/jsearch) endpoint
with `x-api-key`. The role and location stay in `query`; a resolved market adds
`country` and `language`; `work_from_home=true` is sent only for remote-only.
`num_pages=1` and one comma-separated `fields` projection keep each response
bounded. Six configured variants remain a maximum, not a promise: a provider-
wide timeout or deadline stops the fan-out.

Check without a request, then explicitly spend one synthetic request:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

The live probe uses a fixed Berlin/de software-developer query and may wait up
to the configured read window. It distinguishes connect, read, write and pool
timeouts plus DNS, TLS, proxy, authentication, plan, rate-limit, request,
response and provider failures. It prints no key, query, URL or response body.

## Apify actors

One Apify token can authenticate three adapters, but they remain independent
providers, permissions, actor runs, cost estimates and operation rows:

```dotenv
APIFY_API_TOKEN=
BETTEROPTION_APIFY_EURES_MAX_RESULTS=30
BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=300
BETTEROPTION_APIFY_JOBSPIPE_POSTED_WITHIN_DAYS=60
BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=60
BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=300
BETTEROPTION_APIFY_ALL_JOBS_POSTED_SINCE=30 days
BETTEROPTION_APIFY_ALL_JOBS_PLATFORMS=
BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0
BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=false
```

### EURES

The [`benthepythondev/eures-jobs-scraper`](https://apify.com/benthepythondev/eures-jobs-scraper)
actor receives bounded role keywords, ISO country codes and 30 results. It has
no city filter; EURES/NUTS location evidence is resolved and ranked locally.
The currently successful request shape is unchanged.

### JobsPipe

The [`jobspipe/jobspipe-job-search`](https://apify.com/jobspipe/jobspipe-job-search)
actor receives at most three role/title alternatives in `searchTerms`, later
Compass terms in `descriptionKeywords`, ISO alpha-2 countries, explicit
junior/mid/senior/lead values, a 60-day freshness window and up to 300 items.
Intern/manager values are omitted because the actor does not document them;
`remote` is omitted unless the search is remote-only.

The Apify wrapper exposes country but no city or radius. German results are
therefore nationwide by design and get their role/distance order locally.
Direct JobsPipe APIs have other filters but require a separate JobsPipe key;
BetterOption does not silently switch recipients or credentials.

### All Jobs Scraper

The [`agentx/all-jobs-scraper`](https://apify.com/agentx/all-jobs-scraper)
actor receives one focused role keyword, the full country name, the selected
coarse location, freshness and optional remote/radius/platform choices.
`max_results=60` applies per platform, while API `maxItems=300` is the complete
returned-dataset cap. Leave `PLATFORMS` blank to use every platform available
for the country, including local boards where supported. A positive
`MAX_TOTAL_CHARGE_USD` adds an Apify billing guard; zero means no configured
monetary cap, not free.

BetterOption prefers the actor's `official_url`, then `platform_url`. It maps
vacancy/company/location/salary evidence but deliberately discards returned
email, telephone and social-contact fields.

## Brave Web Search

Use a key from an active Brave **Search** plan. Brave Answers is a different
product and is not called:

```dotenv
BRAVE_SEARCH_API_KEY=
```

BetterOption uses Brave's documented
[Web Search endpoint](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)
and `X-Subscription-Token`. Focused German/English job queries add the resolved
search market, `search_lang`, `ui_lang`, metric units, one-month freshness,
strict safe search and extra snippets. When a non-worldwide location resolves
offline, only rounded latitude/longitude, country, city and a genuinely known
postcode are added as `X-Loc-*` headers. No state or home address is invented.

## Exa, You.com and ATS sources

- **Exa** uses the documented `/search` endpoint, bounded semantic role/location
  queries, country hint, highlights and exclusions for raw aggregator domains.
  Its known-good v0.7.2 request shape remains stable.
- **You.com Search** uses one bounded raw-web request through `YDC_API_KEY`.
  Its results pass the same raw-web URL/plausibility and availability policy as
  Brave and Exa.
- **Arbeitnow** is keyless and scans up to 30 cached feed pages.
- Configured Greenhouse, Lever and Ashby boards use their public board APIs in
  the later ATS expansion phase.

Structured JSearch/JobsPipe/All Jobs rows may legitimately point to LinkedIn,
Indeed, Glassdoor, StepStone or Xing. Raw web-search rows from those domains
remain excluded because a search snippet alone is not structured job evidence.

## Hosted boundary and costs

Local evaluation makes configured providers available. Staging/production
still requires `BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=true`; All Jobs also
requires its own `HOSTED_ENABLED=true`. Review the current
[source record](job-source-review-v0.7.2b.md) before changing either flag.

All `*_ESTIMATED_COST_*` settings feed only the secret-safe local ledger. Enter
current contract prices yourself. `0` means unpriced, never free. Account
choices and daily/workflow operation and cost rails can always narrow calls.
