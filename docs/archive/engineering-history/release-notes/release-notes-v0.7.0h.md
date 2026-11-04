> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0h

v0.7.0h is a narrow operational-clarity release built on the accepted
v0.7.0g workflow foundation. It does not change discovery, matching, routing,
tenant isolation, or persisted user data.

## Live Operations activity

- Background workflows are ordered by their latest activity rather than only
  by their original creation time.
- The Operations page displays the observation time and task timestamps down
  to seconds.
- While a queued, running, or retry-wait workflow exists, the visible
  Operations page refreshes every five seconds.
- Refreshing pauses in a hidden browser tab and resumes when the page is
  visible, avoiding pointless operator traffic.
- Existing provider-ledger semantics remain honest: a cached Explore view that
  performs no provider call does not create synthetic provider usage.

## General job feedback

The feedback surface no longer assumes a software-development career. The
previous role-specific options are presented as general questions about
responsibilities, day-to-day work, level or scope, and company or work context.
Existing stored enum values and decision history remain compatible.

## Clean overlay installation

The local installer now removes the obsolete `tests/test_v070a1.py` file left
by an early account prototype. That test encoded the pre-account anonymous
workspace contract and caused two false failures after authentication and
tenant isolation became real product boundaries.

The installer still preserves `.env`, local databases, API keys, CV text, and
`local-data`, and installs the extraction dependencies through
`.[dev,extraction]`.

## Deployment recommendation

The release adds a deployment decision record for the invited alpha:

- keep `betteroption.example` and authoritative DNS at Cloudflare;
- run the FastAPI web process, durable worker, PostgreSQL, and backup jobs on a
  small EU application server;
- proxy the public HTTPS hostname through Cloudflare;
- use the existing shared cPanel plan only for a separate static landing page
  if desired, not as the production application runtime.

See [Deployment options](../../discontinued-product-planning/deployment-options-v0.7.0h.md) for the concrete
topology, cPanel domain instructions, and the first-alpha server size.

