> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0e

v0.7.0e is a focused Explore latency and geographic-scope repair. It keeps the
useful discovery breadth from v0.7.0d without allowing slow location or
fallback work to hold the workflow for many minutes.

## Bounded source mesh

- The full source mesh has a shared 115-second deadline.
- Keyless feeds and configured search providers run in bounded parallel stages.
- Exa keeps multiple focused role, regional, and employer-oriented searches
  inside a 70-second provider budget; it is not reduced to one query.
- Provider executors stop waiting when their budget expires. Partial, valid
  results are returned instead of blocking indefinitely.
- The new limits are configurable, but validated so the web workflow cannot
  accidentally exceed two minutes.

## Fast, honest geography

- Place resolution uses a cached offline index and bounded token lookup instead
  of repeatedly scanning every known place.
- Explore ranking still uses approximate geography only. It does not spend
  Google Routes or other paid routing calls.
- Only a bounded shortlist receives concurrent live URL availability checks:
  at most 24 candidates, at most two per host, within eight seconds by default.
- Candidates that were not checked remain visible as unverified discoveries;
  they are not silently discarded.
- An unresolved place remains Unknown. It never receives zero-distance credit.

## Global market behavior

- The default search market is the continent inferred from the Compass origin.
  Europe is not hardcoded as the universal default.
- **Worldwide** explicitly allows cross-continent candidates in the next search.
- **Remote only** and **Hide remote-only** are mutually exclusive local filters.
  They update the current persisted cards immediately without re-searching.
- Country hints sent to providers are derived from the resolved Compass
  location, not from a fixed deployment locale.

## Configuration

```dotenv
BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=115
BETTEROPTION_EXA_SEARCH_BUDGET_SECONDS=70
BETTEROPTION_DISCOVERY_AVAILABILITY_BUDGET_SECONDS=8
BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS=24
```

Exact job verification and extraction still occur after selection. Exact
commute calculation still occurs during Matching.

## Upgrade behavior

No saved jobs, Compass answers, Match results, accounts, or API keys need to be
recreated. Run a new Explore search once to use the v0.7.0e provider and market
budgets; the previous persisted result set remains available until then.
