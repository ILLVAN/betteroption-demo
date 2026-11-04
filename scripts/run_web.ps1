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
    Write-Host "WorkLifeBalance is starting at http://127.0.0.1:8000"
    Write-Host "Keep this terminal open while testing. Press Ctrl+C to stop the server."
    & $python -u -m uvicorn betteroption.web.app:create_app `
      --factory `
      --host 127.0.0.1 `
      --port 8000 `
      --log-level debug
}
finally {
    Pop-Location
}
