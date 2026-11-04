> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2d lokal sichern, installieren, testen, dumpen und veröffentlichen

> **Nicht mehr installieren oder veröffentlichen.** Das `d`-Archiv besitzt eine
> ungültige Python-Paketversion. Direkt mit dem
> [`v0.7.2e`-Leitfaden](local-v0.7.2e.md) fortfahren. Die manuellen
> Produktprüfungen in Abschnitt 4 bleiben für den unveränderten Funktionsumfang
> gültig.

## 1. Vorher sichern

App mit `Ctrl+C` stoppen und auf `Finished server process` warten. Danach die
private `.env`, `local-data`, Uploads und nötige lokale Backups außerhalb des
Repositorys sichern.

## 2. Release installieren

Im bestehenden Windows-Repository:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2d.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2d"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Die erwartete App-Version ist `0.7.2d`. Der Installer überschreibt weder `.env`
noch `local-data`. Es gibt keine neue Datenbankmigration, und bestehende
`matching-v0.7.2c`-Resultate bleiben aktuell.

## 3. `.env` kontrolliert aufräumen

- Reale Schlüssel nicht kopieren oder anzeigen; nur die neuen Werte lokal
  einsetzen.
- `BETTEROPTION_EXA_FALLBACK_MIN_RESULTS` durch
  `BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS` ersetzen.
- Nach dem Erstellen lokaler Testkonten
  `BETTEROPTION_REGISTRATION_MODE=disabled` setzen.
- Die drei öffentlichen User-Agents auf `BetterOption/0.7.2d` aktualisieren und
  ihren Kontaktteil vorerst behalten.
- Alle aktuellen Background- und Kosteneinstellungen gegen
  [`.env.example`](../../../../.env.example) prüfen. Null-Dollar-Limits sind deaktiviert.

Der vollständige lokale/hosted Vergleich steht im
[Environment-Audit](local-environment-v0.7.2d.md).

## 4. Diagnosen und Tests

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

Brave und JSearch Live-Probes verbrauchen jeweils genau einen kontrollierten
Request. Prüfen:

- Sterne ändern den sichtbaren Compatibility Score ohne Seitenwechsel.
- Ein Employer-Rating aktualisiert mehrere Karten desselben Arbeitgebers.
- Exclusion-Konflikte zeigen eine Warnung und einen niedrigeren Explore-Score.
- Distanzstopps, Remote-Ausnahme, Fresh/Older und Serif-Titel funktionieren.
- Ein zweiter Tab erzeugt keinen identischen zweiten Background-Task.
- Fortschrittstext rotiert, technische Überschrift wird nicht doppelt gezeigt.

## 5. Dump

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2d.zip -Algorithm SHA256
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
  -CommitMessage "Release BetterOption v0.7.2d"

git tag -a v0.7.2d -m "BetterOption v0.7.2d"
git push origin v0.7.2d

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Pfade leer bleiben. Vor dem Push das ZIP
und die gestagten Dateien weiterhin manuell prüfen.
