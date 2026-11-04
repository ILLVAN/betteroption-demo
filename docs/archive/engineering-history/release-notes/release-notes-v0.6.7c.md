> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.7c Release Notes

v0.6.7c is a correctness and discovery-breadth release. The warm visual design
and all existing page ownership boundaries are preserved.

## Corrected

- Plain Frankfurt transit origins resolve to Frankfurt am Main instead of an
  arbitrary first geocoder result.
- Transitous checks several itineraries, selects the shortest valid journey,
  cross-checks timestamps, and shows resolved-place diagnostics.
- Pre-fix commute cache entries are invalidated automatically.
- Explore location is no longer an exact-city filter that hides nearby jobs.
- CV upload control copy has visual separation, and immediate evidence review
  is selected by default.

## Added

- **Use Compass for search** builds a broad query from confirmed direction,
  skill, and origin data.
- Eight-page recent Arbeitnow discovery with a short in-process cache and
  transparent role-term expansion.
- Multi-source result merging and de-duplication.
- Optional Brave Search API support for broader employer and ATS discovery.
- Source labels on Explore cards and source attribution links above results.

## Preserved safety contracts

- Explore never changes Compass and consumes no slot until a job is selected.
- Selected URLs still pass the normal robots, network-safety, reachability, and
  evidence pipeline before they enter Archive.
- LinkedIn, Indeed, Xing, Stepstone, and Glassdoor are excluded from Brave web
  discovery instead of being bypassed.
- Transitous remains private-alpha only until commercial approval or self-hosted
  MOTIS capacity exists.
- The release ZIP contains no profile, database, CV, `.env`, API key, cache, or
  local source snapshot.

## Local upgrade

Back up `local-data/betteroption.db`, overlay the source archive, then run:

```powershell
cd C:\projects\betteroption
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -v
```

No database migration is required after v0.6.7b.

