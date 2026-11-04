> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2 lokal sichern, installieren, testen und veröffentlichen

Dieser Ablauf gilt für die lokale Windows-App unter
`http://127.0.0.1:8000`. `v0.7.2` wird dadurch nicht auf einen Server
ausgerollt.

## 1. App stoppen und private Daten sichern

Im Fenster mit `run_web.ps1` `Ctrl+C` drücken und den vollständigen
Uvicorn-Shutdown abwarten. Danach:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v072-$stamp"
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

`git ls-files` muss leer bleiben. Dieses Backup enthält Schlüssel und private
Bewerbungsdaten; es gehört weder in GitHub noch in das Release-ZIP.

`dump_release.ps1` ist bewusst ein **Source-Release-Dump**, kein Datenbankbackup.
Es nimmt keine `.env`, Datenbank, Uploads oder CV-Dateien mit.

## 2. Release installieren

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2"

# Der Installer bewahrt .env. Nur den exakten alten öffentlichen 0.7.1s-
# User-Agent-Standard auf 0.7.2 anheben; Schlüssel und andere Werte bleiben unberührt.
$environmentPath = ".\.env"
if (Test-Path $environmentPath) {
  $oldAgent = "BetterOption/0.7.1s-source-facts (+https://github.com/ILLVAN/betteroption)"
  $newAgent = "BetterOption/0.7.2 (+https://github.com/ILLVAN/betteroption)"
  $environmentText = Get-Content $environmentPath -Raw
  if ($environmentText.Contains($oldAgent)) {
    $updatedEnvironmentText = $environmentText.Replace($oldAgent, $newAgent)
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

Erwartet werden `0.7.2` und weiterhin der Alembic-Head
`0030_verified_job_posters`. Installer und Release-ZIP überschreiben keine
lokale `.env`, Datenbank, CV-Texte, Uploads oder Backups.

Der gezielte Replace oben betrifft nur den exakt ausgelieferten alten
User-Agent-Text. Selbst gewählte Agent-Werte werden nicht verändert. Ohne
diesen Schritt würde eine aus `v0.7.1s` erhaltene `.env` weiterhin die alte
Versionskennung an Transitous, Valhalla und den OSM-Geocoder senden.

## 3. JSearch gezielt prüfen

Ohne `--live` erfolgt kein Request:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
```

Genau einen synthetischen Plan-Request ausdrücklich freigeben:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

Ein erfolgreicher Check zeigt `category: success`, eine Ergebniszahl sowie
feste `detail`-/`next_step`-Texte. Bei Fehlern erscheinen getrennte Kategorien
für Konfiguration, Authentifizierung, Plan, Rate Limit, Netzwerk, Request oder
Response. Schlüssel, Suchtext, URL, Response-Body und Benutzerdaten werden nicht
ausgegeben oder gespeichert.

## 4. Release-Gate und Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Der Test-Runner prüft Formatierung, Lint, die vollständige Suite und
Bytecode-Kompilierung.

## 5. Manuelle Abnahme

1. **Compass:** CV-Kachel ist zunächst kompakt und lässt sich gezielt öffnen.
2. **Compass → Experience evidence:** Eine gesprochene Sprache suchen,
   aktivieren und ein Level speichern; nach Reload und Persona-Wechsel bleibt
   der Wert nur bei der richtigen Persona.
3. Die optionale Programmiersprachen-Kachel öffnen, einen Wert speichern und
   wieder entfernen. Guided readiness und Match-Neuberechnung reagieren auf
   Hinzufügen und Entfernen.
4. Standardgrenzen für Train, Car und Bicycle prüfen: Sie zählen im Match,
   erscheinen aber nicht doppelt als Compass-Checks. Eine eigene Walking- oder
   Flight-Regel bleibt sichtbar.
5. **Explore:** Filters, Info, Source contribution und Portal links öffnen und
   schließen; ohne Öffnen bleibt die Seite ruhig.
6. Eine große Ergebnisliste prüfen: Explore nutzt kompakte volle Zeilen; Home,
   Match und Archive behalten Karten. Ort, Ranking, Quelle und bestehende
   Aktionen bleiben erreichbar.
7. Source contribution zeigt **Exa**, niemals **Exa fallback**.
8. JSearch allein aktivieren und eine kleine Suche durchführen. Ein gültiger
   `data.jobs`-Response darf nicht mehr als `JSearchResponseError` enden.
9. **Job Detail:** Routing zeigt einen Hauptwert und darunter die kleinere
   Range. Employer-Relationship-Felder und Saved-Correction-Badge sind lesbar.
10. Job Facts bleiben vor Employer Facts; EURES-Regionen/Distanz, Add-Reihenfolge,
    deduplizierte Bewerbungsadresse und Home-Badges aus `v0.7.1s` bleiben intakt.

## 6. Source-ZIP bauen und prüfen

App wieder stoppen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2.zip -Algorithm SHA256
```

Das Script verwendet `scripts/build_release.py`; es erstellt keinen beliebigen
Ordner-Dump. Trotzdem das ZIP vor Veröffentlichung öffnen und prüfen, dass nur
Produktdateien enthalten sind.

## 7. GitHub-Release

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2"

git tag -a v0.7.2 -m "BetterOption v0.7.2"
git push origin v0.7.2

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Der letzte Status muss sauber sein und `v0.7.2` auf `HEAD` zeigen.
