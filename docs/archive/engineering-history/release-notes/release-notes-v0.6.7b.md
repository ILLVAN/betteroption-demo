> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.7b Release Notes

v0.6.7b completes the first coherent search-to-decision loop without changing
the accepted warm visual system.

## Added

- Navigation ordered Home, Compass, Explore, Match, Archive.
- Explore search through a bounded public Arbeitnow provider adapter.
- Multi-select Save to Archive and Save and run Match actions.
- Keyless Transitous/MOTIS public-transport fallback with geocoding,
  attribution, diagnostics, and a 12-hour cache.
- Explicit Review and merge into Compass action for retained CV text.
- Salary benchmarks for supported German occupation families when the source
  states no compensation.
- `matching-v0.6.7b` result snapshots and visible stale-run detection.

## Preserved safety contracts

- Search results do not change the Compass and do not consume slots until
  selected.
- Selected job URLs must pass the normal public-URL and evidence pipeline.
- CV proposals affect matching only after user confirmation.
- Salary benchmarks are estimates, not employer evidence, and do not hard-block.
- Transitous public service is private-alpha only until commercial approval or
  self-hosting is in place.
- The release ZIP contains no profile, database, CV, `.env`, API key, or local
  source snapshot.

## Local upgrade

Back up `local-data/betteroption.db`, overlay the source archive, then run:

```powershell
cd C:\projects\betteroption
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -v
```

No new database migration is required after v0.6.7.
