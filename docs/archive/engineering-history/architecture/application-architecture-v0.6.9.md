> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.9

## Outcome

v0.6.9 adds a bounded Discovery Source Mesh without moving trust decisions into
search providers. Explore produces source-attributed candidates. Archive remains
the first trusted boundary: a selected URL must pass URL safety, redirect,
robots, reachability, useful-content, and extraction checks before it becomes a
stored job.

## Discovery flow

```text
Compass or manual query
        |
        v
Primary discovery
  - Arbeitnow public feed
  - Brave Search API when configured
        |
        v
ATS expansion
  - configured Greenhouse boards
  - configured global/EU Lever sites
  - configured Ashby boards
  - boards detected from traceable ATS candidate URLs
        |
        v
Deduplicate + approximate location/role/seniority ranking
        |
        +-- enough candidates --> Explore
        |
        +-- below configured floor --> Exa API fallback when configured
                                      |
                                      v
                              second ATS expansion
                                      |
                                      v
                                   Explore
```

The Exa path is conditional by construction. It does not run merely because a
key exists. `BETTEROPTION_EXA_FALLBACK_MIN_RESULTS` controls the floor, with 15
as the private-alpha default.

## Source contracts

- Greenhouse uses the documented public Job Board API.
- Lever uses the documented Postings API and keeps global and EU hosts explicit.
- Ashby uses the documented public Job Postings API.
- Brave and Exa return discovery candidates, never evidence that can directly
  decide a match.
- Restricted aggregators remain excluded. No connector bypasses authentication,
  anti-bot controls, robots policy, or application workflows.

Configured boards use semicolon-separated `Company=token` values. This explicit
mapping prevents an ATS token from silently becoming an employer identity.

## Candidate and evidence boundaries

`DiscoveredJob` contains the provider, provider identifier, title, employer
label, location label, tags, summary, source URL, and approximate rank metadata.
It is deliberately not a `JobPosting`. Candidate prose can be incomplete or
wrong. Only the existing ingestion and extraction flow may create advertisement
evidence.

Explore uses only approximate geography. Exact public-transport, road, bicycle,
or walking routes remain a Matching operation and apply equally to all 25 alpha
slots.

## Generic mobility safeguard

The bundled postcode and city indexes remain first choice. If an endpoint such
as a district or street cannot be resolved locally, the privacy-first Valhalla
path may use a configured Nominatim resolver. The resolver:

- is generic and Europe-capable rather than backed by place-specific aliases;
- sends only the unresolved endpoint label;
- requires the returned locality to match the meaningful query tokens;
- rejects wrong-city same-name candidates;
- caches decisions in memory and paces the public endpoint;
- can be disabled or replaced with a self-hosted base URL.

Public Nominatim and Valhalla services are private-alpha conveniences, not an
unlimited commercial infrastructure plan. A paid deployment must obtain an
appropriate service agreement or self-host.

## Compass mobility guardrail

LLM extraction remains the general language interpreter. For the narrow case of
an explicitly written mode plus duration, a deterministic guard keeps the fact
when the model returns nothing or omits one mode. It does not infer a location,
mode, duration, or requirement strength that the user did not write. Adding a
new limit supersedes the older active limit for the same mode only.

## Next boundaries

- v0.6.10: an evidence graph that can combine advertisement, company, mobility,
  salary, and reputation evidence without treating advertisement silence as a
  negative.
- v0.6.11: persistent background work with real progress states.
- v0.6.12: authentication, workspace isolation, consent, export/deletion,
  retention controls, legal surfaces, and alpha administration.

