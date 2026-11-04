> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2c lokal sichern, installieren, testen, dumpen und veröffentlichen

Dieser Ablauf gilt für die lokale Windows-App unter
`http://127.0.0.1:8000`. Alle Befehle werden im Repository-Stamm ausgeführt.

## 1. Backup

Im Fenster mit `run_web.ps1` `Ctrl+C` drücken und den vollständigen Uvicorn-
Shutdown abwarten. Danach:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v072c-$stamp"
New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null
if (Test-Path ".\.env") {
  Copy-Item ".\.env" "$backup\.env" -ErrorAction Stop
}
if (Test-Path ".\local-data") {
  Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop
}
if (Test-Path ".\uploads") {
  Copy-Item ".\uploads" "$backup\uploads" -Recurse -Force -ErrorAction Stop
}

git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads
```

`git ls-files` muss leer bleiben. Backup, `.env`, Datenbank, CVs und Uploads
gehören weder in GitHub noch in das Source-ZIP.

## 2. Installation

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2c.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2c"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Die erste Zeile erwartet `0.7.2c`. Python normalisiert den Buchstaben `c` in
Paketmetadaten nach PEP 440; die zweite Zeile darf deshalb `0.7.2rc0` anzeigen.
App, Archiv und Git-Tag heißen weiterhin bewusst `0.7.2c`. Es gibt keine neue
Datenbankmigration; der Head bleibt `0030_verified_job_posters`.

## 3. Erhaltene `.env` aktualisieren

Der Installer bewahrt `.env` absichtlich. Der folgende Block ersetzt nur die
bekannten `0.7.2b`-User-Agents und lässt Schlüssel, eigene Werte und die
Datenschutzversion unverändert:

```powershell
$environmentPath = ".\.env"
if (Test-Path $environmentPath) {
  $environmentText = Get-Content $environmentPath -Raw
  $updatedEnvironmentText = $environmentText.Replace(
    "BetterOption/0.7.2b (+https://github.com/ILLVAN/betteroption)",
    "BetterOption/0.7.2c (+https://github.com/ILLVAN/betteroption)"
  )

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

Danach `.env.example` vergleichen. Ein Wert `0` bei
`*_ESTIMATED_COST_*`, `*_COST_LIMIT_*` oder `MAX_TOTAL_CHARGE_USD` bedeutet je
nach Feld **unpriced** oder **kein konfigurierter Kosten-Cap**, niemals
automatisch kostenlos. Vor Einladungen müssen echte Preise und nicht-null
Safety Rails festgelegt werden.

## 4. Test

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Der Brave-Probe verbraucht einen festen Search-Request. Nur JSearch `--live`
sendet den einen festen synthetischen JSearch-Request; er darf bis etwa
90 Sekunden benötigen. Beide Probes senden keine Compass- oder CV-Inhalte.

## 5. Manuelle Abnahme

1. Eine Explore-Suche bis zum Abschluss laufen lassen. Den Distanzregler
   bewegen: bekannte nicht-remote Treffer außerhalb des Limits verschwinden
   sofort, ohne neuen Providerlauf; Remote-Treffer bleiben entsprechend den
   Remote-Filtern sichtbar.
2. **Any distance** am rechten Ende prüfen. Ein Treffer ohne verlässliche
   Distanz bleibt sichtbar und bekommt keine erfundene Entfernung.
3. In breiter und schmaler Ansicht kontrollieren: Auswahl, Provider, vollständiger
   Arbeitgeber und Ort bilden die Metazeile; der sans-serif Jobtitel liegt in
   einer eigenen Zeile.
4. In **What the last source run contributed** jede aktivierte Quelle getrennt
   prüfen. Auf Operations beachten: die Tages-Fehlerkategorien enthalten alle
   Versuche seit 00:00 UTC und sind nicht nur der letzte Explore-Lauf.
5. JSearch soll im aktuellen Lauf beitragen oder genau eine spezifische,
   secret-safe Kategorie zeigen. `JSearchRequestError` darf keine späteren
   Synonymanfragen desselben Laufs auslösen. Der Request enthält weder `fields`
   noch `num_pages`.
6. JobsPipe mit einem breiten Rollen-/Skillprofil testen, beispielsweise
   Python. Es darf mehrere kurze, unabhängige Läufe geben; Treffer werden nach
   gemeinsamer Deduplizierung, Relevanz und Distanz geordnet. Ein guter naher
   Grenztreffer darf vor einem schwachen fernen Inlandstreffer stehen.
7. All Jobs in Apify prüfen: BetterOption startet bei langsamer Plattform nur
   einen bezahlten Actor-Run, pollt denselben Run und liest dessen Dataset. Es
   darf keinen automatischen zweiten Run als Timeout-Retry geben.
8. Brave bei einer englischen und einer deutschen Rolle testen. Extra-Snippets
   dürfen relevante Evidenz beitragen; Seite zwei wird nur mit Braves
   `more_results_available`-Signal abgerufen.
9. In Compass einen Gehaltswert mit CHF oder GBP speichern und über **Read
   saved input** kontrollieren. ISO-Währung und Betrag müssen erhalten bleiben.
   Eine EUR-Stelle darf nicht durch einen erfundenen FX-Kurs numerisch bestehen
   oder scheitern.
10. Die optionale Programming-languages-Kachel muss kompakt bleiben. Danach
    Compass, Match, Routing, Job Detail, Archive, Ratings und Application
    History stichprobenartig prüfen.

## 6. Dump

App wieder stoppen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2c.zip -Algorithm SHA256
```

## 7. Git-Upload

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2c"

git tag -a v0.7.2c -m "BetterOption v0.7.2c"
git push origin v0.7.2c

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Pfade leer bleiben. Das Push-Script zeigt
die exakt gestagten Produktdateien und fragt vor Commit und Push nach.
