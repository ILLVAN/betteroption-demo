# Local development

Use Python **3.12**. The project remains at application `0.7.2k` and Python
package `0.7.2+k`; this documentation cleanup does not introduce a new release.
Use synthetic profile/job data for evaluation.

## Windows 11

From a checkout of the repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_web.ps1
```

Bootstrap creates `.venv`, preserves an existing `.env`, installs dependencies,
checks configuration, and opens/migrates the local database. The run script
binds Uvicorn to `127.0.0.1:8000`. Keep the terminal open and stop it with
`Ctrl+C` before copying the database or installing an overlay.

The example configuration uses account-owned personas and `first_user`
registration. With an empty database, create a synthetic local owner through
the registration screen. Do not copy an old runtime database or deployment
environment into this checkout.

## Manual setup on Linux/macOS

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp -n .env.example .env
python scripts/diagnose_config.py
python -m uvicorn betteroption.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

SQLite is created/migrated on startup. PostgreSQL evaluation additionally needs
the `deployment` extra and a separately configured database. PowerShell helper
scripts remain Windows-oriented; use the Python commands directly elsewhere.

## External requests and offline inspection

An empty API-key field disables that keyed capability, but keyless discovery,
geocoding, and routing integrations can still contact public services when a
workflow requests them. Local mode alone does not imply offline operation.

For UI-only inspection, leave API keys blank and avoid starting discovery,
research, extraction, or routing workflows. For strict offline execution, also
deny network egress. Automated tests provide fake/in-memory services for
evaluating individual workflows without live providers.

Keep real `.env` files, CVs, uploads, databases, backups, private keys, and
scanner exports outside Git. Deployment examples use reserved example addresses
and placeholders. Configure only services you deliberately intend to exercise.

## Verification

On Windows, `scripts/test_release.ps1` runs the project gate. Equivalent Python
checks from the active virtual environment are:

```bash
python -m ruff format --check .
python -m ruff check .
python -m pytest -q
python -m compileall -q src examples tests
```

Tests isolate the operator's ambient configuration in `tests/conftest.py`.
Platform-specific checks can skip when their external binaries are unavailable.
No live paid-provider validation is required for the documentation cleanup.

## Historical source-ZIP overlays

The retained installer supports the last development release. Preserve private
runtime state separately, stop the app, and obtain a trusted SHA-256 for the ZIP.
Do not use a hash calculated from an untrusted download as its authenticity check.

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2k.zip"
$expectedSha256 = "PASTE-THE-TRUSTED-64-CHARACTER-SHA-256"
$actualSha256 = (Get-FileHash -LiteralPath $release -Algorithm SHA256).Hash
if ($actualSha256 -ne $expectedSha256) { throw "Archive hash mismatch" }
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release -ExpectedVersion "0.7.2k" `
  -ExpectedSha256 $expectedSha256
```

The [release builder](../scripts/build_release.py) can package the source with
`python scripts/build_release.py`. It excludes known runtime/private artifact
classes. Inspect the ZIP before sharing it; packaging exclusions do not rewrite
Git history. Older installation and deployment procedures are
[archived engineering records](archive/engineering-history/README.md).
