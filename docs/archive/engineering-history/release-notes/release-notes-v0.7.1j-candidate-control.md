> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1j-candidate-control

This local release makes the candidate's own judgement explicit without
weakening BetterOption's evidence boundary. It carries the complete
v0.7.1i workflow forward, remains supported only on
`http://127.0.0.1:8000`, and does not claim hosted/private-alpha or legal
readiness.

Application version: `0.7.1j-candidate-control`  
Python package version: `0.7.1+j.candidate.control`  
Matching algorithm: `matching-v0.7.1j`  
Release archive: `betteroption_v0_7_1j_candidate_control.zip`  
Git tag: `v0.7.1j-candidate-control`

## Employer rating and job rating

- **Employer rating** is one private 0–5-star judgement for a normalized
  employer. It follows that employer across jobs belonging to the active
  persona.
- **Job rating** is a second, independent private 0–5-star judgement for one
  exact saved vacancy. A positive company opinion therefore does not imply a
  positive opinion of every role, or vice versa.
- Both controls appear together on Job Detail. The exact-job rating also
  appears on every job card and can be changed directly there; the
  employer-wide value stays in Job Detail to avoid duplicating a company-wide
  control across every vacancy. Employer and job stars use distinct colors
  from the BetterOption site palette instead of generic yellow.
- `Unrated` means that no rating row exists. It is neutral, contributes zero
  points, and never blocks.
- An explicitly selected **0-star** rating is intentionally different from
  `Unrated`: employer 0 blocks all matching jobs for that normalized employer;
  job 0 blocks only that exact vacancy. Clearing the value returns it to the
  neutral `Unrated` state.
- Rating changes remain persona/account isolated, are included in the private
  account export, and mark affected stored results for an explicit rematch.

The deterministic score effects are published rather than learned:

| Rating | 0 | 1 | 2 | 3 | 4 | 5 | Unrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Employer | block | -16 | -8 | 0 | +4 | +8 | 0, neutral |
| Exact job | block | -12 | -6 | 0 | +4 | +8 | 0, neutral |

## Inspectable matching and candidate corrections

- Match results expose the actual mechanics for Compass boundaries and
  preferences, required-skill coverage, posting freshness, employer rating,
  job rating, and the evidence-confidence adjustment.
- Positive-capacity shares describe this configured deterministic algorithm;
  they are not statistical weights or predictions.
- Automatic employer relationship and company-product evidence remains
  immutable and visible. Persona-owned corrections form a separate effective
  layer used by the next match.
- One-job rematches preserve other saved match results and provider evidence.
  Saving a correction or rating does not itself hide the fact that a rematch is
  required.

Because employer and job ratings can now materially change or block a result,
stored I runs are stale under `matching-v0.7.1j` and should be rerun.

## Source-grounded application guidance

- Job ingestion can retain only application contact and process information
  explicitly present in the advertisement: contact name/role, email, phone,
  channel or URL, requested documents, file/page limits, deadline, and concrete
  submission instructions.
- Guidance is populated when the advertisement is extracted or its source is
  refreshed. Existing jobs saved under I are not silently backfilled and may
  show `Unknown` until they are refreshed or re-imported.
- Every source-derived value requires a verbatim evidence quote. Unverified
  model output fails closed; BetterOption never enriches a contact from social
  networks or unrelated pages.
- The active persona may correct a value, explicitly clear it, or restore all
  source-published values. Automatic provenance remains available for review.
- Only the effective, grounded guidance needed by an editable cover-letter
  draft is supplied to the application provider. Contact email, phone, and
  application URL stay visible in the local guidance tile but are scrubbed from
  the OpenAI cover-letter prompt; only contact name/role and text-relevant
  application rules may leave the local boundary. The full advertisement is
  not duplicated in that guidance block, and an absent contact is never
  invented.
- Local guidance is available by default. A hosted environment continues to
  fail closed unless both legal and processor review flags are explicitly set;
  this release does not authorize hosted use.

## Discovery and current opportunities

- Direct feeds and employer ATS sources retain their existing priority. Between
  otherwise equally relevant broad web results, Exa now precedes Brave.
- When Exa and Brave identify the same canonical job URL, the Exa copy is kept.
  A materially more relevant Brave result can still rank higher.
- Home's carousel contains every current Top and Stretch result and excludes
  blocked, rejected, and withdrawn jobs. Posting freshness remains visible,
  including old postings.

## Database and compatibility

Existing v0.7.1i databases migrate forward without a reset. J extends the
single Alembic chain from `0024_posting_date_evidence` through head
`0028_job_ratings`:

1. `0025_employer_reputation_scoring` stores explicit employer 0-star ratings
   and one-job rematch task links.
2. `0026_application_guidance` stores persona-owned corrections to application
   contact/process evidence.
3. `0027_context_evidence_overrides` adds the generic typed text layer for
   contextual machine-evidence corrections.
4. `0028_job_ratings` stores one explicit 0–5 rating per persona and saved job.

The migrations are additive, but an older code checkout must not write a J
database. Rollback requires both older source and the corresponding pre-J
database backup; the local guide uses a separate checkout so the accepted J
worktree is not destroyed.

## Provider permissions and cost accounting

J introduces no provider and requires no new API key. Existing keys remain
private in `.env`. Job/application prompt contracts changed and are recorded as
`job-v0.7.1j` and `application-draft-v0.7.1j`; unchanged profile and salary
prompts retain their own earlier contract versions.

The environment remains the installation-wide availability ceiling and the
signed-in account remains the permission boundary for all of its personas:

- a disabled provider is not called and creates no provider-operation or cost
  entry;
- an enabled provider call remains attributable to its provider and purpose;
- numeric provider-price settings must contain a number, never a blank value;
- explicit `0` is the safe placeholder while a price is uncalibrated, and such
  usage is shown as **used but unpriced**, never free;
- daily/action cost-limit values of `0` disable those monetary guardrails and
  are limits, not price estimates. Operation-count limits remain separate.

The automated release tests use fakes and do not consume provider budget.

## Release gate

The focused J gate covers release/package identity, prompt and User-Agent
versions, dual-rating persistence and score effects, application-guidance
provenance, the linear migration head, one-job rematching, and discovery
tie-breaking. Run the complete local gate before the Git tag:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

See [Local candidate control for v0.7.1j](../local-guides/local-candidate-control-v0.7.1j.md)
for backup, exact install, acceptance, no-pager GitHub, and rollback commands.
