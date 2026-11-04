> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9c — Regional discovery and explicit learning

v0.6.9c improves the quality and shape of Explore while preserving the accepted
mobility and Matching behavior.

## Discovery

- The keyless feed depth defaults to twenty pages.
- Configured Brave discovery runs a bounded broad query, a focused Compass query,
  and a regional employer-career query. Local roles rank ahead of remote and
  far-away roles unless the Compass prefers remote work.
- Remote-only results can be hidden explicitly. Soft work-style preferences rank;
  only explicit must-haves become strict filters.
- Configured Exa fallback starts below thirty ranked candidates. Public ATS board
  expansion remains bounded and selected URLs still pass the normal safety,
  reachability, robots, and extraction pipeline.

The synchronous request does not crawl 200 companies. The scalable follow-up is
a cached background regional-employer pool that may inspect up to 200 attributed
career sites per region and field, then refresh incrementally.

## Trust and evidence

- Equivalent repeated Compass statements collapse in the active projection while
  the underlying audit history remains available.
- Job feedback has an explicit opt-in to create an editable Compass preference.
- Retained CV text records and displays its most recent evidence review time.
- Explicit spoken-language requirements are recovered and checked against
  confirmed candidate experience.
- Attributed company product evidence can reduce uncertainty for unrelated
  exclusions, but the UI explicitly states that absence is not proven.

## Data migration

Migration `0008_cv_review_state` adds nullable `reviewed_at` metadata. Existing
CV text, jobs, profiles, match history, and commute evidence remain valid.
