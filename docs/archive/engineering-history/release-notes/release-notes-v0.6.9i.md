> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9i — Consistency and score calibration

v0.6.9i is a focused hardening increment over v0.6.9h. It preserves the
discovery source mesh, persistent Explore results, source preflight, routing
providers, database schema, and the 25-slot private-alpha allowance.

## User-flow changes

- Archive and Match selectors are integrated into their cards.
- Bulk deletion opens an explicit modal warning. The server still requires a
  confirmation value, so disabling JavaScript cannot bypass the safety check.
- Reference deletion uses the same modal confirmation.
- The brand mark is lighter and friendlier, with a pale pink halo and soft teal
  wave instead of the earlier dark opposing-petal silhouette.

## Compass consistency

Matching pauses for a small set of high-signal contradictions, including junior
and senior targets, remote-only and on-site-only boundaries, and the same
condition being both wanted and excluded. Ordinary breadth across roles,
industries, and skills is deliberately not treated as an error. The user can edit
the Compass or explicitly acknowledge the tension for the current run.

## Score calibration

- Only supporting preferences add positive points.
- A preference contradicted by job evidence now lowers the score.
- The final compatibility score is calibrated by the share of resolved evidence.
  Unknowns remain different from conflicts, but sparse evidence cannot claim the
  same confidence as a fully supported result.
- The matching identity advances to `matching-v0.6.9i`; rerun Matching once to
  replace earlier saved scores. Re-importing jobs is not required.

No migration is required. Profiles, API keys, CV text, job revisions, and local
runtime data remain excluded from the release archive.
