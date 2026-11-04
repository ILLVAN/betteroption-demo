> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Install, verify, and publish v0.7.2k locally

`v0.7.2k` is a narrow portability hotfix over the already installed, committed,
pushed, and tagged `v0.7.2j` release. It does not change application behavior,
Matching, prompts, provider configuration, the database schema, or deployment
topology. The local SQLite database remains local. A first Netcup deployment
still starts with an empty PostgreSQL database and follows the separate
[private-alpha runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2k.md).

## 1. Stop the app and make a private local backup

In the PowerShell window that runs BetterOption, press `Ctrl+C` once and wait
until Uvicorn prints `Application shutdown complete` and `Finished server
process`. Then open PowerShell in the repository root:

```powershell
Set-Location C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path (Get-Location) "local-backups\before-v0.7.2k-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path .env) { Copy-Item .env (Join-Path $backup ".env") }
if (Test-Path local-data) {
  Copy-Item local-data (Join-Path $backup "local-data") -Recurse
}
```

Never add `.env`, `local-data`, `local-backups`, uploads, CVs, databases, or
provider secrets to Git or a release ZIP.

## 2. Point PowerShell at the k ZIP and trusted hash

Download the supplied ZIP to the normal Windows Downloads folder. Copy the
complete SHA-256 from the release handoff; do not reuse the `j` hash.

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2k.zip"
$expectedSha256 = "PASTE-THE-64-CHARACTER-K-SHA-256-HERE"
```

Confirm that both values are present before installation:

```powershell
if (-not (Test-Path -LiteralPath $release -PathType Leaf)) {
  throw "The v0.7.2k ZIP was not found at $release"
}
if ($expectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
  throw "Paste the complete SHA-256 from the trusted v0.7.2k handoff first."
}
Get-FileHash -LiteralPath $release -Algorithm SHA256
```

The displayed hash must match `$expectedSha256` exactly.

## 3. Install k over j

The `j` installer already understands and requires `-ExpectedSha256`, so the
installer itself verifies the archive before opening or extracting it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2k" `
  -ExpectedSha256 $expectedSha256
```

The overlay preserves `.env`, `.venv`, `local-data`, uploads, and local
backups. It replaces only release-managed source, tests, scripts, and
documentation.

## 4. Verify the installed identities

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
.\.venv\Scripts\python.exe -c "from betteroption.results import CURRENT_MATCHING_ALGORITHM; print(CURRENT_MATCHING_ALGORITHM)"
```

Expected identifiers:

```text
0.7.2k
0.7.2+k
matching-v0.7.2i
0033_background_task_leases
```

The Match-evidence prompt remains `match-evidence-v0.7.2i`. Existing `i`/`j`
matches remain valid. No migration, forced rematch, `.env` edit, or provider
reconfiguration is required for this hotfix.

## 5. Run only the two repaired tests

This is the intended narrow `k` verification. It does not run the complete
suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_release_package.py::test_release_builder_rejects_symlinked_input `
  tests/test_v072j_background_worker.py::test_one_sigint_exits_without_joining_stuck_provider_io
```

Expected result on the normal Windows setup: `2 passed`.

What these tests protect:

1. The archive builder must reject a release input reported as a symlink or a
   Windows directory junction. The old test failed before calling the builder
   because Windows denied creation of its test symlink (`WinError 1314`). The
   portable fixture now tests the builder on every supported machine.
2. A stopped local process must not wait for abandoned provider I/O. The old
   Windows test used `os.kill(..., SIGINT)`, which terminates a Windows process
   with exit code `2` instead of invoking its registered SIGINT handler. The
   test now uses Python's portable `signal.raise_signal(SIGINT)` path.

These are valuable release/shutdown regression guards, but the two original
failures were test-harness failures. They did not reveal a `j` application,
Matching, database, or hosted-worker defect.

## 6. Optional checks remain the operator's choice

No full suite is required for this narrow handoff. If you decide to run it
yourself later, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Do not describe `k` as fully regression-tested unless that command actually
finishes successfully on the exact committed bytes.

## 7. Start the app for a quick smoke check

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000` and confirm that the page loads and reports
`0.7.2k`. Your earlier `j` manual acceptance remains the functional baseline;
`k` intentionally adds no new product workflow to retest.

## 8. Use the updated first-server-deploy guide

For the first VPS deployment, do not copy the local `.env`, SQLite database,
personas, jobs, CVs, uploads, sessions, or backups. Follow the complete
[Netcup + Cloudflare v0.7.2k runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2k.md)
from the first section and stop at every gate.

The server runbook pins `v0.7.2k`, expects package `0.7.2+k`, and still expects
database head `0033_background_task_leases` and Matching
`matching-v0.7.2i`. Its rollback example deliberately returns to
`v0.7.2j`, the previous release.

## 9. Build and inspect the k source ZIP

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2k.zip -Algorithm SHA256
```

The archive must contain the `k` release notes, this local guide, the `k`
private-alpha runbook, source, tests, and migration `0033`. It must not contain
`.env`, Tunnel tokens, databases, runtime data, uploads, backups, CVs, private
keys, or unapproved PDF/Office documents.

## 10. Commit, push, and tag k in the Windows repository

First inspect the exact changes and confirm that private paths remain ignored
and untracked:

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads
git ls-files .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads
```

`git ls-files` must print nothing for those private/runtime paths. Then:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2k"

git tag -a v0.7.2k -m "BetterOption v0.7.2k"
git push origin v0.7.2k
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Do not move, delete, or reuse tag `v0.7.2j`. Record the final `k` commit ID and
new ZIP SHA-256 in the deployment operator record before touching the VPS.
