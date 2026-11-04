> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8 Release Notes

v0.6.8 makes the 25-slot private-alpha promise concrete: all 25 saved jobs can
receive complete profile matching and full-quality routing after the user starts
a Match run. Explore remains intentionally cheap and never calls route APIs.

## Added

- explicit 25-job exact-routing policy alongside 25 storage and result slots;
- privacy-first and balanced provider modes;
- three ordinary-Tuesday morning samples with median and visible range;
- endpoint labels, precision, route scope, confidence, and sample diagnostics;
- geographic plausibility checks with fallback/Unknown behavior;
- most-precise verified job location selection;
- additive `0007_route_evidence` migration.

## Preserved

- the accepted warm interface and Home → Compass → Explore → Match → Archive story;
- deterministic Top / Stretch / Blocked decisions;
- profile-free release packages;
- pytest-only verification;
- no bypass of robots, login walls, LinkedIn restrictions, or source controls.

## Deliberately deferred

Usage-based free/pro tier degradation is not introduced. The alpha keeps 25 equal
full-quality slots until route invocation, latency, and conversion data justify a
different commercial policy.
