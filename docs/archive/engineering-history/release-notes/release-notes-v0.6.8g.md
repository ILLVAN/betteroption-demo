> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8g Release Notes

v0.6.8g is a focused mobility and waiting-state refinement. It does not change
the accepted visual direction or the 25-slot private-alpha policy.

## Mobility facts users can trust

- Location-and-mobility extraction must return a mode with every time limit.
- Stored values are normalized to wording such as `60 minutes by car one way`.
- Inputs expressed in hours are converted correctly before matching.
- Legacy bare values are repaired from an unambiguous semantic key when loaded.
- A limit without any identifiable mode becomes an Open unresolved statement
  and is not used as a hidden commute boundary.

## More readable routes

Durations below one hour remain `33 min`. Longer values use compact, zero-padded
minutes such as `1h 12m` and `3h 04m`. The same formatter is used on result cards,
route ranges, limits, medians, and diagnostic samples.

## Honest waiting feedback

Profile extraction, CV evidence extraction, selected-job ingestion, URL-based
job extraction, and full Matching now show an accessible indeterminate progress
overlay. It prevents uncertain double submissions without inventing a percentage
the synchronous server cannot actually measure.

CV/reference-derived evidence still requires review. Direct Compass answers
remain immediately active, editable, reclassifiable, and removable.
