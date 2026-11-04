> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1p lokal sichern, installieren, testen und pushen

Dieser Ablauf unterstützt weiterhin nur `http://127.0.0.1:8000`. Die
Installation erhält `.env` und `local-data`; trotzdem zuerst ein unabhängig
prüfbares Backup erstellen.

## 1. App stoppen und `.env`, SQLite-Snapshot und SQL-Dump sichern

Im Fenster mit `run_web.ps1` zuerst `Ctrl+C` drücken und auf das vollständige
Uvicorn-Shutdown warten. Danach in einem neuen PowerShell-Fenster:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071p-$stamp"
New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null
Copy-Item ".\.env" "$backup\.env" -ErrorAction SilentlyContinue
Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop
Remove-Item "$backup\local-data\betteroption.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$backup\local-data\betteroption.db-wal" -Force -ErrorAction SilentlyContinue
Remove-Item "$backup\local-data\betteroption.db-shm" -Force -ErrorAction SilentlyContinue

$sourceDb = (Resolve-Path ".\local-data\betteroption.db").Path
$backupRoot = (Resolve-Path $backup).Path
$backupDb = Join-Path $backupRoot "local-data\betteroption.db"
$dump = Join-Path $backupRoot "betteroption-$stamp.sql"

@'
import sqlite3
import sys
from pathlib import Path

source, snapshot, dump = map(lambda value: Path(value).resolve(), sys.argv[1:4])
if not source.is_file():
    raise SystemExit(f"Database not found: {source}")
snapshot.parent.mkdir(parents=True, exist_ok=True)
snapshot.unlink(missing_ok=True)

with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as live:
    with sqlite3.connect(snapshot) as backup:
        live.backup(backup)
with sqlite3.connect(snapshot) as backup:
    result = backup.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite integrity check failed: {result}")
    with dump.open("w", encoding="utf-8", newline="\n") as output:
        for statement in backup.iterdump():
            output.write(statement + "\n")

print(f"SQLite snapshot verified: {snapshot}")
print(f"Portable SQL dump created: {dump}")
'@ | .\.venv\Scripts\python.exe - $sourceDb $backupDb $dump

.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(':memory:'); db.executescript(open(sys.argv[1], encoding='utf-8').read()); print('SQL dump verified successfully')" `
  $dump

Get-FileHash $backupDb -Algorithm SHA256
Get-FileHash $dump -Algorithm SHA256
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

`git ls-files` muss leer bleiben. Das Backup enthält Schlüssel und private
Persona-/Bewerbungsdaten und gehört nicht in GitHub.

## 2. P installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1p_local_stability.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1p-local-stability"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartete Version: `0.7.1p-local-stability`. P enthält keine neue Migration;
der Datenbank-Head bleibt `0029_job_detail_preferences`.

## 3. Testen und lokal starten

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Manuell prüfen:

1. Home öffnen: Job- und Employer-Rating haben gleich breite Spalten und je
   eine vollständige Sternzeile.
2. Eine vorhandene Job Card öffnen und `/apply` aufrufen. Beide Seiten dürfen
   keinen Internal Server Error liefern.
3. Einen vollständigen Match ausführen und danach das Ergebnis erneut öffnen.
   Im Log darf keine `Expected tuple[SalaryEvidence, ...]`-Warnung erscheinen.
4. Im Jobdetail prüfen, dass `Expected salary orientation` immer sichtbar ist.
   Ohne belastbare Schätzung muss dort `Unavailable` stehen; es darf keine Zahl
   erfunden werden, und die privaten Minimum-/Maximum-Felder bleiben nutzbar.
5. Mit erlaubtem You.com-Provider Explore ausführen. Resultate aus
   `results.web` sowie Markdown-Seiten können beitragen; Nicht-Jobs und
   unbrauchbare Links bleiben ausgeschlossen.
6. Persona-Isolation, Compass, Add/manual input, Archive und bestehende Drafts
   regressionsweise prüfen.

## 4. Nach lokaler Abnahme nach GitHub pushen

App erneut mit `Ctrl+C` stoppen:

```powershell
cd C:\projects\betteroption
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1p-local-stability"

git tag -a v0.7.1p-local-stability `
  -m "BetterOption v0.7.1p local stability"
git push origin v0.7.1p-local-stability

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor der Bestätigung im Push-Skript prüfen, dass `.env`, Datenbanken,
`local-data`, `local-backups`, CVs, Uploads und Schlüssel nicht gestaged sind.

## 5. Wiederherstellung

Bei einem Problem die App stoppen und den verifizierten Vor-P-Snapshot in eine
separate Kopie des Arbeitsstands übernehmen. Alternativ aus dem SQL-Dump eine
neue Datenbank erstellen:

```powershell
$dump = ".\local-backups\before-v071p-YYYYMMDD-HHMMSS\betteroption-YYYYMMDD-HHMMSS.sql"
$restore = ".\local-backups\restored-v071p-check.db"
Remove-Item $restore -Force -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(sys.argv[2]); db.executescript(open(sys.argv[1], encoding='utf-8').read()); print(db.execute('PRAGMA integrity_check').fetchone()[0])" `
  $dump $restore
```

Die aktive Datenbank niemals bei laufender App überschreiben.
