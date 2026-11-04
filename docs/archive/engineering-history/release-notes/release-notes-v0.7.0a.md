> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0a release notes

v0.7.0a is a focused account and configuration correction on top of v0.7.0.
It does not change discovery, matching, mobility, or the accepted user interface.

## Account page correction

The authenticated Account page now receives stable statement counts from the
web adapter. Its template no longer reaches through the profile-repository
object graph, which fixes the `ProfileWorkspace has no attribute profile`
failure for both claimed legacy workspaces and newly created accounts.

An authenticated browser regression test opens `/account` and verifies the
saved-job, confirmed-statement, and open-statement metrics.

## Configuration clarity

The default provider guardrails now accommodate a complete 25-job private-alpha
workflow more realistically:

- 1,000 provider operations per UTC day;
- 200 provider operations per correlated workflow.

A value of `0` still disables the corresponding operation or cost rail.
Production values remain an operator decision and should be paired with
provider-side billing limits.

Run the new secret-safe diagnostic after editing `.env`:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

It reports effective modes, configured-provider presence, routing and worker
settings, guard values, and duplicate `.env` assignments. It never prints API
keys, tokens, passwords, request content, or database credentials. When a key
appears more than once, the last assignment is effective.

For an existing first account, keep exactly one
`BETTEROPTION_REGISTRATION_MODE=disabled` line. Use `first_user` only for the
one-time initial ownership claim, and use `open` only in an intentionally
controlled multi-user test.
