> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9h — Expiry and slot controls

v0.6.9h preserves the v0.6.9g matching algorithm, routing policy, source mesh,
persistent Explore shelf, database schema, and accepted visual layout. Existing
jobs do not need to be imported again.

## Closed-source protection

- Explore web results receive the existing bounded, robots-aware preflight.
- Human-visible closed states such as `Expired 27d ago` are evaluated before
  stale `JobPosting` JSON-LD, so structured data cannot keep a closed page alive.
- A page discovered as closed during selection is removed from the current
  Explore shelf and is not retained in Archive or passed to Matching.
- Blocked or temporarily unavailable pages still remain Unknown rather than
  being falsely labelled closed.

## Slot and deletion controls

- Explore shows the remaining 25-slot capacity while selecting jobs and blocks
  an overflowing selection before any import starts.
- The server repeats that check atomically; partial over-capacity imports are not
  possible.
- Archive supports select-all and confirmed bulk deletion for the current
  filter.
- Match supports the same complete deletion without forcing a trip to Archive.
- Reference cards have their own confirmed delete action. Complete deletion
  removes revisions, match rows, source copies, and linked reference settings and
  frees the slot.

## Compass and identity

- Each Compass section offers three keyboard-operable topic suggestions aligned
  with evidence the product can evaluate: role and seniority, modal commute
  limits, working arrangement, salary and time, skills and languages, product
  exclusions, and attributable culture signals.
- Selecting a suggestion inserts it into the active answer box for immediate
  completion rather than silently creating a preference.
- The established warm layout is unchanged. The header now uses a code-native
  pink, turquoise, orange, and black mark that remains crisp at every resolution.

## Upgrade and verification

The release contains no `.env`, API key, database, profile, CV, or local corpus.
Use `scripts/install_latest_release.ps1` to overlay it while preserving private
runtime data, then run `scripts/test_release.ps1` separately for the full suite.
