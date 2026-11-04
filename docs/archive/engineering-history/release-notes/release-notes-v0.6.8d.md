> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8d Release Notes

v0.6.8d fixes a geocoder identity defect and makes multi-job Transitous failure
diagnostics directly inspectable.

## Root causes

- A city-only label was expanded to `"<city> Bahnhof"`. Station-like words
  received enough ranking weight to beat the requested locality itself. The
  request for Alzenau therefore selected a distant place named "Zum Alten
  Bahnhof" near Siegen.
- A Match run stores an immutable result snapshot. Provider errors are not
  cached, but an old Unknown remains visible until Matching is explicitly run
  again.
- Personio's fictional "The Demo Daten GmbH" tenant could appear in structured
  metadata even when the advertisement body repeatedly named the real employer.

## Fixed

- City-only Transitous inputs use country-qualified city-centre geocoding.
- Candidates must contain the requested locality and, where locally resolvable,
  remain within 25 km of the expected city coordinates.
- Public requests are paced and temporary responses or transport failures
  receive up to two bounded retries.
- Unsafe geocoder candidates and HTTP failures remain explicit Unknowns with
  inspectable diagnostics; they never become a duration.
- The new routing cache fingerprint prevents v0.6.8c results from being reused.
- A narrowly scoped normalization replaces the known Personio demo placeholder
  only when the job body repeats a different employer identity.
- An imprecise destination may carry a separate company-and-city POI hint for
  Google. Transitous continues to receive only the evidence-backed location.
- `scripts/diagnose_saved_commutes.py` explains every route stored in the latest
  Match without making new provider requests.

## Preserved

- the accepted visual design;
- 25 equal-quality private-alpha slots;
- cheap, offline Explore ordering;
- deterministic and evidence-backed matching;
- privacy-first routing and no invented travel time;
- database revision `0007_route_evidence` and existing user data.
