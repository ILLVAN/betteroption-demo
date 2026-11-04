> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1h-workflow-refinement

This local release refines the v0.7.1g account/persona architecture without
opening a server or changing the private-alpha readiness flags.

## Apply

- Cover letters are grouped by job, with up to three expandable named drafts
  inside each job group.
- A Job Detail creation link shows only that job, preselected and ready for the
  one-time OpenAI action. It does not open another job's drafts.
- Job and draft deep links are validated and remain focused after save,
  transform, generation, and deletion.
- The picker now says “Generate up to 5 cover letters at once.”

## Matching corrections

- Boundary, commute, and skill corrections appear beside the machine result
  they replace. The redundant optional explanation field is gone.
- Corrections follow the persona across replacement Compass workspaces and are
  reapplied by full Match runs.
- Saving a correction offers a separate one-job rematch. The save itself never
  starts a provider call or cost.
- A broad AI salary orientation may now provide very-low-confidence supporting
  context. It can improve evidence coverage and compatibility, but never proves
  employer pay or a salary violation. Advertised compensation still takes
  precedence.

## Providers and Explore

- Every technically available provider is enabled by default. Account owners
  may opt out; the account decision applies to all personas.
- Disabled providers produce no request and no provider cost. Enabled calls
  with an unknown/zero price remain “used but unpriced,” never “free.”
- Explore has a default-on `Include custom portals` scope when enabled portals
  and Brave/Exa are available.
- Portal paths retain meaningful locale/branch scope while generic `SearchJobs`
  leaves are stripped. Deterministic error and search-landing pages are rejected.
- Source-run diagnostics show how many final results belong to saved portal
  scopes included in the run.

## Application-state presentation

- Discovered, Saved, Preparing, Applied, Interview, Offer, Rejected, and
  Withdrawn have distinct restrained visual marks.
- Rejected and Withdrawn use broad, low-opacity terminal stripes rather than the
  previous dark grey/white overlay.

## Boundary

- Local loopback use only is the supported operating mode for this iteration.
- No legal-readiness claim, processor approval, or public/private-alpha launch
  flag is added by this release.
- No database migration is required beyond the existing Alembic head
  `0022_application_draft_slots`.

