> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2e

`v0.7.2e` is an installation-only hotfix for the withdrawn `v0.7.2d` source
archive. It contains the same product behavior, matching rules and database
schema as `v0.7.2d`.

## Fixed installation metadata

The `v0.7.2d` archive declared `project.version = "0.7.2d"`. That value is not
a valid PEP 440 Python distribution version, so current setuptools rejected the
editable installation before it could refresh package metadata. The preceding
`0.7.2c` value appeared to work only because PEP 440 interprets `c` as the
release-candidate alias and normalizes it to `rc0`.

This hotfix restores the two-part version convention already used by the
project's earlier lettered releases:

- application and source release: `0.7.2e`
- Python distribution: `0.7.2+e`
- ZIP: `betteroption_v0_7_2e.zip`
- Git tag: `v0.7.2e`
- matching algorithm: `matching-v0.7.2c`, unchanged
- database migration: none

The package version is now parsed and checked for canonical PEP 440 form by the
release builder and regression suite. A real editable install from the source
archive is also part of the release acceptance gate.

## Upgrade state after the failed d installer

The overlay installer copies product files before it invokes pip. A failed
`v0.7.2d` attempt therefore leaves the `d` source in the repository while the
editable distribution metadata can still describe the preceding release. It
does not overwrite `.env`, `local-data`, uploads or local backups.

Install `v0.7.2e` directly over that state. No rollback to `v0.7.2c`, manual
source edit or database migration is required. The exact commands and both
version checks are in the [local install guide](../local-guides/local-v0.7.2e.md).

## Included product behavior

The complete interaction, ranking, provider, waiting-copy and background-task
changes remain documented in the
[`v0.7.2d` product notes](release-notes-v0.7.2d.md). The provider configuration,
environment audit and domain decision also remain applicable.

