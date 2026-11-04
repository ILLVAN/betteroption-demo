> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2k

`v0.7.2k` is a deliberately narrow portability hotfix over the manually
accepted `v0.7.2j` application. It fixes the two Windows failures reported by
the local release gate without changing product behavior, Matching, prompts,
providers, persistence, migrations, or the hosted deployment topology.

## What the two failures meant

### Release-builder link rejection

`test_release_builder_rejects_symlinked_input` failed while arranging its test
fixture. A standard Windows account without Developer Mode or the symbolic-link
privilege cannot call `Path.symlink_to`; Windows returned `WinError 1314`
before the release builder was executed.

The underlying guard remains important. It prevents a release ZIP from
following a link into an outside directory and accidentally packaging runtime,
private, or otherwise unreviewed files. `k` therefore does not solve the
failure by skipping the test:

- the test now supplies ordinary placeholder paths and models the exact
  `Path.is_symlink()` result for those paths;
- nested-file and included-root rejection remain covered on every supported
  development machine;
- the builder also treats a Windows directory junction as link-like input via
  `Path.is_junction()` and rejects it before archive traversal.

This is a release confidentiality/integrity boundary. The original red result
was a Windows fixture-capability failure, not evidence that the already built
`j` ZIP contained a symlink.

### One-SIGINT shutdown regression

`test_one_sigint_exits_without_joining_stuck_provider_io` used
`os.kill(os.getpid(), signal.SIGINT)` inside a child process. On Windows,
`os.kill` handles this value through process termination rather than the
registered Python SIGINT handler; the child therefore ended silently with exit
code `2`. The worker shutdown path was never exercised.

The test now uses `signal.raise_signal(signal.SIGINT)`, which invokes the
registered handler portably. It continues to verify that a daemon provider
thread cannot keep Python alive after the bounded worker stop.

The regression guard is meaningful for local shutdown, but it is not a full
Uvicorn/Windows console-event integration test. The reported manual Windows
session already supplied that complementary evidence by reaching
`Application shutdown complete` and `Finished server process` after one
`Ctrl+C`.

Python documents the platform distinction in
[`os.kill`](https://docs.python.org/3.12/library/os.html#os.kill) and the
portable in-process trigger in
[`signal.raise_signal`](https://docs.python.org/3.12/library/signal.html#signal.raise_signal).

## Deliberately unchanged

- Application workflows and UI from `v0.7.2j`
- Explore progress, cancellation, and durable worker behavior
- Provider budgets and Operations telemetry
- Manual-job one-job Matching and evidence overrides
- Matching algorithm `matching-v0.7.2i`
- Match-evidence prompt `match-evidence-v0.7.2i`
- Database migration head `0033_background_task_leases`
- Privacy draft `2026-08-05-feedback-draft`
- `.env` keys and defaults other than the mechanical outbound version label
- Compose, Caddy, PostgreSQL, Cloudflare, and Netcup topology

Existing `i`/`j` Match results remain valid. No forced rematch, database
migration, environment upgrade, or new server secret is required.

## Updated operating guides

- [Local install, two-test verification, build, and publish guide](../local-guides/local-v0.7.2k.md)
- [Complete first Netcup + Cloudflare deployment runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2k.md)

The server was not deployed from `h`, `i`, or `j`; the first server deployment
can therefore pin `v0.7.2k` directly and still starts with an empty PostgreSQL
database. The rollback example deliberately returns to `v0.7.2j`.

## Verification scope

The `k` handoff intentionally does **not** claim a complete regression run.
Only narrow checks relevant to this portability hotfix and release packaging
are run by the release author. Functional/manual acceptance remains the
accepted `j` baseline, and the operator may run `scripts/test_release.ps1`
later if a complete local gate is desired.

The two repaired nodes are:

```text
tests/test_release_package.py::test_release_builder_rejects_symlinked_input
tests/test_v072j_background_worker.py::test_one_sigint_exits_without_joining_stuck_provider_io
```

Archive validation still checks unique portable paths, no case collisions,
no ZIP traversal, no link entries, byte equality with the selected source
files, and exclusion of runtime/private material. Those checks do not imply
that the complete application suite was run.

## Release identity

- Application/source release: `0.7.2k`
- Python distribution: `0.7.2+k`
- Archive: `betteroption_v0_7_2k.zip`
- Git tag: `v0.7.2k`
- Previous/rollback release: `v0.7.2j`
- Matching algorithm: `matching-v0.7.2i` (unchanged)
- Match-evidence prompt: `match-evidence-v0.7.2i` (unchanged)
- Database migration head: `0033_background_task_leases` (unchanged)
- Privacy draft: `2026-08-05-feedback-draft` (unchanged)
