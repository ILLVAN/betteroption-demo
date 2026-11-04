> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1i-evidence-workflow

This local release refines the tested v0.7.1h workflow. It does not open a
server, change provider permissions, or claim private-alpha/legal readiness.

## Apply handoff

- Job Detail preselects only the requested job in Apply without hiding the
  other eligible jobs.
- All existing job draft groups remain available and collapsed. If the target
  already has drafts, its group opens; if it has none, no unrelated group is
  opened.
- Existing draft deep links still open the requested draft.

## Home and navigation

- Rejected and withdrawn jobs no longer appear under Home's current
  opportunities. They remain available in their traceable job/application
  history.
- Add now precedes Explore, matching the intended optional-portal-first user
  journey.
- Application-state watermarks are slightly larger, clearer, and positioned
  above the state controls. Rejected/withdrawn terminal styling remains muted.

## Candidate-controlled evidence

- A required skill can be explicitly added to the active persona's confirmed
  Compass. This is deliberately limited to the required-skills section because
  a demonstrated skill is reusable across jobs.
- Private employer ratings use 0–5 stars. A rating follows a normalized employer
  across the current persona's jobs, remains isolated from other personas and
  accounts, and can be cleared with `Unrated`.
- Employer ratings are included in the account data export and removed with the
  owning persona/account.

## Posting-date evidence

- Explicit posting dates are extracted from supported structured facts and
  clearly labelled English/German source text, including labelled relative
  dates.
- The import/observation timestamp is never substituted for a missing posting
  date. Missing and future dates remain `Unknown`.
- Fresh is newer than one calendar month; Medium is one through four calendar
  months; Old is older than four calendar months.
- Score influence is intentionally bounded: Fresh `+2`, Medium/Unknown `0`, Old
  `-4`. Posting age never creates a hard violation.
- A persona can correct the date for one job, restore the automatic value, and
  explicitly rematch that job. The correction survives later full match runs.

## Compact traceability

- Employer, company, salary, commute, Compass, and skill evidence keep their
  essential value/status/confidence visible.
- Long explanations, quotes, assumptions, diagnostics, and source links are
  collapsed by default and remain available on demand.
- User edit controls are smaller, and required-skill colors now follow the
  effective evidenced/not-evidenced state.

## Data and compatibility

- Migration `0023_employer_reputation_ratings` adds persona-owned company
  ratings.
- Migration `0024_posting_date_evidence` adds typed posting-date overrides.
- Existing H databases migrate forward; no reset is required.
- Provider enablement and operational cost accounting remain as in H: disabled
  providers are not called; enabled calls with price `0` are used but unpriced,
  never recorded as free.
