> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.10c — Match cost KPIs and explicit providers

v0.6.10c closes the first operational measurement loop while preserving the
accepted Matching behavior.

## Product changes

- Matching and Archive cards use a compact bottom row with **Delete job** on
  the left and application state on the right.
- Application state still saves immediately and color-codes the card, but no
  permanent autosave caption consumes card space.
- Operations now shows whether Brave, Exa, OpenAI, Google Routes, Transitous,
  Valhalla, and OpenRouteService are configured or available without rendering
  their secrets.
- Recent Match runs show jobs and included slots, Top/Stretch/Blocked counts,
  exact-route jobs, provider work and failures, duration, and estimated cost.

## Cost honesty

- Brave and Exa have separate optional per-call estimates.
- Actual provider names are retained at discovery and company-research
  boundaries instead of being collapsed into a generic mesh label.
- A missing estimate is labelled **unpriced** rather than treated as free.
- All figures are operational estimates; provider invoices remain authoritative.

## Privacy and persistence

- Provider operations use an opaque workflow identifier shared with a Match run.
- Correlation stores no query, location, endpoint, URL, prompt, CV/job content,
  model output, or API key.
- Database migration `0010_match_run_operations` is additive and retains all
  profiles, jobs, results, decisions, CV text, and route evidence.

## Verification focus

- Existing matching algorithm: unchanged (`matching-v0.6.10b`).
- Existing 25-slot allowance: unchanged.
- Existing deletion confirmation, application history, routing, discovery, and
  evidence behavior: unchanged.
