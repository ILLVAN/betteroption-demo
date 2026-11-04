> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0g

v0.7.0g is a clean compatibility and workflow repair. It starts from the
accepted v0.7.0e source tree and adds only the durable Explore-to-Match behavior
from the short-lived v0.7.0f package. It therefore retains the bounded global
search model, Worldwide option, and all v0.7.0d/e regression tests.

## Durable Explore-to-Match handoff

- A matching import remains discoverable from the Matching page while it is
  queued, running, or waiting for a retry.
- Returning to Matching redirects to the currently active import or match run,
  so progress does not disappear after navigating elsewhere.
- A successful import creates a fresh match task. This guarantees that the
  newly saved job is included even when an older run already took its corpus
  snapshot.
- Job-import and match-run progress remain separate durable records with their
  own status and retry history.

## Recoverable source failures

- Closed, blocked, unreachable, and non-extractable selections are removed
  from the current Explore result set when verified unusable.
- A selection that yields no usable job completes with a clear Explore message
  instead of leaving a poisoned failed import in the active pipeline.
- The user can immediately select another source and start a new durable import.
- Browser back/forward navigation clears stale submission locks and refreshes
  selection controls.

## Compatibility repair

The v0.7.0f archive was created from an older branch and omitted v0.7.0d/e
symbols, tests, and the persisted `worldwide` query field. v0.7.0g restores
those accepted interfaces. Existing v0.7.0e databases, saved Explore searches,
Compass profiles, accounts, jobs, and API settings remain compatible.

## Upgrade behavior

Install this profile-free overlay directly over the local project. The
installer preserves `.env`, databases, API keys, CV text, and local data. No
job re-import or Compass rebuild is required.
