> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.7c

## Product story

The primary navigation remains **Home → Compass → Explore → Match → Archive**.
v0.6.7c changes no ownership boundary. It corrects discovery breadth, route
resolution, and the CV upload affordance inside the existing story.

## Compass-driven discovery

`discovery_query_from_profile()` converts only confirmed role families,
responsibilities, career direction, industries, desired skills, and origin into
a broad Explore query. Compensation, exclusions, culture, and commute limits do
not narrow discovery; deterministic Matching evaluates those later.

Location is scored as a relevance boost rather than an exact-city filter. This
keeps nearby destinations visible so the mobility layer can decide whether the
actual journey fits.

## Multi-source provider boundary

`CompositeDiscoveryProvider` merges and de-duplicates attributed providers.
The keyless default reads up to eight recent Arbeitnow pages and caches that feed
in process for five minutes. Transparent role expansion currently covers a
small, reviewed set of embedded, software, test-automation, and mechatronics
terms.

When `BRAVE_SEARCH_API_KEY` is configured, a documented Brave Web Search adapter
adds recent web results. Known restricted aggregator hosts are excluded. Search
results remain ephemeral: selected URLs must still pass robots, SSRF, redirect,
content-type, size, reachability, expiration, and evidence checks before
persistence.

## Correct public-transport resolution

Transitous now requests eight geocode candidates and explicitly disambiguates
plain `Frankfurt` to Frankfurt am Main. It records both resolved names and
coordinates in diagnostics, requests up to five MOTIS itineraries, chooses the
shortest valid duration, and cross-checks `duration` against `startTime` and
`endTime` when available.

The commute query fingerprint includes `mobility-v0.6.7c`, so every estimate
created by the earlier ambiguous resolver is ignored and recalculated. The
12-hour private-alpha cache policy otherwise remains unchanged.

## Persistence and compatibility

No schema migration is required. Discovery results remain ephemeral until
selected. The current immutable result snapshot version is
`matching-v0.6.7c`; earlier result sets are visibly stale and rerunnable.

