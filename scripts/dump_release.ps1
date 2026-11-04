$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The project virtual environment does not exist. Install the release first."
}

Push-Location $projectRoot
$archivePath = $null
$buildSucceeded = $false
try {
    $archiveName = (& $python -c "from scripts.build_release import ARCHIVE_NAME; print(ARCHIVE_NAME)").Trim()
    if ($LASTEXITCODE -ne 0 -or $archiveName -notmatch '^betteroption_v[a-zA-Z0-9_.+-]+\.zip$') {
        throw "The release builder did not provide a safe archive name."
    }
    $version = (& $python -c "from scripts.build_release import VERSION; print(VERSION)").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^[0-9a-zA-Z][0-9a-zA-Z.+-]*$') {
        throw "The release builder did not provide a safe version."
    }

    $archivePath = Join-Path (Join-Path $projectRoot "dist") $archiveName
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue

    & $python scripts\build_release.py
    if ($LASTEXITCODE -ne 0) {
        throw "Release dump failed."
    }
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "Release dump completed without creating the expected archive."
    }
    $buildSucceeded = $true
    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
    Write-Host "Local source dump ready: $archivePath"
    Write-Host "SHA-256: $archiveHash"
    Write-Host "Runtime data, environment files, keys, databases, uploads, and CV files are excluded."
    Write-Host ""
    Write-Host "DUMP"
    Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dump_release.ps1"
    Write-Host ""
    Write-Host "INSTALL"
    Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_latest_release.ps1 -ArchivePath `".\dist\$archiveName`" -ExpectedVersion `"$version`" -ExpectedSha256 `"$archiveHash`""
    Write-Host ""
    Write-Host "TEST"
    Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_release.ps1"
    Write-Host ""
    Write-Host "GIT UPLOAD (review the staged files and confirm the prompt)"
    Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\push_release.ps1 -CommitMessage `"Release BetterOption v$version`""
    Write-Host "git tag -a v$version -m `"BetterOption v$version`""
    Write-Host "git push origin v$version"
}
finally {
    if (-not $buildSucceeded -and $null -ne $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
