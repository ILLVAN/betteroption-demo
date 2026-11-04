> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1n lokal sichern, installieren, testen und pushen

Dieser Ablauf unterstützt ausschließlich `http://127.0.0.1:8000`. In dieser
Iteration keinen Server, Tunnel, `0.0.0.0`-Listener oder externen Alpha-Zugang
aktivieren.

## 1. App stoppen und SQLite-Dump sichern

Die App zuerst im `run_web.ps1`-Fenster mit `Ctrl+C` beenden. Danach in einem
neuen PowerShell-Fenster ausführen:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071n-$stamp"
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

Erst fortfahren, wenn Snapshot, Dump und Dump-Import bestätigt wurden und
`git ls-files` nichts ausgibt. Das Backup enthält private Daten und bleibt lokal.

## 2. Exaktes N-ZIP installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1n_local_experience.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1n-local-experience"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartete Version: `0.7.1n-local-experience`. Der Installer bewahrt `.env` und
`local-data`. N benötigt keine neue Datenbankmigration; der Head bleibt
`0028_job_ratings`. Leere numerische Providerpreise bleiben ungültig; `0`
bedeutet unbepreist, nicht kostenlos.

## 3. Test-Gate und lokaler Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

`http://127.0.0.1:8000/health/ready` muss `READY` und Version
`0.7.1n-local-experience` melden. Danach ausschließlich über
`http://127.0.0.1:8000` testen.

## 4. Kurze manuelle Abnahme

1. Einen Remote-only-Job matchen: Routing muss sofort als nicht anwendbar
   enden, ohne Provider-Wartekette. Einen Hybrid-Job mit Adresse gegenprüfen.
2. Explore mit einer breiten Compass-Richtung und Ausschlüssen starten. Parked,
   suspended, 404- und erkennbare Error-Landing-Seiten dürfen nicht auswählbar
   werden; weniger als 150 gute Treffer ist zulässig.
3. Add einmal per URL und einmal über den manuellen Fallback ausführen. Ein
   Extraktionsfehler soll um Text bitten, nicht ungefragt einen defekten Job
   archivieren.
4. Home, Guided Setup und jede Hauptseite prüfen: klare Hauptaktion, erhaltene
   Scrollposition nach Inline-Saves, keine Warn-/Erklärungstextwand.
5. Jobkarten auf saubere Adresse/Remote-Anzeige, `Fresh`/`Old`, State-Wasserzeichen
   und symmetrische Job-/Employer-Ratings prüfen.
6. Job Detail: vorheriger/nächster Match, getrennte Salary-Felder, Work Model,
   Confidence, private Values und einklappbare Provenienz prüfen.
7. Einen veröffentlichten Bewerbungskontakt/-prozess importieren. Prepare
   Package darf nur belegte Angaben zeigen. Cover-Letter-Erzeugung darf Kontakt,
   E-Mail, Telefon, Postadresse und Bewerbungs-URL nicht an OpenAI senden.
8. Account-/Persona-Isolation, Providerwahl, Kostenanzeige, Apply, Archive,
   Export und bestehende M-Daten regressionsweise prüfen.

Bei einem Fehler nicht pushen oder taggen.

## 5. Git ohne Pager prüfen und geschützt pushen

App wieder mit `Ctrl+C` stoppen:

```powershell
cd C:\projects\betteroption
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git --no-pager log -1 --oneline
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Der letzte Befehl muss leer bleiben. Danach:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1n-local-experience"

git tag -a v0.7.1n-local-experience `
  -m "BetterOption v0.7.1n local experience"
git push origin v0.7.1n-local-experience

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor `y` prüfen, dass `.env`, `local-data`, `local-backups`, Datenbanken,
CV/Resume-Dateien, Uploads und Keys nicht gestaged sind.

## 6. Wiederherstellung

App stoppen. Für einen vollständigen Rückweg zuerst das gesicherte Snapshot in
einen separaten Arbeitsstand kopieren; das N-Verzeichnis nicht blind
überschreiben:

```powershell
$preN = (Resolve-Path ".\local-backups\before-v071n-YYYYMMDD-HHMMSS").Path
Copy-Item "$preN\.env" ".\.env" -Force -ErrorAction SilentlyContinue
Copy-Item "$preN\local-data\*" ".\local-data" -Recurse -Force
```

Falls nur der portable Dump vorhanden ist, eine neue Datenbank daraus erzeugen:

```powershell
$dump = "$preN\betteroption-YYYYMMDD-HHMMSS.sql"
$restored = ".\local-data\betteroption-restored.db"
.\.venv\Scripts\python.exe -c `
  "import pathlib,sqlite3,sys; target=pathlib.Path(sys.argv[2]); target.unlink(missing_ok=True); db=sqlite3.connect(target); db.executescript(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); print(db.execute('PRAGMA integrity_check').fetchone()[0]); db.close()" `
  $dump $restored
```

Nur nach Ausgabe `ok` und bei gestoppter App die aktive Datenbank gezielt
ersetzen. Backup und Dump bis zur erfolgreichen Abnahme behalten.

Ein Server-Rollout ist bewusst ein späterer, separater Arbeitsgang mit erneuter
Legal-, Provider-, Security-, Backup- und Restore-Abnahme. Zusätzliche
Discovery-Quellen oder ein Employer-Posting-Portal sind ebenfalls zukünftige
Roadmaparbeit und nicht Bestandteil von N.
