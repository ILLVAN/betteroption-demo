> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1k-local-evidence

This local release tightens the application-data boundary and makes missing
evidence easier for the candidate to resolve. It carries the complete
v0.7.1j candidate-control workflow forward, remains supported only on
`http://127.0.0.1:8000`, and does not authorize a server rollout, tunnel,
public bind, or private alpha.

Application version: `0.7.1k-local-evidence`

Python package version: `0.7.1+k.local.evidence`

Matching algorithm: `matching-v0.7.1k`

Release archive: `betteroption_v0_7_1k_local_evidence.zip`

Git tag: `v0.7.1k-local-evidence`

## Local application contact and process evidence

- Contact and application-process extraction remains deterministic and
  local/server-side. The source advertisement, not an OpenAI response, is the
  authority for contact names, roles, email addresses, phone numbers,
  application links, requested documents, size/page limits, deadlines, and
  submission instructions.
- The deterministic extractor recognizes source-grounded multilingual patterns,
  including common German, English, and French contact and application wording.
  Every retained value keeps a verbatim evidence quote and provenance; it does
  not enrich a person from social networks, search results, or unrelated pages.
- Contact identity and delivery coordinates are withheld from the OpenAI job
  extraction prompt. The cover-letter prompt also excludes names, identifying
  roles, honorifics, email addresses, phone numbers, and application URLs from
  the job, guidance, and existing-draft surfaces.
- OpenAI is instructed to use the literal `[LOCAL SALUTATION]`, a neutral team
  greeting, or no greeting. A returned personal or gendered salutation is
  removed again locally. The candidate can insert the locally displayed,
  verified contact after reviewing the editable draft.
- Non-identifying, source-published process rules may still be supplied when
  they are useful to the draft. Missing contacts remain missing; BetterOption
  does not invent a recipient or submit an application.

## Pasted jobs remain pasted jobs

A manually pasted advertisement is a distinct, local source type even when the
candidate supplies an optional source URL. BetterOption extracts and stores the
text that was pasted but never requests, refreshes, or re-verifies that URL.
Bulk refresh and presentation checks preserve the manual revision unchanged.
Replacing it with a live URL import must be a separate, deliberate action.

This closes an important provenance ambiguity: an optional citation for pasted
text can no longer be mistaken for a network-verified current advertisement.

## Wider, actionable evidence review

- Contextual evidence, employer relationship, company profile, reputation
  context, salary, posting date, commute, work model, Compass comparisons, and
  required skills retain the automatic value on the left and the candidate's
  private effective value on the right.
- Missing automatic findings now expose restrained grey, actionable defaults
  instead of looking like completed provider evidence. They are editing prompts,
  not facts, and do not become effective until the candidate changes and saves
  them.
- Changed fields are saved together through one sticky bulk action. Automatic
  source evidence remains immutable and visible, and a one-job rematch keeps
  unrelated saved results.
- Required skills marked **I can do this** can be added to the active persona's
  confirmed Compass in the same bulk save. This option is enabled by default;
  marking a skill as not evidenced never removes a Compass fact.
- Employer relationship choices now cover direct employer, staffing agency,
  recruitment agency, freelance engagement, contractor engagement,
  intermediary, talent/freelance platform, consultancy, other, and unknown.
  Only the categories that actually establish a direct or agency relationship
  make that claim; nuanced categories remain non-conclusive.

## Compass compensation range

Compass exposes one typed annual-gross EUR range from `0` to `200000`:

- `0` minimum and `200000` target is the neutral default and creates no salary
  constraint.
- A non-zero minimum becomes the matching-visible must-have boundary.
- A target below `200000` becomes a matching-visible preference.
- The dedicated range editor and guided Compensation answers update the same
  structured profile fields and confirmed facts instead of creating parallel
  salary concepts.
- Existing profiles without structured salary values project safely to the
  neutral full range; stored values remain readable.

## Conservative positive-fit calibration

The deterministic matcher adds a tightly bounded calibration for a result with
several independently corroborated positive signals:

- each satisfied hard requirement, supporting preference, or matched required
  skill contributes one point;
- the combined lift is capped at `+4`;
- any hard-requirement or exclusion violation disables the lift;
- 0-star blockers, employer/job rating adjustments, posting freshness, and the
  evidence-confidence adjustment remain independent and unchanged.

The section appears in the published score mechanics as **Corroborated
positive-fit calibration**. It is an explicit rule, not a learned prediction,
and cannot turn a blocked job into a match.

## Database and compatibility

K adds no Alembic migration. The single migration head remains
`0028_job_ratings`, so an accepted J database opens in K without a reset or
schema upgrade. Existing accounts, personas, jobs, ratings, drafts, corrections,
provider permissions, and cost records remain in place.

K does extend versioned JSON/domain data with compensation-range and manual-text
provenance fields. A downgrade should therefore use the verified pre-K backup
rather than letting older source write K-created data. The local guide uses a
separate worktree and backup for rollback.

Job and application prompt contracts are now `job-v0.7.1k` and
`application-draft-v0.7.1k`. The matching identity is
`matching-v0.7.1k`, so rerun Match to compare stored J results under the K
calibration.

## Release-archive privacy

The source release continues to exclude runtime data, `.env`, API keys,
databases, `local-data`, uploads, backups, and caches. K also rejects likely
CV/resume artifacts and unapproved PDF or office-document files during package
selection. Documentation that is deliberately allowlisted remains included.

## Providers and cost accounting

K introduces no provider and requires no new key. Existing account-level
provider choices continue to apply to all personas. A disabled provider creates
no call or provider-cost record; an enabled call remains attributable to its
provider and purpose.

Numeric provider prices must contain a number, never a blank value. Explicit
`0` remains the safe placeholder for an uncalibrated price and is reported as
**used but unpriced**, never free. The automated tests use fakes and consume no
provider budget.

## Release gate

Run the focused K checks and the complete local gate before creating the Git
tag. The complete gate remains:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

See [v0.7.1k local install, acceptance, and GitHub cycle](../local-guides/local-evidence-v0.7.1k.md)
for the verified backup, exact ZIP install, loopback acceptance, no-pager review,
guarded GitHub push, tag, and recoverable rollback. There is intentionally no
server deployment section.
