> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.7d

## Scope

v0.6.7d adds company intelligence, transparent Explore ranking, personalized
Stretch guidance, and repeatable public-transport sampling without changing
profile, job, or result ownership. The accepted page story remains **Home →
Compass → Explore → Match → Archive** and Job Detail remains canonical.

## Company intelligence boundary

`CompanyIntelligenceService` produces two deliberately separate views:

- a product/revenue profile derived from verbatim employer-controlled homepage
  and job-advertisement text;
- an employer-reputation summary containing only attributed, inspectable
  evidence.

Business-category signals may resolve explicit exclusions such as defence,
staffing, recruitment, or consulting. They do not prove culture, contract terms,
or salary. The result snapshot stores the intelligence with the match, so later
page changes cannot silently rewrite an old recommendation.

Kununu's current terms prohibit automated bots, spiders, and scrapers. The
application therefore does not fetch or scrape Kununu. A score is displayed only
when an employer-controlled page republishes it, with that page as the source.
Otherwise Job Detail offers a manual search and states that no score was
verified. When `BRAVE_SEARCH_API_KEY` is configured, a separate adapter may link
licensed search-index results from independent certification sources such as
Great Place to Work and Top Employers; it does not ingest review text.

The existing Bundesagentur für Arbeit Entgeltatlas range remains the salary
orientation for supported occupations when the advertisement states no pay. It
is never represented as company-specific compensation.

## Explore ranking

`OfflinePlaceIndex` resolves city labels from the packaged GeoNames city subset.
No user origin is sent to a geocoder. For resolvable origin/destination pairs:

`Explore rank = 70% proximity relevance + 30% keyword relevance`

Proximity uses a smooth decay over Haversine distance; keyword relevance uses
explicit query and synonym-token coverage. Distance, keyword relevance, and the
combined rank are visible on every card. When an origin exists, unresolved
locations receive no invented proximity credit and are ordered within their
lower band by the 30% keyword component. Without an origin, ordering falls back
to keyword relevance. Matching still uses provider route time for commute boundaries.

## Repeatable commute comparison

Car and transit comparisons use the next nationwide non-holiday Tuesday at
08:00 in `Europe/Berlin`. Transitous/MOTIS receives a request for seven
itineraries; BetterOption validates durations against itinerary timestamps and
selects the shortest valid option. The diagnostic panel shows the chosen local
comparison time and resolved endpoints.

The fingerprint prefix is `mobility-v0.6.7d`, intentionally invalidating older
route cache rows. Transitous remains private-alpha, best-effort infrastructure;
commercial release still requires project approval or self-hosting.

## Personalized Stretch guidance

“Why still apply?” is a deterministic view over the saved result. It names the
employer and role, selects up to two strongest supported Compass facts or skills,
and identifies the first concrete conflict or unknown. It never invokes an LLM,
invent a benefit, or modify the Compass.

## Persistence and privacy

No new migration is required. Company intelligence is serialized inside the
existing saved match-result JSON. GeoNames resolution is local. No `.env`, API
key, database, profile, CV, source snapshot, or route cache belongs in the release
archive.
