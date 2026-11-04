> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2b lokal sichern, installieren, testen, dumpen und veröffentlichen

Dieser Ablauf gilt für die lokale Windows-App unter
`http://127.0.0.1:8000`. Alle Befehle werden im Repository-Stamm ausgeführt.

## 1. App stoppen und private Daten sichern

Im Fenster mit `run_web.ps1` `Ctrl+C` drücken und den vollständigen Uvicorn-
Shutdown abwarten. Danach:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v072b-$stamp"
New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null
if (Test-Path ".\.env") {
  Copy-Item ".\.env" "$backup\.env" -ErrorAction Stop
}
if (Test-Path ".\local-data") {
  Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop
}

git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads
```

`git ls-files` muss leer bleiben. Backup, `.env`, Datenbank, CVs und Uploads
gehören weder in GitHub noch in das Source-ZIP.

## 2. Release installieren

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2b.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2b"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Erwartet wird `0.7.2b`. Der Installer bewahrt `.env`, `local-data`, Backups,
Uploads und `.venv`. Es gibt keine neue Datenbankmigration; der Head bleibt
`0030_verified_job_posters`.

## 3. Erhaltene `.env` sicher aktualisieren

Der Installer bewahrt `.env` absichtlich. Deshalb würden die alten bekannten
`0.7.2a`-Defaults (230 Sekunden, 80 Checks, 150 JobsPipe-Treffer) sonst weiter
gelten und die neue 5–7-Minuten-/300-Treffer-Grenze überstimmen. Der folgende
Block ersetzt nur exakt bekannte Release-Defaults, lässt eigene abweichende
Werte und Schlüssel stehen und ergänzt nur fehlende neue Felder:

```powershell
$environmentPath = ".\.env"
if (Test-Path $environmentPath) {
  $environmentText = Get-Content $environmentPath -Raw
  $updatedEnvironmentText = $environmentText

  $knownReleaseReplacements = [ordered]@{
    "BetterOption/0.7.2a (+https://github.com/ILLVAN/betteroption)" = "BetterOption/0.7.2b (+https://github.com/ILLVAN/betteroption)"
    "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-04-draft" = "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-04b-draft"
    "BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=230" = "BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=390"
    "BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS=80" = "BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS=120"
    "BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=150" = "BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=300"
  }
  foreach ($entry in $knownReleaseReplacements.GetEnumerator()) {
    $updatedEnvironmentText = $updatedEnvironmentText.Replace(
      $entry.Key,
      $entry.Value
    )
  }

  $newDefaults = @(
    "BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true",
    "BETTEROPTION_OPENWEBNINJA_JSEARCH_CONNECT_TIMEOUT_SECONDS=10",
    "BETTEROPTION_OPENWEBNINJA_JSEARCH_READ_TIMEOUT_SECONDS=90",
    "BETTEROPTION_OPENWEBNINJA_JSEARCH_SEARCH_BUDGET_SECONDS=120",
    "BETTEROPTION_APIFY_JOBSPIPE_POSTED_WITHIN_DAYS=60",
    "BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=60",
    "BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=300",
    "BETTEROPTION_APIFY_ALL_JOBS_POSTED_SINCE=30 days",
    "BETTEROPTION_APIFY_ALL_JOBS_PLATFORMS=",
    "BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0",
    "BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=false",
    "BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD=0"
  )
  foreach ($default in $newDefaults) {
    $name = $default.Split("=", 2)[0]
    if ($updatedEnvironmentText -notmatch "(?m)^$([regex]::Escape($name))=") {
      $updatedEnvironmentText = $updatedEnvironmentText.TrimEnd() +
        [Environment]::NewLine + $default + [Environment]::NewLine
    }
  }

  if ($updatedEnvironmentText -ne $environmentText) {
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
      (Resolve-Path $environmentPath).Path,
      $updatedEnvironmentText,
      $utf8WithoutBom
    )
  }
}
```

Wenn du einen dieser Werte bewusst angepasst hattest, bleibt er unangetastet;
vergleiche ihn dann manuell mit `.env.example`. Ein vorhandenes
`APIFY_API_TOKEN` wird für drei technisch getrennte Actor-Adapter verwendet.
Leere Plattformliste bedeutet alle für das Land verfügbaren Plattformen. Jeder
Kostenwert `0` bedeutet **unpriced**, nicht kostenlos.

## 4. Konfiguration und JSearch prüfen

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

Nur `--live` löst genau einen festen synthetischen JSearch-Request aus. Der
Probe darf wegen des korrigierten Read-Timeouts bis etwa 90 Sekunden benötigen.
Ein Erfolg zeigt `category: success`; Fehler bleiben secret-safe kategorisiert.

App danach einmal starten, **Account → Provider choices** öffnen und prüfen,
dass alle gewünschten Quellen aktiv sind. EURES, JobsPipe und All Jobs sind
drei getrennte Optionen. Eine ausdrücklich früher gespeicherte Deaktivierung
wird nicht überschrieben.

## 5. Vollständiges Test-Gate und Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

## 6. Manuelle Abnahme

1. Mit Compass eine Explore-Suche starten und bis zu sieben Minuten laufen
   lassen. Source contribution soll jede konfigurierte/erlaubte Quelle separat
   ausweisen.
2. All Jobs muss als **All Jobs Scraper via Apify** erscheinen; JobsPipe und
   EURES behalten eigene Labels und Operation IDs.
3. Prüfen, dass strukturierte LinkedIn-/Indeed-/Glassdoor-Karten sichtbar sein
   können, rohe Brave/Exa/You-Treffer dieser Domains aber weiter abgewiesen
   werden.
4. Zwei Indeed-Links mit verschiedenen `jk`-IDs dürfen nicht deduplizieren;
   reine Trackingvarianten derselben Stelle sollen deduplizieren.
5. JobsPipe soll Rollenbegriffe und Skills sinnvoller treffen; seine Treffer
   können deutschlandweit sein und werden nach Rolle/Distanz geordnet.
6. Eine JSearch-Suche darf nach dem erweiterten Read-Fenster beitragen oder eine
   spezifische Timeout/Deadline-Zeile erzeugen, aber nicht unsichtbar nach dem
   Explore-Abschluss weiterlaufen.
7. Compass, Match, Routing, Job Detail, Archive, Ratings und Application History
   stichprobenartig auf unverändertes Verhalten prüfen.

## 7. Source-ZIP dumpen und prüfen

App wieder stoppen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2b.zip -Algorithm SHA256
```

## 8. Geprüft zu GitHub hochladen

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2b"

git tag -a v0.7.2b -m "BetterOption v0.7.2b"
git push origin v0.7.2b

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Pfade leer bleiben. Das Push-Script zeigt
die exakt gestagten Produktdateien und fragt vor Commit und Push nach.
