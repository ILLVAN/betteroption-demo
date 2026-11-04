> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider source review — v0.7.2d

## Decision rule

Providers retrieve candidates; they do not receive a ranking privilege. The
bounded local result set is decided from:

1. evidence of the requested role and desired content;
2. Compass relevance, including seniority and explicit exclusions;
3. resolved proximity and the selected maximum distance;
4. a valid known posting date;
5. completeness of company, location and summary evidence;
6. source policy, availability checks and URL deduplication.

Freshness contributes only +2/0/-4 points and cannot rescue an irrelevant role; distance is not
allowed to hide remote or unresolved-location jobs. Explicit exclusion matches
both display a warning and materially reduce the Explore score. The provider
name is absent from the sort key.

For duplicate canonical URLs, the richer record can replace the first record.
This is an evidence-quality choice, not a preference for Brave, Exa, JSearch,
Apify or any other brand.

## Current source behavior

| Source | Retrieval role | Current boundary |
|---|---|---|
| Arbeitnow | Keyless recent feed | Bounded pages and local ranking |
| Brave Search | Broad public-web candidates | Search-plan key; candidate URLs remain subject to source policy |
| Exa | Semantic public-web candidates | Independent focused queries; no fallback ranking bonus |
| You.com Search | Public-web candidates | One bounded search; local parsing and ranking |
| OpenWebNinja JSearch | Structured job results | Up to three focused requests under one provider deadline |
| EURES via Apify | European structured vacancies | One bounded actor result set |
| JobsPipe via Apify | Broad structured aggregation | Up to four short keyword actor runs, then local comparison |
| All Jobs via Apify | Multi-board aggregation | One paid actor run; bounded polling and total dataset cap |
| Greenhouse, Lever, Ashby | Configured public ATS boards | Explicit board list and local ranking |

All configured and account-enabled sources may start concurrently. Provider
budgets, permissions, operation IDs and estimated costs remain separate even
though ranking is shared.

## JSearch acceptance state

The owner-controlled `diagnose_jsearch.py --live` probe reached the official
`search-v2` endpoint and parsed ten results. This closes transport,
authentication, request-schema and response-parser uncertainty for that probe.
It does not prove that every Compass query will contribute a final row.

`v0.7.2d` maps overly terse concepts to a bounded occupation phrase before
searching and resolves compound German location labels to a country code where
possible. The Explore source panel must still report the observed result:

> Found N usable job(s); M contributed to these ranked results.

Zero contribution is valid when another source has the stronger duplicate, a
candidate violates source policy or it falls outside the bounded final set.

Official API overview: <https://www.openwebninja.com/api/jsearch>
