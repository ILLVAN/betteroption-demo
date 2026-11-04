> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.7b

## Product story

The primary navigation is **Home → Compass → Explore → Match → Archive**.

- Compass owns user intent, explicit corrections, CV evidence proposals, and
  Review Tray authority.
- Explore is a non-mutating discovery adapter. Search results use no Archive
  slot and do not affect matching until selected.
- Match owns one-off reference URLs, reference-learning controls, deterministic
  result runs, feedback, and application state.
- Archive owns the verified corpus, lifecycle, revisions, rechecks, and
  deletion. `/jobs/{record_id}` remains the single Job Detail.

## Explore boundary

`JobDiscoveryProvider` keeps feed choice outside the web and domain layers.
The first provider uses Arbeitnow's public Germany-oriented JSON feed. Search
is bounded to two feed pages and at most 30 visible results. Selected URLs pass
through the existing public-URL fetcher, robots, SSRF, redirect, size,
reachability, expiration, and evidence checks before persistence. Explore does
not scrape LinkedIn or bypass access controls.

## Public-transport fallback

The mobility chain is mode-aware:

1. Google Routes when a local key exists.
2. Transitous/MOTIS for public transport.
3. openrouteservice for car, bicycle, and walking when a local key exists.

Transitous geocodes the origin and destination, requests one MOTIS itinerary,
uses an identifying User-Agent, shows attribution and diagnostics, and permits
a 12-hour private cache. Its public instance is community-run and best effort.
The private alpha must contact Transitous or self-host MOTIS before commercial,
high-volume production use.

## CV merge boundary

Uploading and merging are separate actions. A saved text-only CV can be sent to
the experience extractor using **Review and merge into Compass**. The full CV
is not copied to messages or raw profile sections. Atomic proposals enter the
normal Review Tray; only user-confirmed facts become candidate evidence for
skill matching. Re-extraction cannot overwrite confirmed user decisions.

## Salary orientation

Explicit advertised compensation always wins. If none is present, a
deterministic title-family mapper may attach a Bundesagentur für Arbeit
Entgeltatlas lower/upper-quartile annual benchmark. The view states occupation
family, confidence, source, and assumptions. Estimated pay remains unknown for
hard-filter evidence: it can orient a user but cannot prove an employer offer or
hard-block an opportunity.

## Persistence and compatibility

No migration is needed. Explore results are ephemeral until imported; CV rows
use revision `0006`; salary and Transitous evidence live inside the existing
versioned match-result JSON. The matching snapshot version is
`matching-v0.6.7b`, making older results visibly stale and rerunnable.
