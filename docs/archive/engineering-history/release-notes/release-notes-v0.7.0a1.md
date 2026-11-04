> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.0a1 — Background Explore imports

This is a focused reliability release on top of the v0.7.0a account boundary.
It does not redesign discovery, matching, routing, or the accepted visual system.

## User-visible changes

- **Save to Archive** returns immediately to durable progress while selected job
  sources are verified and extracted in the background.
- **Save and run Match** first completes that import and then links to the
  existing background Match task. Navigation or refresh does not lose either
  phase.
- **Hide remote-only roles** filters the currently displayed and cached Explore
  results in the browser. It makes no Brave, Exa, feed, geocoding, or routing
  request.
- Guided Compass clarifications retain the same topic suggestions as the main
  section prompt.
- Discovery uses the structured location currently shown in Compass before any
  older extracted location statement.

## Safety and architecture

Selected source URLs are kept in a tenant-owned import-payload table rather than
the operational task row. Progress, retries, and the operator ledger therefore
remain free of job URLs and user content. The payload is deleted after the import
finishes. Expired sources are removed from both the Archive and the cached
Explore result set.

The private-alpha worker remains deliberately single-process. A later deployment
can move the same SQL-backed task contract to a separate worker without changing
the user-facing flow.

## Database migration

Migration `0013_background_job_imports` adds:

- `background_job_import_batches`
- `background_job_import_items`

Both are additive. Existing profiles, CV evidence, jobs, results, route caches,
provider operations, and account data remain unchanged.
