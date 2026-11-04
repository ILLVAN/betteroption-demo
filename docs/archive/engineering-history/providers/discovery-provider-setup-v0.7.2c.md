> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider setup — v0.7.2c

This is the current local request-shape and diagnostics reference. Put
credentials only in the untracked `.env`, restart the app, run the diagnostics,
and confirm each independent choice under **Account → Provider choices**.

## Complete-run behavior

```dotenv
BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true
BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=390
BETTEROPTION_DISCOVERY_AVAILABILITY_BUDGET_SECONDS=35
BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS=120
```

Every configured and Account-enabled source starts in the concurrent source
phase. A normal all-provider workflow may take five to seven minutes and stores
at most 300 ranked cards. Returned and visible counts legitimately differ after
source policy, location/work-arrangement checks, URL deduplication, seniority
tail handling and final ranking.

The Explore distance slider is a client-side view over that completed result
set. It spends no provider call, filters only known-distance non-remote jobs,
and leaves remote jobs to the remote/work-arrangement controls. Straight-line
distance is an offline ranking estimate; exact routes begin only in Match.

## OpenWebNinja JSearch

Use a direct OpenWebNinja JSearch key, not a RapidAPI key:

```dotenv
OPENWEBNINJA_JSEARCH_API_KEY=
BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS=3
BETTEROPTION_OPENWEBNINJA_JSEARCH_CONNECT_TIMEOUT_SECONDS=10
BETTEROPTION_OPENWEBNINJA_JSEARCH_READ_TIMEOUT_SECONDS=90
BETTEROPTION_OPENWEBNINJA_JSEARCH_SEARCH_BUDGET_SECONDS=120
```

BetterOption calls the documented
[`GET /jsearch/search-v2`](https://www.openwebninja.com/api/jsearch) endpoint
with `x-api-key`. Each focused request sends the role and location in `query`,
plus a resolved `country`/`language` and `work_from_home=true` only when
applicable. It deliberately sends neither `fields` nor `num_pages`: neither is
part of the current canonical v2 example, and v2 continuation uses a cursor
rather than the old page-count shape.

An HTTP request error stops later synonym requests for that provider run;
earlier successful rows remain usable. The provider deadline can also stop
before the configured maximum. No query, URL, response body or key enters the
operation ledger or diagnostics.

Check configuration without a request, then explicitly spend one fixed probe:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

The live probe is still required for owner acceptance because authentication,
plan and live-provider behavior cannot be proven without the owner's key. Its
fixed Berlin software-developer request may wait up to the configured read
window and reports one specific secret-safe category.

## Apify actors

One Apify token authenticates three adapters, but they remain separate
providers, permissions, actor runs, estimates, operation rows and result labels:

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

The
[`benthepythondev/eures-jobs-scraper`](https://apify.com/benthepythondev/eures-jobs-scraper)
actor keeps its known-good bounded role, ISO-country and 30-result contract. It
has no city filter; BetterOption resolves and ranks its location evidence
locally.

### JobsPipe

The
[`jobspipe/jobspipe-job-search`](https://apify.com/jobspipe/jobspipe-job-search)
actor documents OR behavior within one filter list and AND behavior between
different filter groups. `v0.7.2c` therefore makes up to four independent small
actor runs. A run contains either one concise `searchTerms` keyword or one
`descriptionKeywords` keyword—never both. Country-scoped role/skill requests
are complemented by one bounded country-free role request for useful nearby
cross-border roles.

The aggregate returned limit is 300. Calls run inside one provider-wide time
bound, then IDs and URLs are deduplicated before shared relevance/distance
ranking. JobsPipe's Apify wrapper supports countries but no city/radius;
nationwide or cross-border retrieval is therefore intentional. `remote` is
sent only for remote-only searches, and `postedWithinDays` remains 60.

Each actor run is independently billable. Configure its per-run estimate and
interpret the Operations unit count accordingly; four HTTP/actor runs are not
one free logical search.

### All Jobs Scraper

The
[`agentx/all-jobs-scraper`](https://apify.com/agentx/all-jobs-scraper) adapter
uses Apify's asynchronous control flow:

1. start exactly one actor run;
2. wait briefly and poll that same run by its sanitized run ID;
3. fetch the associated dataset by its sanitized dataset ID;
4. use bounded completed or available partial rows, or report an attributed
   provider failure.

It never starts a second paid actor run automatically after a timeout. Poll and
dataset HTTP requests are control-plane operations around one billed actor run;
they must not be priced as additional actor starts.

`max_results` remains a per-platform actor limit. On Apify's asynchronous
`/runs` endpoint, `maxItems=300` limits charged pay-per-result dataset items; it
does **not** guarantee that the actor writes no additional rows. BetterOption
separately asks the dataset endpoint for at most 300 rows and stops parsing at
that limit. Leave `PLATFORMS` blank to use the country-supported set. A positive
`MAX_TOTAL_CHARGE_USD` is an Apify billing guard; zero means no configured
monetary cap, not free. Only vacancy/company/location/salary/source fields are
retained; contact email, telephone and social enrichment are discarded.

An `AllJobsUnavailableError` after a very slow run can represent an Apify or
upstream-platform incident rather than a bad query. Inspect the Apify run and
[platform status](https://status.apify.com/) before changing the input or
starting another charged run.

## Brave Web Search

Use a key from an active Brave **Search** plan; BetterOption does not call
Brave Answers:

```dotenv
BRAVE_SEARCH_API_KEY=
```

BetterOption uses the documented
[Web Search endpoint](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)
and `X-Subscription-Token`.

- `search_lang` is inferred from each generated German or English role query,
  while `ui_lang` remains an appropriate market interface locale.
- `extra_snippets=true` is requested and those snippets are consumed in job
  plausibility and the displayed summary.
- page two is requested only when the first focused query says
  `query.more_results_available=true`.
- no `freshness=pm` is sent: Brave defines that as web-index freshness, not a
  trustworthy job-posting date.
- a resolved non-worldwide origin can add only rounded coarse location headers;
  no home address or invented state/postcode is sent.

Run the payload-free one-request access probe with:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
```

## Exa, You.com, Arbeitnow and ATS sources

- **Exa** keeps the productive bounded semantic role/location queries, country
  hint, highlights and raw-aggregator exclusions.
- **You.com Search** uses one bounded raw-web request through `YDC_API_KEY`.
- **Arbeitnow** is keyless and scans cached feed pages.
- Configured Greenhouse, Lever and Ashby boards use their public board APIs in
  the ATS expansion phase.

Structured JSearch, JobsPipe and All Jobs rows can legitimately point to major
job boards. Raw web-search rows from excluded aggregator domains remain subject
to the stricter source-plausibility policy.

## Operations interpretation

The Operations **Today by provider** row aggregates every attempt since 00:00
UTC. A displayed combination such as `JSearchRequestError,
JSearchTimeoutError, JSearchUnavailableError` can therefore include older runs
from the same day. Use Explore's **What the last source run contributed** for
the exact latest workflow.

Provider estimate fields populate a payload-free ledger. Enter the current
contract unit and price from invoices or dashboards. A zero estimate means
unpriced, not free; failed billed actor starts belong in the measurement.

## Fantastic.jobs decision

`v0.7.2c` has no Fantastic.jobs credential, adapter, scheduled import or normal
Explore call. Its trial may be used only as a manual, separately recorded,
bounded benchmark during the `v0.7.3` cost exercise. Recheck current limits and
pricing immediately before that benchmark; do not silently turn a trial into a
runtime dependency.

## Hosted boundary

Local technical availability is not hosted permission. Staging/production
still requires `BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=true`, and All Jobs
also requires `BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=true`. Review the
current [source record](job-source-review-v0.7.2c.md), provider contracts and
the compliance launch gates before changing either switch.
