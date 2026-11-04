> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9j — Operational UX foundation

v0.6.9j is a deliberately narrow correction over v0.6.9i. It preserves the
accepted matching algorithm, Compass consistency checks, discovery source mesh,
routing policy, database schema, and 25-slot allowance.

## Selection and deletion

- Archive and Match deletion controls now live inside the job card, in the same
  clear position as Explore selection.
- Their label is explicitly **Delete job**, so the action cannot be mistaken for
  selecting a role for matching.
- Bulk deletion no longer depends on JavaScript injecting the server confirmation
  value. The rendered destructive form carries that value, and the button remains
  disabled until at least one job is selected.
- Deletion still removes the complete local aggregate: job record, revisions,
  observations, aliases, reference settings, match history, source copy, and slot.
- The backend retains its confirmation-field guard for non-UI requests.

## Stable frontend assets

CSS and JavaScript URLs contain the application version. A newly installed release
therefore cannot accidentally render with an older cached stylesheet or script.
The accepted v0.6.9i logo is unchanged.

## Product sequencing

The next work starts with provider-operation accounting and budget controls before
adding more paid calls or user accounts. The complete sequence and privacy boundary
are recorded in [Roadmap to the Private Alpha](../../discontinued-product-planning/roadmap-to-private-alpha.md).

No migration, job re-import, or Match rerun is required for v0.6.9j.
