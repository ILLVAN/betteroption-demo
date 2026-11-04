param(
    [string]$ArchivePath = "",
    [string]$ExpectedVersion = "",
    [string]$ExpectedSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$downloads = Join-Path $env:USERPROFILE "Downloads"

if (-not $ArchivePath) {
    $latest = Get-ChildItem -Path $downloads -Filter "betteroption_v*.zip" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No BetterOption release ZIP was found in $downloads."
    }
    $ArchivePath = $latest.FullName
}

$ArchivePath = (Resolve-Path $ArchivePath).Path
if (-not $ExpectedSha256) {
    throw "ExpectedSha256 is required. Copy the SHA-256 from the trusted release handoff."
}
$normalizedExpectedSha256 = $ExpectedSha256.Trim().ToLowerInvariant()
if ($normalizedExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
    throw "ExpectedSha256 must contain exactly 64 hexadecimal characters."
}
$actualSha256 = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $normalizedExpectedSha256) {
    throw "Release SHA-256 mismatch. Expected $normalizedExpectedSha256 but received $actualSha256. Nothing was opened, extracted, or installed."
}
Write-Host "Installing release: $ArchivePath"
Write-Host "Verified SHA-256:  $actualSha256"
Write-Host "Project directory:  $projectRoot"

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
try {
    $approvedEnvironmentExamples = @(
        ".env.example",
        "deploy/.env.staging.example"
    )
    $forbiddenDirectoryNames = @(
        ".git",
        ".idea",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".vscode",
        "__pycache__",
        "backups",
        "dist",
        "htmlcov",
        "local-backups",
        "local-data",
        "uploads"
    )
    $forbiddenSuffixes = @(
        ".db",
        ".doc",
        ".docx",
        ".key",
        ".odt",
        ".p12",
        ".pages",
        ".pdf",
        ".pem",
        ".pfx",
        ".pyc",
        ".pyo",
        ".rtf",
        ".sqlite",
        ".sqlite3"
    )
    foreach ($entry in $archive.Entries) {
        $relative = $entry.FullName.Replace([char]'/', [IO.Path]::DirectorySeparatorChar)
        $portable = $entry.FullName.Replace([char]'\', [char]'/').TrimStart([char]'/')
        $segments = $relative -split "[\\/]"
        if ([IO.Path]::IsPathRooted($relative) -or $segments -contains "..") {
            throw "Unsafe archive path: $($entry.FullName)"
        }
        $leaf = [IO.Path]::GetFileName($relative)
        if (
            (
                $leaf.StartsWith(".env", [StringComparison]::OrdinalIgnoreCase) -or
                $leaf.EndsWith(".env", [StringComparison]::OrdinalIgnoreCase)
            ) -and
            $portable -notin $approvedEnvironmentExamples
        ) {
            throw "The release archive contains a runtime environment file: $portable"
        }
        if ($leaf.Equals("cloudflared-token", [StringComparison]::OrdinalIgnoreCase)) {
            throw "The release archive contains a Cloudflare Tunnel token: $portable"
        }
        if ($segments | Where-Object { $_ -in $forbiddenDirectoryNames }) {
            throw "The release archive contains runtime/private data: $portable"
        }
        if ([IO.Path]::GetExtension($leaf).ToLowerInvariant() -in $forbiddenSuffixes) {
            throw "The release archive contains a forbidden private file type: $portable"
        }
        $candidateArtifactExtensions = @(
            ".jpeg", ".jpg", ".json", ".md", ".png", ".text", ".tif", ".tiff",
            ".txt", ".xml"
        )
        $extension = [IO.Path]::GetExtension($leaf).ToLowerInvariant()
        $stem = [IO.Path]::GetFileNameWithoutExtension($leaf)
        $candidateArtifactPattern = '(?:^|[\W_])(?:candidate[\W_]+)?(?:cv|resume|résumé|lebenslauf)(?:$|[\W_])|(?:^|[\W_])curriculum[\W_]*vitae(?:$|[\W_])'
        if (
            $extension -in $candidateArtifactExtensions -and
            $stem -match $candidateArtifactPattern
        ) {
            throw "The release archive contains a likely private CV/resume artifact: $portable"
        }
    }
}
finally {
    $archive.Dispose()
}

$staging = Join-Path ([IO.Path]::GetTempPath()) ("betteroption-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    Expand-Archive -Path $ArchivePath -DestinationPath $staging -Force
    Get-ChildItem -Path $staging -File -Recurse -Force | ForEach-Object {
        $relative = $_.FullName.Substring($staging.Length).TrimStart([char[]]"\/")
        $destination = Join-Path $projectRoot $relative
        $destinationDirectory = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -Path $_.FullName -Destination $destination -Force
    }
}
finally {
    Remove-Item -Path $staging -Recurse -Force -ErrorAction SilentlyContinue
}

# Obsolete files from superseded overlays are intentionally removed by this
# clean product overlay. These named tests encoded pre-account/pre-legal
# contracts and are not part of the current suite. Runtime configuration and
# user data live outside these paths and remain untouched.
Remove-Item `
    -LiteralPath (Join-Path $projectRoot "docs\release-notes-v0.7.0f.md") `
    -Force `
    -ErrorAction SilentlyContinue
Remove-Item `
    -LiteralPath (Join-Path $projectRoot "tests\test_v070a1.py") `
    -Force `
    -ErrorAction SilentlyContinue
Remove-Item `
    -LiteralPath (Join-Path $projectRoot "tests\test_v071a.py") `
    -Force `
    -ErrorAction SilentlyContinue

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating .venv with the installed Python..."
    python -m venv (Join-Path $projectRoot ".venv")
}
if (-not (Test-Path $python)) {
    throw "Could not create .venv. Install Python 3.12 and run this script again."
}

Push-Location $projectRoot
try {
    & $python -m pip install -e ".[dev,extraction,deployment]"
    if ($LASTEXITCODE -ne 0) {
        throw "Editable installation failed."
    }
    $installedVersion = (& $python -c "import betteroption; print(betteroption.__version__)").Trim()
    Write-Host "Installed BetterOption $installedVersion"
    if ($ExpectedVersion -and $installedVersion -ne $ExpectedVersion) {
        throw "Installed version '$installedVersion' does not match expected '$ExpectedVersion'."
    }
}
finally {
    Pop-Location
}

Write-Host "Installation complete. Your .env, database, CV text, and local data were preserved."
Write-Host "Optional checks: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_release.ps1"
Write-Host "Start the app:  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_web.ps1"
