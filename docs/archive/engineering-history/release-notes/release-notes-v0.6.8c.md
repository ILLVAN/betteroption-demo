> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8c Release Notes

v0.6.8c fixes a live private-alpha failure where every public-transport result
could become Unknown after one Match run generated a burst of Transitous calls.

## Root cause

v0.6.8 sampled three departure times for every time-dependent provider. The
Transitous adapter also repeated origin and destination geocoding for each
sample. Six jobs could therefore generate up to 54 community-endpoint requests
in one synchronous Match run. A rate limit or temporary service response was
reported only as a generic provider error.

## Fixed

- Transitous now sends one standard-Tuesday 08:00 plan request per job and asks
  MOTIS for seven itinerary alternatives in that request.
- Successful geocodes are reused across the complete Match run.
- HTTP 408, 429, 500, 502, 503, and 504 responses receive one bounded retry.
- A numeric `Retry-After` header is respected up to two seconds.
- Persistent HTTP failures expose their status in route diagnostics.
- Small-city station and city-centre recovery from v0.6.8b remains active.
- `scripts/diagnose_mobility.py` can test one explicit route without reading a
  profile or persistent database.

## Preserved

- the 25 equal-quality alpha slots and cheap Explore geography;
- deterministic matching and plausibility checks;
- privacy-first routing without Google unless explicitly enabled;
- no invented transit duration when every provider fails;
- database revision `0007_route_evidence` and all existing user data;
- the accepted visual design.
