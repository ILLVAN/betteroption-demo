> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1m-local-readiness

This release rebuilds the intended L changes on the accepted
`v0.7.1k-local-evidence` baseline and gives them a new, unambiguous M release
identity. It remains a candidate-controlled job-search tool for
`http://127.0.0.1:8000`. The implementation keeps a later server deployment
possible, but this release does not authorize a server rollout, public bind,
tunnel, DNS record, or private alpha.

Application version: `0.7.1m-local-readiness`

Python package version: `0.7.1+m.local.readiness`

Matching algorithm: `matching-v0.7.1m`

Release archive: `betteroption_v0_7_1m_local_readiness.zip`

Git tag: `v0.7.1m-local-readiness`

## Manual jobs can be matched safely

A manually pasted advertisement remains a distinct manual source even when the
candidate adds an optional citation URL. M carries that provenance into the
stored match result and no longer requires URL-verification metadata for this
source type. This fixes the `match URL verification metadata must be complete`
validation failure.

Manual source URLs remain citations only: BetterOption does not fetch, refresh,
or silently promote the pasted text to verified live-URL evidence. Live URL
import remains a separate, deliberate workflow. Ordinary URL jobs still fail
closed if their verification metadata is incomplete.

## Broader but bounded Explore

- A normal Explore request now asks for up to 150 ranked candidates; an explicit
  request can raise the ceiling to 180.
- The shared provider-search budget remains capped at 120 seconds. The complete
  browser workflow can take slightly longer for persistence and rendering, so
  this is a provider-work budget rather than a hard end-to-end stopwatch.
- Existing coarse vacancy, URL, deduplication, location, quality, and ranking
  checks remain in front of the displayed result set. A larger ceiling does not
  turn generic search pages into accepted vacancies.
- Exa wins an otherwise equal fallback tie and its copy is retained when Exa
  and Brave identify the same canonical vacancy URL. A materially better Brave
  vacancy can still outrank a weaker Exa candidate.

The larger limit is a ceiling, not a promise that every search will find 150
usable live jobs. Save/Match continues to perform the deeper verification and
extraction step.

## Freshness and matching calibration

Known posting dates younger than one calendar month now receive a compact
**Fresh** badge on job cards. Dates older than four calendar months use the
short **Old** badge. Medium-age and unknown dates remain visible in Job Detail
without adding another card badge.

The positive-fit calibration is slightly stricter than K: independently
corroborated positive signals can add at most three points instead of four.
Explicit must-have or exclusion violations still block according to the
published deterministic rules, and an explicit 0-star job or employer rating
still blocks its defined scope. M does not manufacture a blocker merely because
evidence is missing.

## More useful application contact evidence

- The deterministic application-guidance layer now retains a source-published
  postal application address in addition to a contact name, business role,
  email address, phone number, application channel, requested documents,
  limits, deadline, and instructions when the supplied job source supports it.
- Findings remain bound to the exact advertisement or official careers source,
  with evidence and provenance. Missing details stay unknown; BetterOption does
  not enrich a person from private profiles, unrelated pages, or inferred
  gender.
- Extraction and display happen inside the BetterOption application boundary.
  Detected contact names, identifying roles, email addresses, phone numbers,
  postal addresses, and delivery URLs are removed from OpenAI job-extraction
  and cover-letter prompt surfaces. The candidate adds or selects the reviewed
  salutation locally.
- BetterOption never contacts an employer or submits an application.

Deterministic minimisation reduces disclosure but cannot prove that arbitrary
free text contains no indirect identifier. That residual risk is one reason an
external alpha remains a separate reviewed decision.

## Resolved employer identity and private shared context

Employer-wide data is now keyed only after BetterOption has a specific,
rateable employer name. Generic values such as `Unknown` or source placeholders
do not share ratings or notes and cannot mix unrelated companies.

The candidate can correct the company name on Job Detail. Once a specific name
is saved, its normalised identity can connect that persona's private employer
rating and latest private employer context across other jobs for the same
employer. The context remains a candidate-authored note, is labelled as such,
and is not a provider finding or an automatic Compass fact. It stays isolated
by account and persona.

Company product corrections and private employer context use compact one-line
fields. They are useful as explicit matching context and remain reviewable
beside the immutable automatic evidence.

## UI refinements

- Job Detail returns to the clearer wide evidence column plus narrow action
  rail. Inside evidence cards, values use natural horizontal groups rather than
  table-like micro-columns that forced one-word line breaks.
- Job cards combine both controls under **Your Ratings**: the exact **Job**
  rating appears on the left and the resolved **Employer** rating on the right.
  Unrated remains neutral; a missing employer identity leaves the employer-wide
  control unavailable rather than attaching it to a placeholder.
- Application-state artwork is positioned higher so it does not overlap
  **See evidence** or the state control.
- **Fresh** and **Old** use the existing BetterOption palette and concise
  wording.

## Data model and compatibility

M adds no Alembic migration. The single migration head remains
`0028_job_ratings`, so an accepted K database opens without a reset or schema
upgrade. Accounts, personas, jobs, drafts, ratings, provider permissions,
private corrections, and cost records remain in place.

M does extend versioned JSON/domain contracts. Job and application prompt
contracts are `job-v0.7.1m` and `application-draft-v0.7.1m`; stored match runs
use `matching-v0.7.1m`. Keep the verified pre-M database and local-data backup
for rollback rather than letting older source rewrite M-created records.

## Legal readiness is not legal approval

M implements a conservative product boundary: candidate-controlled
recommendations, no employer/recruiter profile access, no automated application
or employment decision, no use of real profiles for model training, local
contact extraction, visible provenance, user correction, provider controls,
and explicit unknown states. The legal pages describe the implemented data
flows and the readiness checks warn about unresolved external-operation work.

These engineering controls do not constitute legal advice, a completed DPIA,
or approval to host the product. Before an external alpha, the operator still
has to document and review at least:

- controller identity, purposes, data categories, Article 6 lawful bases, and
  any legitimate-interest assessment, including the use of source-published
  business contact data;
- Articles 13/14 transparency, retention/deletion, data-subject requests, the
  record of processing activities, security measures, and the incident and
  72-hour breach procedure;
- whether an Article 35 DPIA is required and the documented reasons for that
  conclusion;
- every enabled processor, DPA, subprocessor, processing location,
  international-transfer mechanism, retention option, deletion capability, and
  security contact;
- the EU AI Act intended-purpose assessment. Employer/recruiter access,
  recruitment ranking on their behalf, automated selection, or automated
  application would materially change the current candidate-only boundary and
  require a new assessment;
- backup/restore evidence, access control, monitoring, operational retention,
  real operator details, and qualified review of the final notices and terms.

Warnings permit honest local development; they are not switches that convert
an incomplete review into compliance. No server deployment procedure is
included in this release.

## Providers and cost accounting

M introduces no provider and needs no new key. Account-level provider choices
continue to apply to every persona. A disabled provider creates neither a call
nor a provider-cost record. Enabled usage remains attributed by provider and
purpose.

Numeric provider prices must contain a number, never a blank value. Explicit
`0` means **used but unpriced**, not free. Explore's larger ceiling can increase
usage when paid search providers are enabled, so retain the provider-side
monthly limits and review the Operations ledger after acceptance.

## Release gate

The complete local gate remains:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

See [v0.7.1m local backup, install, acceptance, and GitHub cycle](../local-guides/local-readiness-v0.7.1m.md)
for the exact SQLite backup, ZIP overlay, loopback acceptance, guarded GitHub
push, tag, and rollback. There is intentionally no server deployment section.
