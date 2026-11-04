> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9e — Regional coverage and language evidence

v0.6.9e is a focused quality increment. It keeps the existing UI, database,
URL trust boundary, and matching presentation while improving the two weak
points exposed by live Brave and Exa testing.

## Explore

- A Compass search targets 30 resolved, non-remote jobs inside a 150 km rough
  discovery radius. This is a coverage target, not an invented guarantee: live
  supply and source availability can produce fewer results.
- Regional coverage is measured separately from total volume. One hundred
  remote or far-away discoveries no longer prevent the conditional Exa fallback.
- Brave uses bounded role-by-city searches across offline-resolved nearby labour
  markets. The first locality may use a second results page; the complete Brave
  budget is at most eleven requests.
- Conditional Exa expands up to six focused role/locality combinations when the
  primary mesh remains regionally short.
- Direct ATS expansion starts with the already ranked candidates, so nearby and
  relevant employer boards receive the limited expansion budget first.
- Search-result locations are accepted only when a postcode or locality is
  visible in source material. Unknown locations do not receive invented distance
  credit. Exact route APIs remain reserved for Matching.

## Matching

- Confirmed language facts from candidate experience, CV evidence, or explicit
  `language.native`, `language.proficiency`, and `language.spoken` facts are
  available to required-skill coverage.
- Combined statements such as “German and English fluent” can satisfy separate
  explicit German and English requirements.
- A desired English-speaking workplace is not treated as proof that the user
  speaks English. Desired future work and demonstrated capability stay separate.
- The deterministic matching version is `matching-v0.6.9e`. Existing saved runs
  stay unchanged until the user reruns Matching.

## Upgrade

No migration and no job re-import are required. Install the overlay, restart the
web process, repeat Explore to use the locality-aware source mesh, and rerun
Matching to apply the language-evidence rules.
