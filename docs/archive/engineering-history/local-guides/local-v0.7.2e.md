> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2e lokal installieren, testen, dumpen und veröffentlichen

`v0.7.2e` ersetzt das nicht installierbare `v0.7.2d`-Archiv. Der fehlgeschlagene
`d`-Lauf hat den Quellbaum bereits überlagert, aber `.env`, `local-data`, Uploads
und lokale Backups bewahrt. `e` kann direkt darüber installiert werden; ein
Rollback auf `c` ist nicht nötig.

## 1. Installation

App stoppen und im bestehenden Windows-Repository ausführen:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2e.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2e"
```

Danach beide getrennten Versionskennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartet werden nacheinander:

```text
0.7.2e
0.7.2+e
```

Die erste Kennung gehört zur App, die zweite zur installierten Python-
Distribution. `0.7.2+e` ist absichtlich PEP-440-konform. Es gibt keine neue
Datenbankmigration; bestehende `matching-v0.7.2c`-Resultate bleiben aktuell.

## 2. Diagnosen und Tests

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Für diesen reinen Packaging-Hotfix ist kein erneuter kostenpflichtiger Live-
Provider-Test erforderlich. Die manuelle Produktabnahme aus Abschnitt 4 des
[`v0.7.2d`-Leitfadens](local-v0.7.2d.md) bleibt unverändert gültig; dessen
Installations- und Veröffentlichungsbefehle sind ausdrücklich zurückgezogen.

## 3. Dump

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2e.zip -Algorithm SHA256
```

## 4. Git-Upload

Nur `e` veröffentlichen. Einen eventuell vorhandenen `v0.7.2d`-Tag nicht
verschieben oder wiederverwenden.

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2e"

git tag -a v0.7.2e -m "BetterOption v0.7.2e"
git push origin v0.7.2e
```

`git ls-files` muss für die privaten Pfade leer bleiben. Das ursprüngliche
`v0.7.2d`-ZIP mit der fehlerhaften Paketversion ist zurückgezogen und darf nicht
weiterverwendet werden.
