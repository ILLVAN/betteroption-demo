> **Historical README.** This is the final development-release handoff, retained for traceability.
> The project is discontinued; use the [portfolio overview](../../../../README.md).

# BetterOption / WorkLifeBalance

BetterOption is the platform behind WorkLifeBalance, a decision-oriented job
search tool. It turns a user-controlled Compass into source-attributed job
discovery, transparent matching, commute evidence and an application workspace.
It never submits an application automatically.

## Current release: v0.7.2k

`v0.7.2k` is a narrow Windows test-portability and release-archive hotfix over
the manually accepted `v0.7.2j` application:

- the symlink-rejection test no longer requires Windows Developer Mode or an
  elevated symlink privilege, so the archive boundary is exercised instead of
  failing during fixture setup;
- the release builder also rejects Windows directory junctions;
- the one-SIGINT subprocess test uses the portable registered-signal path
  instead of Windows `os.kill(..., SIGINT)` process termination.

No application workflow, UI, Matching rule, prompt, provider, database schema,
or deployment behavior changes. The complete `j` functional behavior remains
the accepted baseline.

Application version: `0.7.2k`
Python package version: `0.7.2+k`
Matching algorithm: `matching-v0.7.2i` (unchanged; a current `i` Match stays valid)
Database migration: `0033_background_task_leases`
Privacy draft: `2026-08-05-feedback-draft`
Release ZIP: `betteroption_v0_7_2k.zip`
Git tag: `v0.7.2k`

See the [release notes](../release-notes/release-notes-v0.7.2k.md),
[local install and verification guide](../local-guides/local-v0.7.2k.md),
[private-alpha deployment runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2k.md),
[Explore provider source review](../providers/job-source-review-v0.7.2d.md),
[pre-alpha cost and business checkpoint](../../discontinued-product-planning/cost-and-business-plan.md), and
[roadmap to closed alpha and public release](../../discontinued-product-planning/roadmap-to-public-release.md).

## Product boundary

This release is approved for localhost evaluation and for executing the
documented owner-only private-server rehearsal. The repository is deployment-
ready, but that does not mean a VPS, Access policy, Tunnel route, backup, legal
review, or external invitation has been completed.

Before inviting anyone online, complete the documented PostgreSQL/HTTPS
deployment, origin restriction, monitoring, encrypted off-server backup and
restore drill, processor/provider review, real legal text, retention/deletion
evidence, incident procedure and final launch record. Read the
[compliance dossier](../../discontinued-product-planning/compliance/README.md) and canonical roadmap before
changing readiness flags.

The candidate controls all private profile, match and application state.
Employers cannot see candidate profiles, ratings or results. Special-category
and criminal-offence data are prohibited. API keys, CVs, local databases,
uploads, backups and runtime `.env` files must never enter Git or a release ZIP.

## Quick start on Windows 11

Requirements: Python 3.12, PowerShell and Git. From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open <http://127.0.0.1:8000>. Keep the PowerShell window open and stop the app
with `Ctrl+C`; wait for the complete Uvicorn shutdown before installing another
release or copying the database.

`bootstrap_local.ps1` creates `.venv`, copies `.env.example` only when `.env`
does not exist, installs dependencies, validates configuration and opens or
migrates the local database. Existing `.env` and `local-data/` are preserved.

## Upgrade from a release ZIP

Stop the app and create a private backup of `.env` and `local-data/` first. Then:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2k.zip"
$expectedSha256 = "PASTE-THE-64-CHARACTER-SHA-256-FROM-THE-RELEASE-HANDOFF"

$actualSha256 = (Get-FileHash -LiteralPath $release -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
    $actualSha256 -ne $expectedSha256.ToLowerInvariant()) {
  throw "Release SHA-256 is missing or does not match. Do not open or install the ZIP."
}

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2k" `
  -ExpectedSha256 $expectedSha256

.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_release_package.py::test_release_builder_rejects_symlinked_input `
  tests/test_v072j_background_worker.py::test_one_sigint_exits_without_joining_stuck_provider_io
```

The installer overlays product files and intentionally preserves the runtime
environment, virtual environment, database, CV text, uploads and local backups.
The [local release guide](../local-guides/local-v0.7.2k.md) contains the verified backup,
narrow two-test check, optional full-suite command, dump and GitHub flow.

## Daily workflow

1. **Compass** — describe roles, boundaries, mobility, experience and language
   evidence; review every active value.
2. **Explore** — search from the confirmed Compass or a deliberate phrase;
   inspect source contribution and scan the compact candidate list.
3. **Match** — save selected jobs and run the complete deterministic/evidence
   model, including exact routes where configured.
4. **Job Detail** — correct job and employer facts, check evidence and record a
   private rating.
5. **Apply / Archive** — prepare user-requested material and track the real
   application state. BetterOption does not send it.

Approximate Explore distance is local ranking evidence, not a claimed journey.
Exact car, train, bicycle or walking routes belong to an explicit Match run and
retain provider, precision, cache and range evidence.

## Configuration

Copy [`.env.example`](../../../../.env.example) locally and add only the services you
actually intend to test. Restart the app after changes.

| Capability | Main setting | Default boundary |
| --- | --- | --- |
| Structured profile/job/application work and unresolved match relations | `OPENAI_API_KEY` | Explicit or bounded workflow; semantic Matching receives only unresolved confirmed criteria and cited public job facts, never the complete profile or advertisement |
| Semantic discovery | `EXA_API_KEY` | Bounded queries; every result is still untrusted until verification |
| Broad web discovery | `BRAVE_SEARCH_API_KEY` | Brave Search product only; every configured source runs by default |
| Structured job discovery | `OPENWEBNINJA_JSEARCH_API_KEY` | Phase and whole-provider deadlines; key sent only in `X-API-Key` |
| European vacancies | `APIFY_API_TOKEN` | Bounded EURES actor run with its own permission, ID, limit and ledger rows |
| Multi-source structured jobs | `APIFY_API_TOKEN` | Separate JobsPipe actor; nationwide retrieval up to 300 and local distance ranking |
| Local multi-board jobs | `APIFY_API_TOKEN` | Separate AgentX All Jobs actor; 20 results/platform, a 120-item readback/presentation guard, and a USD 0.40 pay-per-event charge ceiling; hosted off by default |
| Public ATS boards | `BETTEROPTION_GREENHOUSE_BOARDS`, `BETTEROPTION_LEVER_SITES`, `BETTEROPTION_ASHBY_BOARDS` | Public board APIs only |
| Exact routing | `BETTEROPTION_MOBILITY_PROVIDER` plus optional route keys | `privacy_first`; Explore itself never calls exact routing |
| Account boundary | `BETTEROPTION_AUTH_MODE`, `BETTEROPTION_REGISTRATION_MODE` | Account/persona mode; external invitations stay gated |

Numeric cost settings must contain a number. `0` means **unpriced**, never free.
Provider choices in Account can disable an otherwise configured service for all
personas owned by that account.

Secret-safe checks:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_openai.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
```

The JSearch diagnostic performs no live request unless `--live` is supplied;
that explicit probe consumes one plan request. It reports distinct secret-safe
categories for authentication, plan, rate limit, timeout, DNS, TLS, proxy,
connection, provider availability, request or response failures. Diagnostics
must not print or store keys, queries, request URLs, response bodies or user
content.

## Operator scripts

| Task | Command |
| --- | --- |
| Bootstrap | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_local.ps1` |
| Test | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_release.ps1` |
| Run | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_web.ps1` |
| Build safe source ZIP | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dump_release.ps1` |
| Install ZIP | Verify the published SHA-256 first; the `k` installer and later require `-ArchivePath <zip> -ExpectedVersion <version> -ExpectedSha256 <sha256>` |
| Stage, review and push | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\push_release.ps1` |

`dump_release.ps1` writes `dist/betteroption_v0_7_2k.zip` through the reviewed
release builder. Runtime data, environment files, secret/key types, databases,
uploads, likely CV/resume artifacts and unapproved office/PDF documents are
excluded. Still inspect the archive before publishing.

## Verification and release

The complete local gate runs formatting, lint, tests and bytecode compilation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Before a release commit, stop the app and confirm private paths are ignored and
untracked:

```powershell
git status --short
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads
```

`git ls-files` must print nothing for those paths. Build, inspect and publish:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2k"

git tag -a v0.7.2k -m "BetterOption v0.7.2k"
git push origin v0.7.2k
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

The push script stages only reviewed product roots, rejects tracked/staged
runtime or secret paths, displays the exact staged files and asks before commit
or push.

## Architecture

- Python 3.12, FastAPI and server-rendered Jinja interface
- SQLAlchemy/Alembic with SQLite locally and PostgreSQL for online staging
- deterministic matching with explicit evidence and versioned result snapshots
- persistent leased background tasks with an embedded local worker and a
  dedicated hosted worker
- bounded provider adapters behind permission, budget and telemetry boundaries
- source ZIP overlay that excludes local/private runtime material

The application domain does not depend on FastAPI templates, and provider
failures are expected to degrade one capability rather than invalidate stored
user work or unrelated sources.

## Documentation map

- [Documentation index](../../../README.md)
- [v0.7.2k release notes](../release-notes/release-notes-v0.7.2k.md)
- [Local install, test, dump and publish](../local-guides/local-v0.7.2k.md)
- [Explore provider source review](../providers/job-source-review-v0.7.2d.md)
- [Cost control and rough business plan](../../discontinued-product-planning/cost-and-business-plan.md)
- [Roadmap to closed alpha and public release](../../discontinued-product-planning/roadmap-to-public-release.md)
- [Compliance dossier](../../discontinued-product-planning/compliance/README.md)
- [Profile Protocol](../design/profile-protocol-v0.1.md)
- [Job and matching model](../design/job-and-matching-v0.1.md)
- [Current Explore provider setup](../providers/discovery-provider-setup-v0.7.2d.md)
- [Local environment audit](../local-guides/local-environment-v0.7.2d.md)
- [Domain decision note](../../discontinued-product-planning/domain-name-decision-v0.7.2i.md)
- [Private-alpha hosting and public gates](../../discontinued-product-planning/hosting-and-public-roadmap-v0.7.2i.md)
- [Netcup + Cloudflare private-alpha runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2k.md)

Older `release-notes-v*.md`, `local-*.md`, release-cycle and architecture files
are historical records retained for traceability; the root README and
documentation index are the current entry points.
