param(
    [string]$CommitMessage = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "The project virtual environment does not exist. Install the release first."
}

Push-Location $projectRoot
try {
    if (-not (Test-Path (Join-Path $projectRoot ".git"))) {
        throw "This project directory is not a Git repository."
    }
    if (-not $CommitMessage) {
        $version = (& $python -c "import betteroption; print(betteroption.__version__)").Trim()
        $CommitMessage = "Release BetterOption v$version"
    }

    function Test-ForbiddenReleasePath([string]$Path) {
        $portable = $Path.Replace("\", "/").TrimStart([char]'/')
        $leaf = [IO.Path]::GetFileName($portable)
        $allowedEnvironmentExamples = @(".env.example", "deploy/.env.staging.example")
        if (
            (
                $leaf.StartsWith(".env", [StringComparison]::OrdinalIgnoreCase) -or
                $leaf.EndsWith(".env", [StringComparison]::OrdinalIgnoreCase)
            ) -and
            $portable -notin $allowedEnvironmentExamples
        ) { return $true }
        if ($leaf.Equals("cloudflared-token", [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        if ($portable -match "(^|/)(\.git|\.idea|\.pytest_cache|\.ruff_cache|\.venv|\.vscode|__pycache__|backups|dist|htmlcov|local-backups|local-data|uploads)(/|$)") {
            return $true
        }
        if ($portable -match "(^|/)[^/]+\.egg-info(/|$)") { return $true }

        $extension = [IO.Path]::GetExtension($leaf).ToLowerInvariant()
        if ($extension -in @(
            ".db", ".doc", ".docx", ".key", ".odt", ".p12", ".pages", ".pdf",
            ".pem", ".pfx", ".pyc", ".pyo", ".rtf", ".sqlite", ".sqlite3"
        )) { return $true }

        $candidateArtifactExtensions = @(
            ".jpeg", ".jpg", ".json", ".md", ".png", ".text", ".tif", ".tiff",
            ".txt", ".xml"
        )
        $stem = [IO.Path]::GetFileNameWithoutExtension($leaf)
        $candidateArtifactPattern = '(?:^|[\W_])(?:candidate[\W_]+)?(?:cv|resume|résumé|lebenslauf)(?:$|[\W_])|(?:^|[\W_])curriculum[\W_]*vitae(?:$|[\W_])'
        return (
            $extension -in $candidateArtifactExtensions -and
            $stem -match $candidateArtifactPattern
        )
    }

    $trackedForbidden = @(git ls-files | Where-Object { Test-ForbiddenReleasePath $_ })
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect tracked files." }
    if ($trackedForbidden.Count -gt 0) {
        throw "Git already tracks forbidden runtime/secret files: $($trackedForbidden -join ', ')"
    }

    # Stage only product paths, then independently inspect the resulting index.
    git add -- .dockerignore .env.example .gitignore Dockerfile README.md compose.yaml pyproject.toml deploy docs examples scripts src tests
    if ($LASTEXITCODE -ne 0) { throw "git add failed." }

    $stagedForbidden = @(git diff --cached --name-only --diff-filter=ACMR | Where-Object {
        Test-ForbiddenReleasePath $_
    })
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect staged files." }
    if ($stagedForbidden.Count -gt 0) {
        throw "Refusing to commit forbidden runtime/secret files: $($stagedForbidden -join ', ')"
    }

    Write-Host "Files prepared for the release commit:"
    git status --short
    $answer = Read-Host "Commit as '$CommitMessage' and push to origin? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
        Write-Host "Stopped before commit. The displayed product files remain staged for review."
        exit 0
    }

    git commit -m $CommitMessage
    if ($LASTEXITCODE -ne 0) { throw "git commit failed." }
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push failed." }
}
finally {
    Pop-Location
}
