> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9 — Discovery Source Mesh

v0.6.9 broadens Explore while preserving the warm UI and every existing trust
boundary.

## Delivered

- Public Greenhouse, Lever, and Ashby connector adapters.
- Explicit company-to-board configuration, including Lever's European host.
- Safe ATS-board expansion from already discovered ATS URLs.
- Three-page Brave discovery instead of a single result page.
- Exa as an optional, conditional fallback only when primary ranked coverage is
  below the configured floor.
- One deduplication and Compass-aware ranking pass across all discovery sources.
- Provider attribution and source URL on every candidate.
- Generic Nominatim district/address resolution for privacy-first Valhalla
  routes, with locality validation and no place-specific hardcoding.
- A deterministic guard for explicitly authored modal commute limits and
  same-mode supersession.
- Honest feedback when a targeted Compass answer produced no new statement.

## Preserved boundaries

- Search does not run exact routing and therefore cannot consume paid route
  quota.
- A discovery is not archived evidence. Selected URLs still pass SSRF, redirect,
  robots, reachability, content, and extraction checks.
- LinkedIn, Indeed, Stepstone, Xing, and Glassdoor are not bypassed.
- No automatic application, authentication, billing, or unrestricted crawling
  was added.
- The release overlay contains no database, profile, `.env`, API key, CV, upload,
  route cache, or local data.

## Configuration

The keyless Arbeitnow source remains enabled. Optional settings are documented
in `.env.example`:

- `BRAVE_SEARCH_API_KEY`
- `EXA_API_KEY`
- `BETTEROPTION_EXA_FALLBACK_MIN_RESULTS`
- `BETTEROPTION_GREENHOUSE_BOARDS`
- `BETTEROPTION_LEVER_SITES`
- `BETTEROPTION_ASHBY_BOARDS`
- `BETTEROPTION_ATS_EXPANSION_ENABLED`
- `BETTEROPTION_OSM_GEOCODER_ENABLED`
- `BETTEROPTION_OSM_GEOCODER_BASE_URL`

No database migration is required for v0.6.9.

