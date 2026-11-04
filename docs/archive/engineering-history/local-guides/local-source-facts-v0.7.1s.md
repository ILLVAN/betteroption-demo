> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1s lokal sichern, installieren, testen und pushen

Dieser Ablauf gilt für die lokale App unter `http://127.0.0.1:8000`. S wird in
dieser Iteration nicht auf einen Server ausgerollt.

## 1. App stoppen und Daten vollständig sichern

Im Fenster mit `run_web.ps1` zuerst `Ctrl+C` drücken und den vollständigen
Uvicorn-Shutdown abwarten. Danach in PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071s-$stamp"
New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null
Copy-Item ".\.env" "$backup\.env" -ErrorAction Stop
Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop

$sourceDb = (Resolve-Path ".\local-data\betteroption.db").Path
$backupRoot = (Resolve-Path $backup).Path
$backupDb = Join-Path $backupRoot "local-data\betteroption.db"
$dump = Join-Path $backupRoot "betteroption-$stamp.sql"

# Native SQLite snapshot and portable SQL dump, when sqlite3.exe is installed:
$backupDbForSqlite = $backupDb.Replace('\', '/')
& sqlite3.exe $sourceDb ".backup '$backupDbForSqlite'"
& sqlite3.exe $backupDb ".dump" | Set-Content -Encoding utf8 $dump

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

`git ls-files` muss leer bleiben. Das Backup enthält Schlüssel und persönliche
Bewerbungsdaten und gehört weder nach GitHub noch in das Release-ZIP.

Falls `sqlite3.exe` fehlt, erzeugt Python beides konsistent:

```powershell
@'
import sqlite3
import sys
from pathlib import Path

source, snapshot, dump = map(lambda value: Path(value).resolve(), sys.argv[1:4])
snapshot.parent.mkdir(parents=True, exist_ok=True)
snapshot.unlink(missing_ok=True)
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as live:
    with sqlite3.connect(snapshot) as target:
        live.backup(target)
with sqlite3.connect(snapshot) as target:
    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("SQLite integrity check failed")
    dump.write_text("\n".join(target.iterdump()) + "\n", encoding="utf-8")
print(snapshot)
print(dump)
'@ | .\.venv\Scripts\python.exe - $sourceDb $backupDb $dump
```

## 2. Provider-Konfiguration prüfen

Die Schlüssel bleiben ausschließlich in `.env`. Leere numerische Werte sind
ungültig; ein unbekannter Preis wird explizit mit `0` markiert:

```dotenv
OPENWEBNINJA_JSEARCH_API_KEY=<CURRENT_PROJECT_KEY>
BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS=3
BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD=0

APIFY_API_TOKEN=<CURRENT_APIFY_TOKEN>
BETTEROPTION_APIFY_EURES_MAX_RESULTS=30
BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD=0
```

Unter **Account → Provider choices** lassen sich beide Anbieter unabhängig an-
oder abschalten. Schlüssel nie in Screenshots, Logs, Git oder Chat einfügen.

## 3. S installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1s_source_facts.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1s-source-facts"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Optional: verify the current JSearch key and plan with exactly one live request:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

The `--live` flag is required because this request can consume plan quota. The
probe uses one fixed synthetic term, disables retries and search fan-out, and
does not use Compass or job data. It prints only `category` and `result_count`;
the key, fixed query, request URL and response body are neither printed nor
stored. Safe categories are `success`, `not_configured`, `authentication`,
`plan`, `rate_limit`, `network`, and `provider`.

Erwartet werden `0.7.1s-source-facts` und weiterhin der Datenbank-Head
`0030_verified_job_posters`.

## 4. Tests und lokaler Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

## 5. Lokale Abnahme

1. Eine EURES-Suche durchführen und Ergebnisse aus mehreren Ländern prüfen.
   Statt `DE724`, `DE600` oder `SE232` muss eine lesbare Region erscheinen;
   bei auflösbaren Regionen darf die Distanz nicht mehr `Unknown` sein.
2. JSearch allein aktivieren und eine kleine Suche ausführen. Die
   Source-Diagnose muss `Reached` statt `Failed` zeigen und echte Einheiten in
   Operations erfassen.
3. Prüfen, dass die Source-Diagnose **Exa** statt **Exa fallback** nennt.
4. Job Details öffnen: Job-Fakten müssen vor den Employer-Fakten gebündelt
   sein; Employer-Typen bleiben kompakt und scrollbar.
5. Die veröffentlichte Bewerbungsadresse darf nur einmal und ohne
   `PostalAddress`-Schemawörter erscheinen.
6. Add öffnen: **Paste manual job text** steht links/vor der finalen Aktion
   **Verify and save job**.
7. Home mit Remote + Fresh + Worth-a-look Karten prüfen. Der Fit-Badge bleibt
   einzeilig und unverformt.

## 6. Nach GitHub pushen

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
  -CommitMessage "Release BetterOption v0.7.1s-source-facts"

git tag -a v0.7.1s-source-facts `
  -m "BetterOption v0.7.1s source facts"
git push origin v0.7.1s-source-facts

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor `y` kontrollieren, dass `.env`, Datenbanken, `local-data`, Backups, CVs,
Uploads und Schlüssel nicht gestaged sind.

## 7. Wiederherstellung testen

```powershell
$dump = ".\local-backups\before-v071s-YYYYMMDD-HHMMSS\betteroption-YYYYMMDD-HHMMSS.sql"
$restore = ".\local-backups\restored-v071s-check.db"
Remove-Item $restore -Force -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(sys.argv[2]); db.executescript(open(sys.argv[1], encoding='utf-8-sig').read()); print(db.execute('PRAGMA integrity_check').fetchone()[0])" `
  $dump $restore
```

Erst nach `ok` eine Wiederherstellung erwägen. Ein Server-/Alpha-Rollout ist
nicht Teil von S.
