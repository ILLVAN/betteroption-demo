> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9b — Priority stabilization

v0.6.9b is a compatibility-preserving stabilization release for the private
alpha. It does not require a database migration or re-import of stored jobs.

## Matching responsiveness

- Route calculation and optional employer-context research now run in separate,
  bounded worker pools instead of serially across every job.
- The web composition root keeps one employer-context service alive, so repeated
  matching runs reuse bounded company and homepage caches.
- Transitous and Valhalla retain their public-service pacing but enter a short
  fail-fast cooldown after a terminal provider failure. One unavailable endpoint
  can no longer multiply the same timeout across every job.
- Existing persistent commute estimates keep the v0.6.9 fingerprint and remain
  reusable. A rerun does not require extraction or source import again.

The synchronous alpha request is now bounded substantially more tightly, but
v0.6.11 remains the planned move to durable background jobs and real progress
state for production-scale workloads.

## Explore distance and work arrangement

- Explore resolves German postcode origins through the bundled offline GeoNames
  postcode dataset before attempting city-label resolution. Approximate distance
  does not invoke Google, Transitous, Valhalla, or another paid route provider.
- Remote-only, on-site-only, or unrestricted discovery is derived from confirmed
  Compass work-arrangement statements. Explicit hybrid intent allows remote,
  hybrid, and on-site candidates. The separate Remote-only checkbox is removed.

## Evidence quality

- `location.origin`, `commute.origin`, and `mobility.origin` are profile context
  for routing. They are not job-advertisement requirements and no longer appear
  as missing evidence or in “Why still apply?” text.
- Personalized Stretch guidance prefers advertisement-backed role strengths and
  evidenced skills before commute evidence.
- Attributed surveillance, facial-recognition, or biometric-monitoring evidence
  can now activate an explicit company-category exclusion. When no reliable
  public evidence exists, the result remains Unknown.

## Upgrade

Overlay the release files onto the existing repository, reinstall the editable
package, run the full verification suite, and restart Uvicorn. Keep the existing
`.env` and `local-data` directory; neither is present in the release archive.
