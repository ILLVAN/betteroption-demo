$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
Push-Location $projectRoot

try {
    if (-not (Test-Path $python)) {
        throw "The project virtual environment does not exist. Run install_latest_release.ps1 first."
    }

    Write-Host "Using Python: $python"
    & $python -m pip install -e ".[dev,extraction]"
    if ($LASTEXITCODE -ne 0) {
        throw "Editable installation failed."
    }

    & $python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) {
        throw "Formatting check failed. Run: python -m ruff format ."
    }

    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "Lint check failed."
    }

    & $python -m pytest -v --cov=betteroption --cov-report=term
    if ($LASTEXITCODE -ne 0) {
        throw "Test suite failed."
    }

    & $python -m compileall -q src examples scripts tests
    if ($LASTEXITCODE -ne 0) {
        throw "Bytecode compilation check failed."
    }
}
finally {
    Pop-Location
}
