> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1s-source-facts

S is a local-first source-correction and job-detail release. It keeps the R
provider mesh and matching model, but makes structured European locations
usable for distance ranking, repairs the configured JSearch path, and groups
job facts separately from employer facts.

## Explore providers

- EURES results whose source exposes a NUTS territorial code are resolved to a
  human-readable European region before display and proximity ranking. A raw
  code such as `DE724` or `SE232` is no longer presented as though it were a
  postal code.
- The resolver follows the official Eurostat NUTS 2024 hierarchy and uses the
  most-specific code supplied by EURES. If the resulting region cannot be
  mapped safely to a representative place, distance remains unknown instead of
  inventing a coordinate.
- OpenWebNinja JSearch uses its documented `search-v2` request contract and
  returns a useful, secret-safe diagnostic category when the service rejects a
  request.
- Provider diagnostics call the conditional Exa source simply **Exa**. Its
  internal provider identity and accounting remain unchanged.
- Every provider remains separately selectable by the account and separately
  represented in the operation ledger. A configured price of `0` means
  unpriced, never free.

## Job and employer facts

- Job relationship, **Your rating of this job**, salary orientation and posting
  date form one job-facts section. Employer identity, organisation type and
  reputation remain a separate employer-facts section.
- Employer-type choices use a compact, scrollable single-line list.
- The published application address is normalised and shown once.
- Add presents **Paste manual job text** before the final **Verify and save
  job** action.
- Home cards protect the match label from wrapping or collapsing when Remote
  and Fresh badges occupy a second line.

## Release identity

- Application: `0.7.1s-source-facts`
- Python package: `0.7.1+s.source.facts`
- Matching algorithm: `matching-v0.7.1o`
- Database head: `0030_verified_job_posters`
- ZIP: `betteroption_v0_7_1s_source_facts.zip`
- Git tag: `v0.7.1s-source-facts`

## Operating boundary

Run S only as the password-protected loopback application at
`http://127.0.0.1:8000`. This release does not approve a server or alpha
rollout. Hosted use still needs the recorded legal, processor, retention,
security, incident, backup/restore and launch decisions.

Use [the S local backup, install, acceptance and GitHub guide](../local-guides/local-source-facts-v0.7.1s.md).
