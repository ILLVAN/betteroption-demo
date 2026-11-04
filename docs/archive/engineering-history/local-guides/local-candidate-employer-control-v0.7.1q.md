> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1q lokal sichern, installieren, testen und pushen

Dieser Ablauf ist ausschließlich für `http://127.0.0.1:8000`. Q wird in dieser
Iteration **nicht** auf einen Server ausgerollt.

## 1. App stoppen und lokale Daten sichern

Im Fenster mit `run_web.ps1` zuerst `Ctrl+C` drücken und den vollständigen
Uvicorn-Shutdown abwarten. Danach in PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071q-$stamp"
New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null
Copy-Item ".\.env" "$backup\.env" -ErrorAction Stop
Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop

$sourceDb = (Resolve-Path ".\local-data\betteroption.db").Path
$backupRoot = (Resolve-Path $backup).Path
$backupDb = Join-Path $backupRoot "local-data\betteroption.db"
$dump = Join-Path $backupRoot "betteroption-$stamp.sql"

# Native SQLite snapshot, if sqlite3.exe is installed:
$backupDbForSqlite = $backupDb.Replace('\', '/')
& sqlite3.exe $sourceDb ".backup '$backupDbForSqlite'"

# Portable SQL dump:
& sqlite3.exe $backupDb ".dump" | Set-Content -Encoding utf8 $dump

# Verify both files with the project Python:
@'
import sqlite3
import sys
from pathlib import Path

snapshot, dump = map(lambda value: Path(value).resolve(), sys.argv[1:3])
with sqlite3.connect(snapshot) as database:
    result = database.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite integrity check failed: {result}")
with sqlite3.connect(":memory:") as restored:
    restored.executescript(dump.read_text(encoding="utf-8-sig"))
    result = restored.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQL dump restore check failed: {result}")
print("SQLite snapshot and SQL dump verified")
'@ | .\.venv\Scripts\python.exe - $backupDb $dump

Get-FileHash $backupDb -Algorithm SHA256
Get-FileHash $dump -Algorithm SHA256
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

`git ls-files` muss leer bleiben. Das Backup enthält API-Schlüssel, Persona- und
Bewerbungsdaten und darf nicht nach GitHub.

Falls `sqlite3.exe` nicht installiert ist, erzeugt dieser Python-Fallback
denselben konsistenten Snapshot und SQL-Dump:

```powershell
@'
import sqlite3
import sys
from pathlib import Path

source, snapshot, dump = map(lambda value: Path(value).resolve(), sys.argv[1:4])
snapshot.parent.mkdir(parents=True, exist_ok=True)
snapshot.unlink(missing_ok=True)
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as live:
    with sqlite3.connect(snapshot) as backup:
        live.backup(backup)
with sqlite3.connect(snapshot) as backup:
    if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("SQLite integrity check failed")
    dump.write_text(
        "\n".join(backup.iterdump()) + "\n",
        encoding="utf-8",
    )
print(snapshot)
print(dump)
'@ | .\.venv\Scripts\python.exe - $sourceDb $backupDb $dump
```

## 2. Q installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1q_candidate_employer_control.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1q-candidate-employer-control"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartet: `0.7.1q-candidate-employer-control`. Beim Start wird die lokale
SQLite-Datenbank auf `0030_verified_job_posters` migriert.

## 3. Testen und starten

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

## 4. Lokale Abnahme

1. Home, Compass, Add, Explore, Match, Apply und Archive öffnen. Die farbige
   Hauptaktion liegt jeweils randlos in einer hellen Standard-Kachel.
2. In Job Detail einen eindeutigen privaten Wert ändern und **Save changes and
   update score** ausführen. Der Score soll ohne vollständige Provider-Recherche
   aktualisiert werden.
3. Einen relevanten Compass-Wert ändern und prüfen, dass **Fully Rematch this
   Job** nur bei veralteter Evidenz aktiv wird.
4. Salary Minimum und Target testen: Werte laufen in 1k-Schritten bis 300k; ein
   unberührtes Target bleibt neutral.
5. Explore mit deutscher und englischer Berufsbezeichnung testen. Nur geprüfte
   Einzelanzeigen dürfen auswählbar werden.
6. Prepare Package prüfen: veröffentlichte E-Mail/Adresse/Anforderungen dürfen
   erscheinen; unbekannte Angaben bleiben `Unknown` und werden nicht erfunden.
7. Unter Account den Job-poster-Zugang öffnen. Ein normaler Account kann nur
   anfragen. Nach Operator-Freigabe kann er lokal einen Entwurf erstellen und
   veröffentlichen. Candidate-Personas und Accounts bleiben isoliert.
8. Cover Letter **Shorter** muss den Entwurf sichtbar verkürzen; Drafts bleiben
   editierbar und werden nie automatisch versendet.

## 5. Nach lokaler Abnahme nach GitHub pushen

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
  -CommitMessage "Release BetterOption v0.7.1q-candidate-employer-control"

git tag -a v0.7.1q-candidate-employer-control `
  -m "BetterOption v0.7.1q candidate and employer control"
git push origin v0.7.1q-candidate-employer-control

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor der Bestätigung prüfen, dass `.env`, Datenbanken, `local-data`,
`local-backups`, CVs, Uploads und Schlüssel nicht gestaged sind.

## 6. Wiederherstellung

Die App stoppen. Den verifizierten Snapshot niemals bei laufender App
überschreiben. Für einen separaten Restore-Test:

```powershell
$dump = ".\local-backups\before-v071q-YYYYMMDD-HHMMSS\betteroption-YYYYMMDD-HHMMSS.sql"
$restore = ".\local-backups\restored-v071q-check.db"
Remove-Item $restore -Force -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(sys.argv[2]); db.executescript(open(sys.argv[1], encoding='utf-8-sig').read()); print(db.execute('PRAGMA integrity_check').fetchone()[0])" `
  $dump $restore
```

Erst nach einem erfolgreichen Restore-Test entscheiden, ob die aktive lokale
Datenbank ersetzt werden soll. Ein Server- oder Alpha-Rollout gehört nicht zu Q.
