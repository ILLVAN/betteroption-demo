$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "The project virtual environment does not exist. Run install_latest_release.ps1 first."
}

Push-Location $projectRoot
try {
    # A short-lived pre-account overlay created this obsolete test outside the
    # current release. Removing it here makes the release gate deterministic
    # even when an older ZIP was applied before v0.7.1a.
    Remove-Item `
        -LiteralPath (Join-Path $projectRoot "tests\test_v070a1.py") `
        -Force `
        -ErrorAction SilentlyContinue
    # v0.7.1a shipped a transient pre-legal registration test whose assertions
    # conflict with the later legal/account boundary. Overlay installs preserve
    # unrelated local files, so remove this one known superseded test explicitly.
    Remove-Item `
        -LiteralPath (Join-Path $projectRoot "tests\test_v071a.py") `
        -Force `
        -ErrorAction SilentlyContinue
    & $python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "Formatting check failed." }
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Lint check failed." }
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Test suite failed." }
    & $python -m compileall -q src examples scripts tests
    if ($LASTEXITCODE -ne 0) { throw "Bytecode compilation check failed." }
}
finally {
    Pop-Location
}
