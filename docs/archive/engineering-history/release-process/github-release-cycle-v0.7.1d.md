> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Private GitHub release cycle for v0.7.1c and v0.7.1d

The private GitHub repository is the source-history and collaboration record.
Release ZIPs are immutable recovery checkpoints; they do not replace Git.

Never stage `.env`, `local-data`, `local-backups`, CV files, databases, API
keys, certificates, or the generated `dist` archive.

## A. Preserve the already-installed v0.7.1c release

Do this before installing v0.7.1d if v0.7.1c has not been committed yet.

```powershell
cd C:\projects\betteroption
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
git remote -v
git status --short
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

The version must be `0.7.1c-local-quality`. `git ls-files` must not print a
private/runtime path. The old overlay installer could leave one superseded
v0.7.1a test behind; it is not part of the v0.7.1c archive:

```powershell
Remove-Item .\tests\test_v071a.py -Force -ErrorAction SilentlyContinue
```

The v0.7.1c test harness could also read real provider settings from `.env`.
Run its clean-source gate with the secret file temporarily moved and restore it
even if a test fails:

```powershell
$heldEnvironment = ".env.test-hold"
Move-Item .env $heldEnvironment
try {
    powershell -NoProfile -ExecutionPolicy Bypass `
      -File .\scripts\test_release.ps1
}
finally {
    Move-Item $heldEnvironment .env
}
```

Then use the guarded product-only commit helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1c-local-quality"
```

After GitHub shows that commit, mark the exact checkpoint:

```powershell
git tag -a v0.7.1c-local-quality -m "BetterOption v0.7.1c local quality"
git push origin v0.7.1c-local-quality
git status --short
```

If the release commit already exists, do not create an empty duplicate commit;
verify the imported version and tag that existing commit instead.

## B. Install, validate, and publish v0.7.1d

Install the exact archive path. The installer preserves `.env` and local data
and removes the known superseded test automatically.

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1d_local_personas.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1d-local-personas"
```

Run diagnostics and the complete gate with the normal `.env` present. The
v0.7.1d tests are isolated from runtime provider credentials.

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
git status --short
git diff --stat
```

After the local persona, Compass, CV, and Explore acceptance checks pass:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1d-local-personas"

git tag -a v0.7.1d-local-personas -m "BetterOption v0.7.1d local personas"
git push origin v0.7.1d-local-personas
```

Verify GitHub and the local branch:

```powershell
git log -2 --oneline
git tag --list "v0.7.1*"
git status --short
git ls-files .env local-data local-backups dist
```

The final command must print nothing. A clean `git status` plus both pushed
tags gives a recoverable sequence from the legal baseline through the local
quality and persona iterations.
