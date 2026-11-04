> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Job Corpus Contract v0.1

## Purpose

The corpus turns one-off URL extraction into durable product state. It is the
service boundary that the first FastAPI dashboard will use for importing,
refreshing, listing, and matching jobs.

## Persistence architecture

The local default is `sqlite:///local-data/betteroption.db`. SQLAlchemy 2.x
keeps repository consumers independent of the database backend so production
can move to PostgreSQL without changing matching or ingestion services.
Alembic owns schema evolution from v0.6.2 onward. On first startup, an intact
v0.6.0 database is adopted at the baseline revision and upgraded in place; job
records, revisions, aliases, and observations are retained.

The schema separates four concepts:

- **Job record:** stable identity, canonical URL, availability, and the current
  revision pointer.
- **URL alias:** normalized requested or redirected URL mapped to one record.
- **Job revision:** append-only canonical `JobPosting` JSON for one observed
  content version.
- **Observation:** append-only result of every URL check.

The repository exposes records, revision history, observation history, current
canonical jobs, and live jobs. Web routes must use this repository rather than
querying SQLAlchemy rows directly.

## Identity and deduplication

URL normalization lowercases scheme and host, removes fragments, removes common
tracking parameters, sorts the remaining query parameters, and retains job
identifiers. Redirect destinations and requested URLs are stored as aliases.

The fetched job text is SHA-256 hashed. If the hash equals the current revision,
the corpus records an `unchanged` observation and updates link-verification
metadata inside the cached job without an LLM call. Different content creates a
new revision.

## Lifecycle semantics

Availability and observation kind are separate:

- Availability is `live`, `expired`, `unreachable`, or `needs_attention`.
- A successful observation is `new`, `unchanged`, or `changed`.
- A failed observation is `expired`, `unreachable`, or `extraction_failed`.

HTTP 404/410 and recognized expired-job pages are expired. Network errors,
blocked automation, unsupported pages, and other inaccessible sources are
unreachable. A reachable page whose evidence extraction fails needs attention.
A later successful refresh restores any of these records to live.

Historical revisions are never deleted by a failed availability check.

Explicit user deletion is different from a failed check. In the private-alpha
free workspace, the archive stores at most 25 records. A 26th new URL is
rejected before network or model work, while an already known URL can still be
refreshed. After confirmation, deleting one selected record removes its aliases,
revisions, observations, matching/interaction rows, related reference settings,
and targeted local source/canonical copies. The deletion frees one slot.

## Presentation safety

Only live records with a canonical revision may be matched. The application
service rechecks live links older than 24 hours before presentation. A forced
refresh also retries expired and unreachable records.

Every real `MatchResult` still contains the resolved URL, successful HTTP status,
and verification time. Reusing an unchanged extraction refreshes these fields,
so the result never presents an old verification timestamp as a new check.

## Cost behavior

- First content version: one LLM extraction, with one correction retry only if
  evidence cannot be mapped.
- Unchanged content: zero LLM calls.
- Changed content: one new extraction and revision.
- Failed URL check: zero LLM calls.

## Current limitations

- URL checks do not bypass authentication, robots rules, anti-bot controls, or
  unsupported JavaScript-only sources.
- Corpus-level operator corrections and gold-set labels are planned before the
  public release.
