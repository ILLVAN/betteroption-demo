> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9d — Compass and search clarity

v0.6.9d is a focused stabilization increment. It preserves the v0.6.9c source
mesh, matching contracts, database, and warm visual system while repairing the
parts that made direct Compass editing feel unreliable.

## Compass

- A direct “Add a detail or correction” action is allowed even while indirect
  CV or learned evidence awaits review. The explicit user action does not accept,
  reject, or otherwise alter that pending evidence.
- When structured extraction returns no atomic fact, the exact explicit answer
  is retained as a confirmed, visible, editable statement. User-authored intent
  can no longer vanish because a provider returned an empty fact list.
- Identical normalized wording within one prose-led section has one active
  projection even when separate model runs chose adjacent ontology keys. Raw
  facts and review history remain stored for auditability.
- “Guided setup” is the primary Compass action. Direct additions return to the
  changed section; statement edits return to the changed statement; removals
  return to the containing section.

## Matching presentation

Commute evidence now has four textual and visual states:

- green: at or below the confirmed limit;
- yellow: above the limit but no more than 15% over it;
- grey: unavailable or missing precise endpoints;
- red: more than 15% above the limit.

The existing exact duration, mode, route provider, endpoint precision, cache
state, and diagnostic evidence remain authoritative. Color is only a scanning
aid and is never the sole signal.

## Explore

- Keyless Arbeitnow discovery uses the full configured thirty-page budget and a
  short cache.
- The final transparent ranking places approximately local roles (up to 80 km
  straight-line discovery distance) ahead of the wider two-hour stretch band.
- Brave and Exa remain optional. Exa is still invoked only below the configured
  primary-result threshold. Selected candidates must pass the existing URL,
  robots, reachability, and extraction pipeline before they enter Archive.

Existing jobs do not need to be re-imported. Existing match runs remain
immutable; rerun Matching only when you want results based on the latest Compass.

