> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Job-source review for v0.7.1r

Reviewed 3 August 2026. This is an engineering integration record, not a
substitute for the operator's contract/DPA and transfer assessment before a
hosted release.

## OpenWebNinja JSearch: integrated as an optional source

Primary documentation:

- <https://www.openwebninja.com/api/jsearch>

The documented `search-v2` endpoint accepts a job query and an `X-API-Key`
header. Its structured result includes the job title, employer, publisher,
description, location, posting time, application links, and whether the role is
remote. The provider advertises results sourced from public job sites and job
aggregators, including LinkedIn, Indeed, Glassdoor and ZipRecruiter.

BetterOption's adapter:

- is absent unless `OPENWEBNINJA_JSEARCH_API_KEY` is configured;
- sends only a bounded role/location search phrase;
- uses the documented country/language context for recognised local markets and
  the documented work-from-home filter for remote-only searches;
- never puts the key in a URL, ledger row, result, or error message;
- prefers a direct employer application option when the response provides one;
- records the number of attempted HTTP requests and applies the configured
  per-call estimate;
- is enabled by default when technically available, but remains controllable
  under Account provider choices;
- remains closed in staging/production until processor review is marked
  complete.

JSearch and EURES are treated as structured active-corpus sources rather than
generic web-search hits. Their source links still pass BetterOption's domain,
role-evidence, deduplication and ranking rules, and a selected job is verified
again when it enters the archive. BetterOption does not run the generic
fail-closed HTML checker over every structured result: LinkedIn, Glassdoor and
EURES pages commonly return robots or anti-bot responses to server-side clients
even when the candidate-facing page is live. Exa, You.com and Brave raw web
links do receive that stricter individual-job/body/error-landing check. A
JSearch or EURES card is therefore inspectable provider evidence, not a promise
that an external vacancy cannot close between discovery and selection.

The public pricing page currently describes Free, Pro, Ultra, Mega and pay-as-
you-go plans. Prices and quotas can change, so BetterOption does not hardcode
them. `BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD=0` means
unpriced/unknown, not free. Set the installation's current effective marginal
price when cost calibration begins.

## EURES via the community Apify actor: integrated for a bounded local trial

Reviewed actor/API page:

- <https://apify.com/benthepythondev/eures-jobs-scraper/api>

The actor calls the public EURES service and can return structured European
vacancies with employer, location, contract, dates, description and public
application contacts. BetterOption now exposes it as the optional
`apify-eures` provider for a bounded local quality trial:

- one actor-run request per Explore run, capped at 30 returned rows;
- the Apify token is sent only in the `Authorization` header and is never put in
  the URL, request body, ledger row, result or operator-facing error;
- the canonical EURES vacancy URL is preferred and public application/contact
  details are kept bounded;
- the operation ledger records one actor run plus the returned result count;
- `BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD` is operator supplied;
  numeric `0` means unpriced/unknown, not free;
- the provider is independently controllable under Account provider choices;
- staging/production use remains closed until processor review is marked
  complete.

This is still a community-maintained Apify actor rather than an official EURES
API integration. At review time it was new and lightly used and introduced a
separate Apify processor relationship. Before enabling it in a hosted alpha,
complete and record:

1. Apify and actor terms, DPA/subprocessors, processing locations and deletion;
2. actor maintenance/stability and output-contract tests;
3. EURES source/reuse and attribution obligations;
4. cost per useful, still-open, non-duplicate vacancy;
5. whether a maintained direct official interface can replace the actor.

The local adapter is therefore an evaluation path, not a declaration that the
actor or processor has passed production legal/commercial review.

## Kitsuno Agentic Job Search EU: source roadmap, not a runtime API

Reviewed project and directory description:

- <https://github.com/kitsuno-ai/agentic-job-search-eu>
- <https://kitsuno.ai/content/en/open-source-eu-job-sources/>

Kitsuno publishes a machine-readable directory of European job sources plus
health/yield observations. It is valuable for deciding which direct feeds to
build next; it is not itself a hosted job-search endpoint. BetterOption already
implements several of its low-friction source families (Arbeitnow and public
Greenhouse, Lever and Ashby boards).

The repository documents dual licensing: directory/statistics data under
CC-BY-SA 4.0 and tools/examples/schema under MIT. BetterOption therefore does
not silently vendor the directory. A later importer needs explicit attribution,
share-alike handling, version/update provenance, and per-source terms review.
For v0.7.1r it remains an evidence-backed provider backlog rather than another
unaccounted external call.
