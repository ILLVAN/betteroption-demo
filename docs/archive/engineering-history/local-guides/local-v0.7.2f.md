> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2f lokal installieren, testen, dumpen und veröffentlichen

`v0.7.2f` wird direkt über die gepushte `v0.7.2e`-Baseline installiert. Die
Installation bewahrt `.env`, `local-data`, Uploads und lokale Backups. Vor dem
Overlay die App vollständig stoppen und eine private Sicherung von `.env` und
`local-data` erstellen.

## 1. Installation

Im bestehenden Windows-Repository ausführen:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2f.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2f"
```

Danach beide getrennten Versionskennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartete Ausgabe:

```text
0.7.2f
0.7.2+f
```

`0.7.2+f` ist die kanonische PEP-440-Paketversion. Es gibt keine
Datenbankmigration. Der Matchingvertrag ändert sich auf `matching-v0.7.2f`;
gespeicherte ältere Ergebnisse werden deshalb bewusst als veraltet angezeigt
und beim nächsten vollständigen Matching neu berechnet.

## 2. Erhaltene `.env` sicher aktualisieren

Der Installer bewahrt `.env` absichtlich. `v0.7.2f` ergänzt die eng begrenzte
semantische Prüfung ungeklärter Match-Kriterien und beschreibt diese
Verarbeitung in der Privacy Notice. Deshalb muss eine bekannte ältere
Draft-Kennung nach dem Lesen der aktualisierten Notice auf
`2026-08-05-draft` wechseln. Der folgende Block ersetzt ausschließlich bekannte
ältere BetterOption-Draftwerte, ergänzt die Kennung nur, wenn sie fehlt, und
lässt eigene oder extern geprüfte Kennungen unverändert:

```powershell
$environmentPath = ".\.env"
if (Test-Path $environmentPath) {
  $environmentText = Get-Content $environmentPath -Raw
  $updatedEnvironmentText = $environmentText
  $supersededPrivacyDrafts = @(
    "2026-08-01-draft",
    "2026-08-02-draft",
    "2026-08-04-draft",
    "2026-08-04b-draft"
  )
  foreach ($oldDraft in $supersededPrivacyDrafts) {
    $updatedEnvironmentText = $updatedEnvironmentText.Replace(
      "BETTEROPTION_LEGAL_PRIVACY_VERSION=$oldDraft",
      "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-draft"
    )
  }
  if ($updatedEnvironmentText -notmatch "(?m)^BETTEROPTION_LEGAL_PRIVACY_VERSION=") {
    $updatedEnvironmentText = $updatedEnvironmentText.TrimEnd() +
      [Environment]::NewLine +
      "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-draft" +
      [Environment]::NewLine
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

Eine eigene oder bereits rechtlich freigegebene Kennung nicht automatisch
überschreiben: zuerst den neuen Semantic-Matching-Abschnitt prüfen und dann eine
bewusste neue Versionskennung setzen. Bei Accounts kann die Änderung eine neue
Zustimmung auslösen. Anschließend die App neu starten.

## 3. Diagnose und vollständiger Test

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

`diagnose_jsearch.py` führt ohne `--live` keinen Provideraufruf aus. Ein neuer
Live-Probe ist für dieses Release nicht erforderlich.

## 4. Manuelle Abnahme

1. Unter Account die Profil-JSON laden. Sie darf nur Account, Personas und den
   jeweils aktuellen Compass enthalten—keine Tasks, Provideroperationen,
   Explore-Snapshots, Runs oder Matchhistorien.
2. Im Compass prüfen: Guided Setup ist die Hauptaktion; Add, Explore und Open
   Matching folgen als Nebenaktionen.
3. Eine Explore-Suche öffnen. Im Source-Run-Tile einzelne Quellen abwählen und
   wieder aktivieren. Die fertige Ergebnisliste muss ohne neuen Provideraufruf
   sofort reagieren.
4. Einen über mehrere Quellen gefundenen Job prüfen: Er bleibt sichtbar, solange
   mindestens eine seiner Quellen aktiv ist.
5. Sicherstellen, dass Such-/Kategorie-Startseiten nicht als Einzeljob erscheinen.
6. Einen Job wählen, dessen Seite Robots/Login/Extraktion blockiert. Er darf nach
   dem Importversuch nicht still aus Explore verschwinden; nur eindeutig
   abgelaufene oder nicht als Einzelstelle erkennbare Seiten werden entfernt.
7. Einen Compass mit einem Must-have wie höchstens zwei Bürotagen gegen eine
   glaubwürdig belegte reine On-site-Stelle matchen. Der Widerspruch muss mit
   seiner Unsicherheit sichtbar sein und bei mittlerer oder hoher Sicherheit den
   Job blockieren. Schwache Hinweise dürfen keinen Blocker erfinden.
8. Im Jobdetail Feedback speichern. Die Schaltfläche muss der schwarzen
   Primäraktion entsprechen.

## 5. Release-ZIP

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2f.zip -Algorithm SHA256
```

## 6. Git-Upload

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2f"

git tag -a v0.7.2f -m "BetterOption v0.7.2f"
git push origin v0.7.2f
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Pfade leer bleiben. Den bestehenden
`v0.7.2e`-Tag nicht verschieben oder wiederverwenden.
