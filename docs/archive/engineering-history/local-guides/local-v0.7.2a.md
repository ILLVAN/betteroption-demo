> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2a lokal sichern, installieren, testen, dumpen und veröffentlichen

Dieser Ablauf gilt für die lokale Windows-App unter
`http://127.0.0.1:8000`. `v0.7.2a` wird dadurch nicht auf einen Server
ausgerollt. Alle Befehle werden im Repository-Stamm ausgeführt.

## 1. App stoppen und private Daten sichern

Im Fenster mit `run_web.ps1` `Ctrl+C` drücken und den vollständigen
Uvicorn-Shutdown abwarten. Danach:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v072a-$stamp"
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

`git ls-files` muss leer bleiben. Das Backup enthält Schlüssel und private
Bewerbungsdaten; es gehört weder in GitHub noch in das Release-ZIP.
`dump_release.ps1` ist ein Source-Release-Dump und kein Datenbankbackup.

## 2. Release installieren und die erhaltene `.env` aktualisieren

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2a.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2a"

# Der Installer bewahrt .env. Nur bekannte 0.7.2-Releasewerte ersetzen und
# fehlende JobsPipe-Grenzen ergänzen; Schlüssel und eigene Werte bleiben erhalten.
$environmentPath = ".\.env"
if (Test-Path $environmentPath) {
  $environmentText = Get-Content $environmentPath -Raw
  $updatedEnvironmentText = $environmentText.Replace(
    "BetterOption/0.7.2 (+https://github.com/ILLVAN/betteroption)",
    "BetterOption/0.7.2a (+https://github.com/ILLVAN/betteroption)"
  ).Replace(
    "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-02-draft",
    "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-04-draft"
  )

  $jobspipeDefaults = @(
    "BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=150",
    "BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD=0"
  )
  foreach ($entry in $jobspipeDefaults) {
    $name = $entry.Split("=", 2)[0]
    if ($updatedEnvironmentText -notmatch "(?m)^$([regex]::Escape($name))=") {
      $updatedEnvironmentText = $updatedEnvironmentText.TrimEnd() +
        [Environment]::NewLine + $entry + [Environment]::NewLine
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

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartet werden `0.7.2a` und weiterhin der Alembic-Head
`0030_verified_job_posters`. Der Installer überschreibt weder `.env` noch
Datenbank, CV-Texte, Uploads oder Backups. `0` beim JobsPipe-Kostenwert bedeutet
**unpriced**, nicht kostenlos.

## 3. JSearch gezielt prüfen

Ohne `--live` erfolgt kein Request:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
```

Genau einen synthetischen Plan-Request ausdrücklich freigeben:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

Ein erfolgreicher Check zeigt `category: success`, eine Ergebniszahl und feste
`detail`-/`next_step`-Texte. Fehler werden unter anderem als `authentication`,
`plan`, `rate_limit`, `timeout`, `dns`, `tls`, `proxy`, `connection`,
`provider_unavailable`, `request` oder `response` eingeordnet. Damit lässt sich
ein lokales DNS-/TLS-/Proxyproblem von einem HTTP-5xx-Fehler des Providers
trennen. Schlüssel, Suchtext, Request-URL, Response-Body und Benutzerdaten
werden nicht ausgegeben oder gespeichert.

## 4. JobsPipe bewusst freigeben

JobsPipe und EURES verwenden bei Bedarf dasselbe `APIFY_API_TOKEN`, sind aber
zwei getrennte Empfänger und Provider. Deshalb aktiviert ein vorhandenes Token
JobsPipe nicht automatisch:

1. App einmal starten und **Account → Provider choices** öffnen.
2. **JobsPipe via Apify** ausdrücklich aktivieren; **EURES via Apify** bleibt
   eine eigene Auswahl.
3. Für Hosted/Staging bleibt JobsPipe trotz Auswahl geschlossen, solange der
   Processor-Review-Schalter nicht freigegeben ist.

Die aktuelle Prüfgrenze und die offenen Vertrags-/Quellenfragen stehen im
[JobsPipe source review](../providers/job-source-review-v0.7.2a.md).

## 5. Vollständiges Test-Gate und Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Der Test-Runner prüft Formatierung, Lint, die vollständige Suite und
Bytecode-Kompilierung.

## 6. Manuelle Abnahme

1. **Explore:** Eine kleine Suche mit EURES und JobsPipe durchführen. In Source
   contribution stehen **EURES via Apify** und **JobsPipe via Apify** getrennt.
2. In den Provider-Operations stehen getrennte IDs/Zeilen (`apify-eures` und
   `apify-jobspipe`), Einheiten und Kostenschätzungen. Kein JobsPipe-Lauf darf
   als EURES erscheinen.
3. JobsPipe in Account deaktivieren, erneut suchen und prüfen, dass nur dieser
   Provider ausbleibt. Danach die gewünschte Auswahl wiederherstellen.
4. JSearch allein aktivieren und eine kleine Suche durchführen. Ein gültiger
   `data.jobs`-Response wird akzeptiert; ein Fehlschlag trägt die spezifische,
   secret-safe Transport- oder Provider-Kategorie.
5. **Match:** **Info**, **Run facts** und **Select jobs to delete** sind zunächst
   geschlossen. Ein veralteter Lauf zeigt weiterhin den sichtbaren Badge
   **Review notices**.
6. Einen Job markieren: Auswahlzähler und Löschbutton werden aktualisiert;
   ohne Auswahl bleibt der Button deaktiviert und die Bestätigung erhalten.
7. Explore behält die akzeptierte kompakte Ergebnisdarstellung. Compass,
   Routing, Job Detail, Archive, Ratings und Application History unverändert
   stichprobenartig prüfen.

## 7. Source-ZIP dumpen und prüfen

App wieder stoppen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2a.zip -Algorithm SHA256
```

Das Script verwendet `scripts/build_release.py` und schließt Runtime-Daten,
Umgebungsdateien, Schlüsseltypen, Datenbanken, Uploads, Backups, CV-/Resume-
Artefakte und nicht freigegebene Office-/PDF-Dateien aus. Das ZIP vor der
Veröffentlichung trotzdem öffnen und den Inhalt prüfen.

## 8. Geprüft zu GitHub hochladen

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2a"

git tag -a v0.7.2a -m "BetterOption v0.7.2a"
git push origin v0.7.2a

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Pfade leer bleiben. Der letzte Status muss
sauber sein und `v0.7.2a` auf `HEAD` zeigen. Das Push-Script zeigt die exakt
gestagten Dateien und fragt vor Commit und Push erneut nach Bestätigung.
