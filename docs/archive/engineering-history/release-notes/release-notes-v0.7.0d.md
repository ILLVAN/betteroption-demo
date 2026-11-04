> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0d

v0.7.0d is a focused Explore and background-matching repair on top of the
accepted v0.7.0c migration and account foundation.

## Explore visibility

- **Hide remote-only** now hides matching cards immediately and restores them
  when unchecked.
- The visible-result count and selected-result count update from the same local
  card set.
- Toggling the switch does not repeat discovery or spend provider quota.
- The persisted Explore snapshot remains unchanged until the user starts a new
  search.

## Geographic market safety

- A semantic non-remote fallback must prove a requested or regional locality in
  its visible title.
- A semantic remote fallback must prove the requested country or European
  market in its visible title or excerpt.
- A query location echoed inside an unrelated foreign excerpt is not accepted
  as job-location evidence.
- Place resolution prefers a real city identity over generic station aliases,
  so origins such as “Leipzig Central Station” do not resolve to a similarly
  named feature on another continent.
- Direct structured feeds and ATS connectors retain their own location
  contracts.

These checks are generic. They use the resolved Compass origin and regional
place index; they do not contain a Frankfurt, Leipzig, or Davao exception.

## Scoped Explore matching

**Save and run Match** is a single persisted background operation. It:

1. verifies and extracts the selected URLs;
2. discards closed or unusable sources;
3. evaluates route, company, and Compass evidence only for newly selected live
   records; and
4. reuses unchanged results from the latest current run.

The normal **Run Matching** action remains a full rerun across the current
Archive. If the Compass or matching algorithm changed, stale prior results are
not reused.

## Compatibility and privacy

- The v0.7.0c single-head Alembic migration repair remains included.
- Existing local SQLite data, `.env`, CV text, and `local-data` are preserved by
  the installer.
- The release archive excludes databases, profiles, API keys, `.env`, CV files,
  virtual environments, caches, and generated local data.
