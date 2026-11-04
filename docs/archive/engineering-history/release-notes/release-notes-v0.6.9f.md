> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9f — Balanced routes and a stable Explore shelf

v0.6.9f is a narrow reliability increment. It preserves the accepted UI,
profile protocol, 25-slot private-alpha policy, job corpus, and database schema.
Existing open jobs do not need to be imported again.

## Routing

- `balanced` mode with `GOOGLE_ROUTES_API_KEY` now tries Google Routes before a
  previously cached open-data fallback can short-circuit the provider chain.
- Google route responses remain current-run evidence and are not persisted.
  Transitous, Valhalla, and openrouteservice remain available fallbacks.
- `scripts/diagnose_mobility.py` prints the configured provider order, making a
  stale `.env` value such as an explicit `valhalla` provider immediately visible.
- Use `BETTEROPTION_MOBILITY_PROVIDER=auto` together with
  `BETTEROPTION_MOBILITY_PRIVACY_MODE=balanced` to select Google-first routing.

## Explore continuity and freshness

- The latest successful Explore results remain available when navigating to
  Compass, Matching, Archive, or Job Detail. A new explicit search replaces the
  prior in-process result shelf.
- Brave and Exa web discoveries receive bounded, robots-aware source checks.
  HTTP 404/410 and explicit expired-page evidence are removed before display.
- A blocked, JavaScript-only, or temporarily unreachable page is not called
  closed. It remains visible as a source requiring verification.
- Direct ATS and documented job-feed results stay on their normal fast path.

## Local workflow

Four PowerShell helpers separate installation, verification, running, and Git
publication. They use `.venv\Scripts\python.exe` directly and therefore work with
Windows' restrictive script policy when invoked with `-ExecutionPolicy Bypass`.
The installer validates the ZIP paths, preserves private runtime data, includes
the extraction dependency group, and intentionally does not run pytest.

## Safety boundary

Search-engine discoveries remain untrusted until their selected source passes
the existing URL, robots, reachability, extraction, and evidence pipeline. The
preflight removes only demonstrably closed pages; it does not bypass restricted
sources or claim that an unknown page is current.
