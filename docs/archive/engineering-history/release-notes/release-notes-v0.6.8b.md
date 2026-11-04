> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8b Release Notes

v0.6.8b is a focused stability patch. It does not change the accepted interface,
the 25-slot alpha policy, or any profile and matching semantics.

## Fixed

- XML-looking fragments inside Schema.org job descriptions are still treated as
  HTML fragments, but no longer emit a misleading BeautifulSoup runtime warning.
- Transitous geocoding retries a missing city-station lookup with a
  country-qualified city query and then the original city label.
- When a station-to-station plan returns no itinerary, one bounded city-centre
  recovery request is allowed. If that also fails, the commute remains Unknown.
- Successful Transitous geocodes are reused across the 07:30, 08:00, and 08:30
  samples, reducing public-endpoint traffic and avoiding inconsistent endpoints.
- Route evidence records whether each resolved endpoint is a station or city
  area instead of labelling every city fallback as a rail hub.

## Verification contract

The patch adds explicit regressions for an Alzenau station miss, an empty
station-plan recovery, geocode reuse, and XML-looking JSON-LD content. Release
acceptance still requires the complete pytest suite with coverage, Ruff format
and lint checks, bytecode compilation, package inspection, and live Uvicorn
route smoke tests.

## Preserved safety boundaries

- no Google request is made in `privacy_first` mode;
- Explore performs no exact routing;
- no route duration is inferred from straight-line distance;
- `.env`, API keys, CVs, profiles, databases, and local runtime data are absent
  from the release archive;
- the database remains at additive migration `0007_route_evidence`.
