> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1f-general-salary-ui

`v0.7.1f-general-salary-ui` keeps the account, persona, Add and Apply model from
v0.7.1e and corrects one product-level generalisation error: salary orientation
must work for different kinds of candidates rather than encode the first
developer's occupation list. It also cleans up four visible workflow details
found during real local use.

Application version: `0.7.1f-general-salary-ui`  
Python package version: `0.7.1+f.general.salary.ui`  
Release archive: `betteroption_v0_7_1f_general_salary_ui.zip`  
Database head: `0019_application_drafts`
Terms/Privacy engineering-draft version: `2026-08-01-draft`

## Occupation-agnostic salary orientation

- Salary evidence stated by the advertisement always wins. BetterOption does
  not replace an advertised amount with a market estimate.
- Missing pay is treated as missing evidence, not as permission to invent a
  number. The estimator first identifies the occupation from the available job
  evidence and uses attributable public benchmark evidence only when the match
  is sufficiently supported.
- The approach is occupation-agnostic: it is not restricted to software,
  embedded, electrical or other engineering jobs.
- The first shipped research adapter is country-aware for European vacancies.
  Its current allowlist contains official EU or national
  statistical/employment sources only. The architecture can admit reviewed,
  corroborated secondary evidence later, but none is enabled in this release.
- Its bounded source basis includes Eurostat Structure of Earnings Survey and
  EURES evidence, national sources such as the Bundesagentur für Arbeit, and an
  attributable ECB reference when a currency conversion is needed. Source
  availability varies by country and occupation.
- Country, currency, pay period, source attribution, assumptions and confidence
  stay explicit. A German benchmark can never be applied to a job abroad.
- Non-EUR normalization requires a consulted ECB reference rate whose quoted
  currency, value and date agree with the structured evidence. Future rates and
  rates older than 31 days are rejected.
- This is bounded European orientation, not a claim of comprehensive coverage
  for every country and occupation. Unsupported European and non-European roles
  abstain.
- If the occupation or evidence cannot be mapped responsibly, BetterOption
  abstains and leaves salary unknown.
- An estimated range remains market orientation—not compensation advertised by
  the employer, not a promise, and never a reason to hard-block a job.

Research is an explicit opt-in through
`BETTEROPTION_SALARY_RESEARCH_ENABLED=true`. It performs at most one bounded
OpenAI Web Search batch per Match and only when the active Compass has a pay
criterion and the advertisement omits pay. The payload contains public job
title, resolved country/coarse workplace, summary and limited public
role/employment facts; it does not contain the profile or target salary.
`BETTEROPTION_SALARY_RESEARCH_MAX_JOBS` is bounded from 1 to 25, an optional
`BETTEROPTION_SALARY_RESEARCH_MODEL` can override the shared model, and the
numeric `BETTEROPTION_SALARY_RESEARCH_ESTIMATED_COST_PER_CALL_USD` records the
operator's current per-call estimate. Before a batch, the cost guard reserves
that value multiplied by `BETTEROPTION_SALARY_RESEARCH_MAX_TOOL_CALLS`; `0`
means unknown/unpriced, not free.

The matching algorithm identity is now `matching-v0.7.1f`. Existing match
snapshots remain readable, but the interface marks an older run as stale so the
new salary logic is used only after the user deliberately runs Match again.

## Interface corrections

- Apply presents each selectable job as one aligned, readable checkbox row
  instead of distributing the checkbox and job text across the card.
- Job Detail places the cover-letter action with the application workflow
  rather than letting it interrupt the current-state controls.
- Persona cards visibly separate the persona name from its creation date.
- Archive and Match cards in `Rejected` or `Withdrawn` state receive a muted,
  semi-transparent diagonal grey stripe treatment in addition to their state
  colour, making completed paths unmistakable without hiding the text.

## Persistence and upgrade boundary

No database migration is required. The Alembic head remains
`0019_application_drafts`; accounts, personas, Compass data, jobs, matches,
drafts and interaction history are preserved. Salary orientation is serialized
inside each match-result snapshot. A compatibility check protects v0.7.1e
salary snapshots from becoming unreadable.

Back up `local-data/betteroption.db` before installing anyway. That preserves a
single-step rollback boundary for source and stored match snapshots.

## Operating status

This remains a loopback-only local tool. It does not deploy a server, submit an
application, email an employer, publish candidate data or declare the legal
package ready for a private alpha. The existing legal and processor-review
gates remain unchanged.

Use the complete Windows, acceptance and private-GitHub cycle in
[Local upgrade and GitHub cycle for v0.7.1f](../local-guides/local-general-salary-ui-v0.7.1f.md).
