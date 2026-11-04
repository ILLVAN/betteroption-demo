> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2b

`v0.7.2b` is a local Explore retrieval and reliability update. It preserves
the `matching-v0.7.2` scoring model and current database head while widening
the candidate pool, calling every configured source, and repairing two filters
that hid valid structured aggregator results.

## Explore sources and result pool

- **All Jobs Scraper via Apify** is a distinct optional provider backed by the
  AgentX `all-jobs-scraper` actor. It has its own Account permission, provider
  ID (`apify-all-jobs`), operation rows, cost estimate, result caps and labels.
- AgentX receives one focused role keyword, the user-selected search location,
  an offline-resolved full country name, optional remote/radius/freshness fields
  and bounded platform settings. The API-level `maxItems=300` guard caps the
  complete returned dataset even though the actor's `max_results` is per
  platform. Contact details in actor output are deliberately discarded.
- Every configured and Account-enabled Explore provider now starts in the same
  concurrent source phase by default, including Brave and You.com. The former
  conditional fallback policy remains available through
  `BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=false`.
- Explore accepts up to 300 final ranked candidates and allows a 390-second
  shared source budget. The stored background task and progress UI explicitly
  explain that a complete run can take five to seven minutes.
- LinkedIn, Indeed, Glassdoor, StepStone and Xing links remain excluded when
  they are unverified raw web-search rows. The same domains are no longer
  discarded when a structured JSearch, JobsPipe or All Jobs adapter returned a
  validated job record.
- URL deduplication keeps stable job identity parameters such as Indeed's `jk`
  while continuing to remove tracking parameters.
- Standalone ISO codes, English/German country names and bare German postcodes
  now resolve to a provider market for JobsPipe, All Jobs and JSearch instead
  of silently producing worldwide or US-default requests.

## JobsPipe request quality

- JobsPipe now requests up to 300 recent candidates. The actor receives at
  most three role/title alternatives in `searchTerms`; later Compass terms use
  its separate `descriptionKeywords` field, and explicit seniority targets use
  the documented `seniority` field for junior/mid/senior/lead. Unsupported
  intern/manager values are omitted rather than creating an empty AND filter.
- `remote` is sent only for a remote-only search. The default freshness window
  is 60 days. JobsPipe exposes country but no city/radius filter, so it remains
  a nationwide source whose location and distance are ranked locally.
- The API input limit and returned-dataset limit are both bounded. Ranking and
  distance ordering are unchanged; the larger pool prevents 150 higher-ranked
  rows from eliminating an otherwise useful JobsPipe tail before final order.

## JSearch reliability

- The documented OpenWebNinja direct endpoint, `x-api-key` authentication,
  country/language/location request shape and supported response envelopes are
  retained.
- The former scalar 20-second timeout is replaced by phase-specific connect,
  pool, write and 90-second read limits. The diagnostic uses the same contract.
- A whole-provider deadline prevents six sequential focused searches and their
  retries from outliving Explore. Read timeouts are not blindly retried, and a
  bounded `fields` projection avoids downloading unused parts of the large job
  schema.
- Timeout and deadline failures remain fixed-text and secret-safe; queries,
  request URLs, response bodies and keys are not stored or printed.

## Brave and stable providers

- Brave keeps its documented Web Search endpoint and Search-plan header while
  adding market language, UI locale, metric units, extra snippets and bounded
  location headers from the already user-selected Explore origin.
- Exa and EURES request contracts remain deliberately stable because their
  observed contribution was already healthy. Their current official contracts
  were rechecked as part of this release.

## Identity and compatibility

- Application and package: `0.7.2b`
- Matching algorithm: unchanged at `matching-v0.7.2`
- Database migration head: unchanged at `0030_verified_job_posters`
- Release archive: `betteroption_v0_7_2b.zip`
- Git tag: `v0.7.2b`

Existing databases, accounts, personas, Compass evidence, jobs, matches,
ratings and application history remain compatible. Existing explicit Account
provider choices remain authoritative. Locally available providers default on
for new/default preference sets; hosted All Jobs remains separately disabled
until both its actor-specific switch and the processor review are complete.

See the [local release guide](../local-guides/local-v0.7.2b.md) for backup, installation,
diagnostics, testing, dump creation and Git publication, and the
[source review](../providers/job-source-review-v0.7.2b.md) for the exact provider boundary.
