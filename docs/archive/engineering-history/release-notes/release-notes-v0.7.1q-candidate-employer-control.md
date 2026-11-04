> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1q-candidate-employer-control

Q is a localhost product-control release. It keeps the candidate workspace as
the primary product and prepares a separate, verified employer-posting boundary
without authorizing a hosted rollout.

## Candidate workflow

- Main actions use the same borderless gradient strip inside a calm standard
  surface across Home, Compass, Add, Explore, Match, Apply, Archive and Job
  Detail.
- Saving explicit evidence corrections updates the deterministic score from
  stored evidence. It does not repeat route, salary, employer or LLM research.
  A deliberate full single-job rematch remains available for stale evidence.
- Salary inputs use `0`–`300k` in `1k` steps. An untouched target is neutral;
  only an explicit target becomes a preference, while an explicit minimum is a
  hard boundary.
- The candidate's job signal teaches Compass by default, repeated help text is
  collapsed, and satisfied/I-can-do corrections use the satisfied visual state.
- Cover-letter shortening has a deterministic reduction target, while every
  draft remains editable and is never submitted automatically.

## Discovery, employer identity and application evidence

- Explore can issue bounded German and English query variants for a German job
  search while retaining exclusions, provider permissions, cost accounting,
  ranking and URL safety checks.
- Employer identity resolution uses attributable source and employer-domain
  evidence. Generic ATS, aggregator and unknown labels are not merged into one
  employer identity.
- Prepare Package shows only source-published application details or the user's
  private correction. Contact data is never guessed, sent to OpenAI, or used to
  contact an employer automatically.

## Verified employer-posting preparation

- Normal accounts can request job-poster access outside candidate navigation.
- An operator must review the company name, website and work-email boundary.
- Only an approved account can create and publish a first-party job; published
  jobs enter the same candidate-controlled discovery and evidence flow.
- Hosted use fails closed unless the explicit employer-posting flag, legal
  review, incident plan and operator configuration are all ready.

This is an architectural preparation, not a legal approval, marketplace launch,
or invitation to employers.

## Release identity

- Application: `0.7.1q-candidate-employer-control`
- Python package: `0.7.1+q.candidate.employer.control`
- Matching algorithm: `matching-v0.7.1o`
- Database head: `0030_verified_job_posters`
- ZIP: `betteroption_v0_7_1q_candidate_employer_control.zip`
- Git tag: `v0.7.1q-candidate-employer-control`

## Operating boundary

Run Q only as the password-protected loopback application at
`http://127.0.0.1:8000`. Do not deploy it to a server yet. A later hosted pilot
still needs final controller information, notices and terms, RoPA/lawful-basis
work, DPIA decision, processor and transfer review, retention/DSR/incident
procedures, security and backup-restore evidence, job-poster moderation rules,
and a final launch review.

Use [the Q local backup, install, acceptance and GitHub guide](../local-guides/local-candidate-employer-control-v0.7.1q.md).
