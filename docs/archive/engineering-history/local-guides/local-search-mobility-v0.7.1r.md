> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1r lokal sichern, installieren, testen und pushen

Dieser Ablauf ist ausschließlich für `http://127.0.0.1:8000`. R wird in dieser
Iteration **nicht** auf einen Server ausgerollt.

## 1. App stoppen und lokale Daten sichern

Im Fenster mit `run_web.ps1` zuerst `Ctrl+C` drücken und den vollständigen
Uvicorn-Shutdown abwarten. Danach in PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071r-$stamp"
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
    dump.write_text("\n".join(backup.iterdump()) + "\n", encoding="utf-8")
print(snapshot)
print(dump)
'@ | .\.venv\Scripts\python.exe - $sourceDb $backupDb $dump
```

## 2. Provider optional konfigurieren

In `.env` gehören ausschließlich aktuelle persönliche Testschlüssel. Leere
numerische Kostenwerte sind ungültig; unbekannte Preise werden explizit `0`:

```dotenv
OPENWEBNINJA_JSEARCH_API_KEY=<YOUR_CURRENT_JSEARCH_KEY>
BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS=3
BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD=0

APIFY_API_TOKEN=<YOUR_CURRENT_APIFY_TOKEN>
BETTEROPTION_APIFY_EURES_MAX_RESULTS=30
BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD=0
```

Nur konfigurierte Provider erscheinen als verfügbar. Unter **Account → Provider
choices** kann der Account jeden verfügbaren Anbieter abschalten. Schlüssel nie
in Screenshots, Logs, Git oder Chat einfügen.

## 3. R installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1r_search_mobility.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1r-search-mobility"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartet: `0.7.1r-search-mobility`. Der Datenbank-Head bleibt
`0030_verified_job_posters`.

## 4. Testen und starten

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

## 5. Lokale Abnahme

1. Mit einer Persona `midwife`/`midwifery` und München suchen. Engineering,
   Finance und andere nahe, aber fachfremde Rollen dürfen nicht mehr durch die
   Standortwertung hochgezogen werden.
2. Unter Account JSearch bzw. EURES einzeln an- und abschalten und dieselbe
   Suche vergleichen. Operations muss echte Request-/Result-Einheiten zeigen;
   `0`-Preise erscheinen als unbepreist, nicht kostenlos.
3. Compass → Location and mobility öffnen. Einen nahen öffentlichen Ort
   normalisieren und Car/Transit/Bicycle einzeln setzen, speichern und die Seite
   neu laden. Nicht benutzte Modi bleiben neutral.
4. Prüfen, dass vorhandene Guided-Setup-Fakten sowohl Mobility als auch Salary
   in den Widgets wieder erscheinen.
5. Nach einem vollständigen Match den Compass ändern und ohne erneuten Full
   Match einen Cover Letter erzeugen. Der Draft muss die neuesten bestätigten
   Compass-Fakten verwenden; blockierte oder geschlossene Jobs bleiben gesperrt.
6. Cover Letter **Shorter** soll ungefähr 30 Wörter entfernen.
7. Personas wechseln und die Suche erneut öffnen. Ergebnisse dürfen neu
   bewertet werden; keine Kriterien oder Rangwerte der anderen Persona dürfen
   übernommen werden.

## 6. Nach lokaler Abnahme nach GitHub pushen

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
  -CommitMessage "Release BetterOption v0.7.1r-search-mobility"

git tag -a v0.7.1r-search-mobility `
  -m "BetterOption v0.7.1r search and mobility"
git push origin v0.7.1r-search-mobility

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor der Bestätigung prüfen, dass `.env`, Datenbanken, `local-data`,
`local-backups`, CVs, Uploads und Schlüssel nicht gestaged sind.

## 7. Wiederherstellung

Die App stoppen. Für einen separaten Restore-Test:

```powershell
$dump = ".\local-backups\before-v071r-YYYYMMDD-HHMMSS\betteroption-YYYYMMDD-HHMMSS.sql"
$restore = ".\local-backups\restored-v071r-check.db"
Remove-Item $restore -Force -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(sys.argv[2]); db.executescript(open(sys.argv[1], encoding='utf-8-sig').read()); print(db.execute('PRAGMA integrity_check').fetchone()[0])" `
  $dump $restore
```

Erst nach `ok` entscheiden, ob die aktive lokale Datenbank ersetzt werden soll.
Ein Server- oder Alpha-Rollout gehört nicht zu R.
