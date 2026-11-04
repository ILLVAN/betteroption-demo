> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1a1 — Test authentication repair

v0.7.1a1 is a narrow regression-test patch over v0.7.1a. Product authentication
remains unchanged and account mode remains the secure application default.

## Root cause

Account authentication became the default in v0.7.0. Older dashboard, Compass,
job, matching, CV, background-task, and operations tests still created isolated
clients without declaring an authentication mode. Protected requests therefore
redirected to `/login`.

Many later errors were only consequences of that redirect: tests parsed
`/login` as a profile URL, expected a job redirect, or looked for saved match
data that the unauthenticated request had never created.

## Repair

- Legacy single-workspace feature fixtures now explicitly set
  `auth_mode="local"`.
- Account, session, tenant-isolation, export, legal-acceptance, and deletion
  tests continue to use account mode and real isolated accounts.
- No common pytest password, global account, authentication bypass, or relaxed
  production default was added.
- The versioned asset URLs and release identity were advanced to v0.7.1a1.

## Verification

- All tests pass together.
- Ruff formatting and linting pass.
- Python bytecode compilation passes for `src`, `examples`, `scripts`, and
  `tests`.
- The release archive continues to exclude `.env`, credentials, databases,
  uploads, CV text, profiles, and local runtime data.
