> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1p-local-stability

v0.7.1p is a focused localhost stability release over v0.7.1o. It does not
expand the deployment boundary or change the database schema.

## Fixed

- Apply and Job Detail no longer fail when one schema.org source line contains
  several workplace addresses. Distinct addresses remain available, while the
  identical source quote is stored only once and every hydrated job is fully
  revalidated before it reaches the web layer. The source-only provenance
  boundary remains enforced.
- Private salary-range corrections keep `SalaryEstimate.evidence` as a typed
  tuple. Matching results therefore serialize without the Pydantic
  `Expected tuple[SalaryEvidence, ...]` warning.
- Job Detail always keeps its expected-salary section visible after Matching.
  If no attributable or AI-assisted orientation exists, it shows an explicit
  unknown state and editable private min/max fields instead of hiding the
  section or inventing a number.
- You.com Search accepts the documented `results.web` response and optional
  `contents.markdown` page content, plus successful Markdown link responses.
  Parsed candidates still pass the existing URL, error-landing and individual
  vacancy gates; malformed responses fail closed.
- Home keeps Job and Employer as equal rating columns while placing each full
  star group on its own line, so the narrower carousel cards no longer squeeze
  one rating differently from the other.

## Compatibility and traceability

- Application: `0.7.1p-local-stability`
- Python package: `0.7.1+p.local.stability`
- Matching algorithm: `matching-v0.7.1o` (unchanged scoring semantics)
- OpenAI prompt versions: `job-v0.7.1o`, `application-draft-v0.7.1o`,
  `salary-research-v0.7.1o` (unchanged prompts)
- Database head: `0029_job_detail_preferences` (no P migration)
- ZIP: `betteroption_v0_7_1p_local_stability.zip`
- Git tag: `v0.7.1p-local-stability`

Keeping the matching and prompt versions unchanged is deliberate: P repairs
validation, parsing, serialization and presentation but does not silently
change a score formula or OpenAI instruction.

## Operating boundary

The supported mode remains the password-protected loopback application at
`http://127.0.0.1:8000`. No server deployment or external alpha is authorized
by this release. Account provider permissions, request limits and the operation
ledger remain active. A numeric provider price of `0` means used but currently
unpriced, never free; blank numeric price values remain invalid.

Use [the complete local backup, install, acceptance and GitHub guide](../local-guides/local-stability-v0.7.1p.md).
