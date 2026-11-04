> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.10b — Visible operations and application flow

v0.6.10b turns the first provider ledger into an operator-visible control room
and brings application tracking onto the pages where jobs are actually compared.
The accepted Explore, source verification, routing, and matching contracts remain
unchanged.

## Application state on overview cards

- Archive and Matching cards show a compact application-state dropdown at the
  bottom of the card.
- Changes auto-save through the same append-only interaction history used by Job
  Detail.
- Subtle accents distinguish saved, preparing, applied, interview, offer,
  rejected, and withdrawn states. The written state remains authoritative.
- The control is separate from card navigation and complete-deletion selection,
  so changing state does not open or delete a job.

## Compass safeguards

- A confirmed internship exclusion is interpreted as “do not show internships,”
  not as a positive intern target. An ordinary junior role can therefore satisfy
  the exclusion.
- When a car, transit, bicycle, or walking limit is active, the consistency gate
  requires a starting point before Matching. A city, district, postcode, station,
  or street address is sufficient; there is no locality-specific workaround.
- Distant simultaneous origins and unresolved bare postcodes receive focused
  guidance before paid routing work begins.

## Operations control room

`/operations` shows sanitized usage for today and the rolling seven days, plus a
per-provider/purpose breakdown of calls, results, average latency, failures,
budget blocks, cache hits, and configured estimated cost.

The page also displays the active environment-controlled daily operation and
estimated-cost guards. It is intentionally read-only: production limits and
secrets are changed through deployment environment configuration, not a public
web form.

The ledger contains no query, address, URL, prompt, response, CV text, job text,
or API-key fields. Provider invoices remain authoritative when a unit cost is not
configured.

## Upgrade

```powershell
cd C:\projects\betteroption
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_latest_release.ps1
```

The installer includes extraction and installs `.[dev,extraction]` while
preserving `.env`, the database, CV text, and local runtime data.
