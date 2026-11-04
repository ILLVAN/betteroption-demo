> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Job and Matching Contract v0.1

## Purpose

This increment proves the next end-to-end boundary: one confirmed candidate
profile can be compared with canonical, source-backed job advertisements. It
does not yet discover jobs on the public web.

## Canonical job record

Every real job begins with a user- or operator-supplied URL. It keeps the
requested URL, resolved URL, successful HTTP status, verification time,
complete fetched source text, observation time, content hash, and atomic facts.
Each fact has:

- an intent-neutral semantic key;
- a concise normalized value;
- a kind: requirement, preference, offer, or context;
- a verbatim quote that must occur in the source text.

Typography and whitespace differences are resolved back to an exact source
span. Invalid evidence triggers one correction request. Facts that remain
unsupported are omitted and recorded as warnings; they can never influence
matching.

## Extraction boundary

An LLM may convert text fetched from a supplied job URL into the canonical
record. Copied advertisement text is not a product input. The advertisement is
treated as untrusted data and cannot instruct the model, change the schema, or
determine candidate fit. Missing conditions remain unknown. The extractor never
invents salary, remote work, culture, or benefits.

The local alpha fetches only an explicitly supplied public URL. It prefers
schema.org `JobPosting` JSON-LD and otherwise extracts visible article text.
The fetcher accepts only HTTP(S), blocks local/private/reserved network targets,
validates every redirect, honors `robots.txt`, restricts content types and
download size, detects common expired-job pages, and never bypasses
authentication or access controls. A source that blocks access or requires
unsupported JavaScript is rejected with an explicit error.

Each real result and saved match record contains the resolved job URL and its
verification time. Only a recently fetched, successful response enters the
current URL-driven match command. External availability can change later, so
future corpus runs must recheck stale links before presenting them.

## Persistent corpus boundary

The v0.6 repository stores a stable job record separately from its canonical
content revisions and URL-check observations. The first URL import creates a
revision. An unchanged source hash refreshes availability without another LLM
call. Changed source text creates a new revision; earlier revisions remain
available. Expired and unreachable records retain their history but are not
eligible for active matching.

Job URL identity removes fragments and common tracking parameters while
preserving job-specific parameters such as ATS identifiers. Requested and
redirected URLs become aliases of the same record.

## Deterministic matching

The LLM does not score jobs. Python applies confirmed profile facts:

- Must-have facts are satisfied, violated, or unknown from job evidence.
- Exclusions are violated only when the advertisement contains the excluded
  characteristic; explicit absence can satisfy an exclusion.
- Preferences add ranking support but never filter by themselves.
- Required skills are compared with confirmed candidate evidence.
- Missing advertisement information is unknown, never a silent violation.

Every decisive reason returns the exact advertisement quote that produced it.

Compatibility and hard-evidence coverage are separate. A highly relevant job
can still have low evidence coverage when the advertisement omits salary,
contract, work model, culture, or exclusions. Missing evidence remains visible
but does not subtract compatibility. Supported role and direction evidence,
required-skill overlap, and proven hard conflicts determine the compatibility
score. A job with no supporting evidence remains a neutral Stretch result and
cannot become Top merely because unknowns are neutral.

## Result groups

- **Top Match:** no hard violation, sufficient score, and at most one unknown
  Must-have.
- **Stretch:** one hard violation, lower evidence coverage, or multiple unknown
  Must-haves. The reason remains visible.
- **Blocked:** at least two hard violations. Blocked jobs remain visible in the
  alpha so false filters can be diagnosed.

The current score is deliberately provisional. It is a transparent test
instrument for the gold set, not a claim of statistical relevance.

## Persisted web results

From v0.6.5 onward, web match runs are stored in the database with the exact
profile and canonical job snapshots used. Page refreshes reuse that immutable
run. Profile or job changes make the prior presentation stale; they do not
rewrite its evidence.

Up to 25 stored jobs receive durable free-access grants per profile workspace.
The private-alpha free workspace also stores at most 25 job records, so all stored
Top/Stretch results can be inspected without an email gate. Rerunning does not
reset or expand the allowance. Deleting a job removes its grant and frees its
storage slot. Blocked results remain inspectable to make exclusion behavior
debuggable. Feedback and application changes are separate, explicit user
signals with append-only event history and cannot mutate the confirmed profile
automatically.

From v0.6.6 onward, every saved run stores its matching algorithm version.
Earlier results remain immutable and are marked for rerun when their scoring
version is no longer current.

Confirmed modal commute limits may be evaluated from provider-backed road,
public-transit, bicycle, or walking durations. Route estimates are cached by
private profile workspace, job, mode, and normalized query. Missing origin,
missing destination, provider failure, and unavailable routes remain unknown.
Only a calculated duration can satisfy or violate a limit.
