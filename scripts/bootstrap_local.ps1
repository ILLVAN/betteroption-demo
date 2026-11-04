param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $projectRoot ".venv"
$python = Join-Path $venvDirectory "Scripts\python.exe"
$environmentFile = Join-Path $projectRoot ".env"
$environmentExample = Join-Path $projectRoot ".env.example"

Push-Location $projectRoot
try {
    if (-not (Test-Path $python)) {
        Write-Host "Creating an isolated Python 3.12 environment..."
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            & py -3.12 -m venv $venvDirectory
        }
        else {
            & python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
            if ($LASTEXITCODE -ne 0) {
                throw "Python 3.12 is required. Install it, then run this script again."
            }
            & python -m venv $venvDirectory
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python)) {
            throw "Could not create .venv with Python 3.12."
        }
    }

    & $python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "The existing .venv does not use Python 3.12. Move it aside and rerun bootstrap."
    }

    if (-not (Test-Path $environmentFile)) {
        if (-not (Test-Path $environmentExample)) {
            throw ".env.example is missing from this release."
        }
        Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
        Write-Host "Created .env from the safe local example. Add new API keys before provider tests."
    }
    else {
        Write-Host "Preserving the existing .env file."
    }

    if (-not $SkipDependencyInstall) {
        & $python -m pip install -e ".[dev,extraction,deployment]"
        if ($LASTEXITCODE -ne 0) {
            throw "Editable installation failed."
        }
    }

    $installedVersion = (& $python -c "import betteroption; print(betteroption.__version__)").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "BetterOption could not be imported from the local environment."
    }
    Write-Host "Installed BetterOption $installedVersion"

    & $python scripts\diagnose_config.py
    if ($LASTEXITCODE -ne 0) {
        throw "Configuration validation failed. Correct .env and rerun this script."
    }

    & $python -c "from betteroption.database import Database; database = Database(); print('Database ready: ' + database.engine.url.get_backend_name())"
    if ($LASTEXITCODE -ne 0) {
        throw "The local database could not be created or migrated."
    }
}
finally {
    Pop-Location
}

Write-Host "Local bootstrap complete. No public listener or server deployment was created."
Write-Host "Run tests: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_release.ps1"
Write-Host "Start local-only: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_web.ps1"
