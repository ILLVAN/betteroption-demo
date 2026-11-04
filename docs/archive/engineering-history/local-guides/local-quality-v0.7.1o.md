> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1o lokal sichern, installieren, testen und pushen

Dieser Ablauf unterstützt ausschließlich `http://127.0.0.1:8000`. In dieser
Iteration keinen Server, Tunnel, `0.0.0.0`-Listener oder externen Alpha-Zugang
aktivieren.

## 1. App stoppen, `.env`, SQLite-Snapshot und SQL-Dump sichern

Die App zuerst im `run_web.ps1`-Fenster mit `Ctrl+C` beenden. Erst wenn Uvicorn
vollständig beendet ist, in einem neuen PowerShell-Fenster ausführen:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071o-$stamp"
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

Erst fortfahren, wenn Snapshot, `PRAGMA integrity_check`, SQL-Dump und der
Dump-Import bestätigt wurden. `git ls-files` muss leer bleiben. Das Backup
enthält Schlüssel und private Persona-/Bewerbungsdaten und bleibt lokal.

## 2. Optionalen You.com-Search-Provider konfigurieren

O funktioniert weiterhin mit den vorhandenen Quellen. You.com Search ist ein
optionaler zusätzlicher REST-Provider, kein Installationszwang. Falls er genutzt
werden soll, `.env` öffnen und numerische Werte ausdrücklich setzen:

```dotenv
YDC_API_KEY=<CURRENT_YOU_SEARCH_KEY>
BETTEROPTION_YOU_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
```

`0` bedeutet **unbepreist/unknown**, niemals kostenlos. Sobald der wirksame
Tarif bekannt ist, `0` durch den aktuellen numerischen Preis pro Search-Aufruf
ersetzen. Das Feld nicht leer lassen. Nach dem Start unter **Account → Provider
controls** prüfen, ob You.com technisch verfügbar und für diesen Account
erlaubt ist. Das Abschalten verhindert Aufrufe und neue Kosten.

Für localhost darf die bestehende lokale Provider-Grenze genutzt werden. Vor
Hosting oder Alpha-Testern bleiben DPA/Processor-Rolle, Subprozessoren,
Verarbeitungsorte, Transfermechanismus, Retention/Löschung und Incident-Kontakt
für You.com wie für alle anderen aktivierten Anbieter echte Launch-Gates.

## 3. Exaktes O-ZIP installieren

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1o_local_quality.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1o-local-quality"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Erwartete Version: `0.7.1o-local-quality`. Der Installer bewahrt `.env` und
`local-data`. Beim ersten lokalen Start wird die Datenbank bis
`0029_job_detail_preferences` migriert. Deshalb vor der Installation sichern
und einen älteren Programmstand nicht gegen die migrierte Datenbank starten;
für einen Rückweg das Vor-O-Backup wiederherstellen.

Leere numerische Providerpreise bleiben ungültig. Für jeden unbekannten Preis
explizit `0` verwenden; das Kosten-Ledger zeigt diesen Betrieb als verwendet,
aber unbepreist—nicht als kostenlos.

## 4. Test-Gate, lokaler Start und Health-Check

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

In einem zweiten PowerShell-Fenster prüfen:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`/health/ready` muss `READY` und Version `0.7.1o-local-quality` melden. Nur über
`http://127.0.0.1:8000` testen.

## 5. Manuelle O-Abnahme

1. Home öffnen: Die Smart-Action darf keinen Text wie
   `<built-in method copy ...>` enthalten. Home, Compass, Add, Explore, Match,
   Apply und Archive müssen jeweils eine durchgehende pink-teal Hauptaktion
   ohne weißen Mittelstreifen zeigen.
2. Match mit leerem Compass und separat ohne Jobs prüfen: **Create my matches**
   bleibt jeweils deaktiviert und erklärt knapp den fehlenden Schritt.
3. Explore starten. Der Background-Text darf auf mehrere Minuten sorgfältige
   Prüfung hinweisen, aber keine harte Vier-Minuten-Gesamtdauer versprechen.
   Das konfigurierte Budget gilt für die Source-Mesh-Stufe; Queue, Retry,
   Persistenz und bereits laufende Requests können darüber hinausgehen.
   Phishing/suspended-domain, 404/error,
   Search-/Kategorie-, Blog-/Listicle- und andere nicht verifizierte
   Nicht-Vacancy-Seiten dürfen nicht auswählbar sein. Weniger Treffer sind bei
   nicht bestandener Verifikation korrekt.
4. Optional je einen Lauf mit und ohne You.com-Erlaubnis ausführen. Operations
   muss die tatsächlich aufgerufenen Provider und unbepreiste Nutzung korrekt
   zeigen; ein deaktivierter Provider darf nicht aufgerufen werden.
5. Apply prüfen: Permission/Allowance und Create-Button bilden zusammen die
   farbige Hauptaktion; ohne ausdrückliche Auswahl/Erlaubnis darf kein
   Cover-Letter-Provider aufgerufen werden.
6. Die Einstellung **Also update my Compass from skill changes** entfernen,
   neu laden und wieder setzen. Beide Zustände müssen pro Persona erhalten
   bleiben. Einen Skill aus dem Compass löschen; der Job-Detail-Marker muss den
   aktuellen Compass statt eines alten Matching-Snapshots zeigen.
7. Evidence korrigieren und den Job einzeln neu matchen. Die Aufgabe muss im
   Hintergrund laufen, zur Job-Detail-Seite zurückkehren und Good/Check/Blocker
   bzw. unresolved anhand des neuen effektiven Ergebnisses anzeigen. Match muss
   anschließend auf gemischte Refresh-Zeitpunkte hinweisen.
8. Einen Remote-only-Job matchen: keine Adress-Routing-Wartekette, aber eine
   kompakte graue, nachvollziehbare Mobility-Zeile und Teil-Credit, solange
   Remote nicht ausgeschlossen ist. Eine explizite Remote-Ausschlussregel muss
   weiterhin blockieren.
9. Einen Job mit veröffentlichter Bewerbungsadresse/-anweisung prüfen. Prepare
   Package zeigt nur belegte oder privat korrigierte Angaben. Kontakt, E-Mail,
   Telefon, Postadresse und Bewerbungs-URL dürfen nicht im OpenAI-Job-Payload
   landen; BetterOption darf niemanden kontaktieren oder automatisch bewerben.
10. Persona-/Account-Isolation, Add/manual input, Job-/Employer-Ratings,
    Archive, Export, Cover-Letter-Bearbeitung und bestehende Jobs
    regressionsweise prüfen.

Bei einem Fehler nicht pushen oder taggen.

## 6. Git ohne Pager prüfen und geschützt pushen

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
  -CommitMessage "Release BetterOption v0.7.1o-local-quality"

git tag -a v0.7.1o-local-quality `
  -m "BetterOption v0.7.1o local quality"
git push origin v0.7.1o-local-quality

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Vor `y` prüfen, dass `.env`, `local-data`, `local-backups`, Datenbanken,
CV/Resume-Dateien, Uploads und Keys nicht gestaged sind. Ein privates GitHub
Repository ist der normale, ausreichende Code-Stand; das lokale private
Daten-Backup gehört nicht ins Repository.

## 7. Wiederherstellung

App stoppen. Das verifizierte Vor-O-Snapshot in einen separaten Arbeitsstand
kopieren; die aktive Datenbank nicht blind bei laufender App überschreiben:

```powershell
$preO = (Resolve-Path ".\local-backups\before-v071o-YYYYMMDD-HHMMSS").Path
Copy-Item "$preO\.env" ".\.env" -Force -ErrorAction SilentlyContinue
Copy-Item "$preO\local-data\*" ".\local-data" -Recurse -Force
```

Falls nur der portable Dump vorhanden ist, eine neue Datenbank daraus erzeugen
und erneut prüfen:

```powershell
$dump = "$preO\betteroption-YYYYMMDD-HHMMSS.sql"
$restored = ".\local-data\betteroption-restored.db"
.\.venv\Scripts\python.exe -c `
  "import pathlib,sqlite3,sys; target=pathlib.Path(sys.argv[2]); target.unlink(missing_ok=True); db=sqlite3.connect(target); db.executescript(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); print(db.execute('PRAGMA integrity_check').fetchone()[0]); db.close()" `
  $dump $restored
```

Nur nach Ausgabe `ok` und bei gestoppter App die aktive Datenbank gezielt
ersetzen. Backup und Dump bis zur erfolgreichen Abnahme behalten.

Ein Server-Rollout ist bewusst nicht Teil von O. SearXNG/MCPHub, allgemeine
Search-MCPs, nicht lizenzierte LinkedIn/Indeed/Stepstone/Glassdoor-Extraktion
und ein Employer-Posting-Portal bleiben getrennte Architektur-, Vertrags- und
Privacy-Entscheidungen für spätere Iterationen.
