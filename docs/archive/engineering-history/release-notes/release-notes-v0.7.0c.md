> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.0c — Overlay and migration repair

This patch is intentionally small.

- The obsolete `tests/test_v070a.py` path now contains current account and
  session regression tests.
- The former `0012_accounts_and_tenants` and
  `0013_background_job_imports` branch is retained as a compatibility path and
  joined to the current Alembic chain.
- Existing experimental account data is migrated to the current account model
  on supported local SQLite installations.
- The migration graph has one head: `0016_background_job_imports`.

The release archive excludes `.env`, API keys, local databases, CVs, profiles,
and other runtime data.
