> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1m lokal sichern, installieren, testen und nach GitHub pushen

Dieser Leitfaden aktualisiert die bestehende Windows-Installation auf
`v0.7.1m-local-readiness`. Unterstützt wird in dieser Iteration ausschließlich
`http://127.0.0.1:8000`. Kein Server, kein Tunnel, kein `0.0.0.0`, kein
Cloudflare-Rollout und kein externer Alpha-Test.

## 1. Anwendung beenden und vollständiges Backup anlegen

Die laufende App zuerst im Fenster von `run_web.ps1` mit `Ctrl+C` beenden. Das
Datenbank-Snapshot wird anschließend über die konsistente
`sqlite3.Connection.backup()`-API erstellt; der zusätzliche SQL-Dump bleibt die
portable Wiederherstellungsquelle. In einem neuen PowerShell-Fenster ausführen:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071m-$stamp"

New-Item -ItemType Directory -Force "$backup\local-data" | Out-Null

# .env und alle Nicht-Datenbank-Dateien aus local-data privat sichern
Copy-Item ".\.env" "$backup\.env" -ErrorAction SilentlyContinue
Copy-Item ".\local-data\*" "$backup\local-data" -Recurse -Force -ErrorAction Stop

# Die kopierte DB/WAL-Dateien werden durch ein konsistentes SQLite-Snapshot ersetzt
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

source = Path(sys.argv[1]).resolve()
snapshot = Path(sys.argv[2]).resolve()
dump = Path(sys.argv[3]).resolve()

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

Get-ChildItem $backup -Force -Recurse
Get-FileHash $backupDb -Algorithm SHA256
Get-FileHash $dump -Algorithm SHA256

# Den SQL-Dump unabhängig in eine leere In-Memory-Datenbank einlesen
.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(':memory:'); db.executescript(open(sys.argv[1], encoding='utf-8').read()); print('SQL dump verified successfully')" `
  $dump

git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Erst fortfahren, wenn folgende Ausgaben vorhanden sind:

- `SQLite snapshot verified`
- `Portable SQL dump created`
- `SQL dump verified successfully`
- SHA-256-Werte für Snapshot und Dump
- keine Ausgabe beim letzten `git ls-files`-Befehl

Das Backup-Verzeichnis enthält `.env`, lokale Uploads/CV-Daten, das konsistente
SQLite-Snapshot und den portablen SQL-Dump. Es bleibt privat und darf weder in
Git noch in das Release-ZIP gelangen.

## 2. Exaktes M-ZIP installieren

Das heruntergeladene ZIP in `Downloads` ablegen und den exakten Pfad verwenden:

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1m_local_readiness.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1m-local-readiness"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Die letzte Ausgabe muss `0.7.1m-local-readiness` sein. Der Overlay-Installer
behält `.env`, Datenbank und `local-data` und installiert das Paket erneut im
Editable-Modus. Er führt absichtlich noch keine Tests aus.

M benötigt keinen neuen API-Key und keine neue Alembic-Migration. Der lineare
Head bleibt `0028_job_ratings`. Vorhandene `.env` nicht durch ein Beispiel
ersetzen. Konfiguration ohne Provider-Aufruf prüfen:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Numerische Providerpreise dürfen nicht leer sein. `0` ist nur der explizite
Status **verwendet, aber noch unbepreist**, niemals kostenlos.

## 3. Vollständigen Test-Gate ausführen

```powershell
cd C:\projects\betteroption

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Der Gate prüft Formatierung, Lint, alle Tests und Python-Kompilierung. Die Tests
verwenden Fakes und sollen kein Providerbudget verbrauchen. Bei einem Fehler
nicht pushen und nicht taggen.

## 4. Nur lokal starten

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Zuerst `http://127.0.0.1:8000/health/ready` öffnen. Erwartet werden `READY`, die
beabsichtigte lokale Datenbank und Version `0.7.1m-local-readiness`. Danach
`http://127.0.0.1:8000` öffnen.

`BETTEROPTION_WEB_HOST=127.0.0.1` beibehalten. Diese Iteration enthält keinen
Server-Rollout.

## 5. Manuelle Abnahme

Für die Abnahme eine bestehende Persona und eine Test-Persona verwenden. Keine
echte Bewerbung absenden.

1. **Manual Match:** Unter Add einen Job als manuellen Text mit optionaler
   Quell-URL speichern und Match ausführen. Der Lauf muss ohne
   `match URL verification metadata must be complete` fertig werden. Job Detail
   muss **Manual** anzeigen; Refresh darf die URL nicht abrufen oder eine
   Verifikation erfinden.
2. **Explore:** Eine realistische Suche mit Exa und Brave ausführen. Der Lauf
   soll innerhalb des begrenzten Providerbudgets bleiben, bestehende
   Qualitäts-/Linkchecks und Ranking anzeigen und keine generischen Suchseiten
   als echte Jobs übernehmen. Bei derselben kanonischen URL soll die
   Exa-Variante einen reinen Gleichstand gewinnen. Es ist korrekt, wenn weniger
   als 150 brauchbare Resultate existieren.
3. **Fresh/Old:** Einen Job mit bekanntem Datum unter einem Monat und einen über
   vier Monate alten Job prüfen. Karten müssen **Fresh** beziehungsweise
   **Old** zeigen; `Old posting` darf nicht mehr erscheinen. Unbekannte und
   mittlere Daten erhalten kein falsches Badge.
4. **Manual Match und Kalibrierung:** Einen klar positiven und einen Job mit
   echter Must-have-/Exclusion-Verletzung neu matchen. Die veröffentlichte
   Positive-Fit-Kalibrierung darf höchstens `+3` liefern und nie einen Blocker
   aufheben. Fehlende Evidenz allein darf keinen erfundenen Blocker erzeugen.
5. **Kontakt und Prozess:** Einen Job mit veröffentlichter Bewerbungsadresse,
   Kontakt oder Prozessregel importieren. Job Detail soll alle belegten Werte,
   insbesondere eine vorhandene Postadresse, mit Quelle zeigen. Unbekanntes
   bleibt unbekannt. Einen Cover Letter erzeugen und prüfen, dass kein Name,
   identifizierender Titel, keine E-Mail, Telefonnummer, Postadresse oder
   Bewerbungs-URL vom Modell in den Text übernommen wurde. Die geprüfte Anrede
   wird lokal ausgewählt oder ergänzt.
6. **Employer Identity:** Bei einem Job mit `Unknown`/Platzhalter müssen
   Employer-Rating und geteilter Kontext deaktiviert bleiben. Den Firmennamen
   auf einen konkreten Arbeitgeber korrigieren, speichern und rematchen. Rating
   und private Employer-Notiz sollen anschließend bei einem zweiten Job
   derselben normalisierten Firma innerhalb derselben Persona erscheinen, aber
   nicht bei einer anderen Firma oder Persona.
7. **Private Felder:** Company-Product-Edits und **Private employer context**
   müssen kompakte einzeilige Eingaben sein. Die private Notiz muss als
   User-Kontext erkennbar bleiben und darf nicht als Providerfinding oder
   automatische Compass-Tatsache erscheinen.
8. **Ratings:** Auf jeder passenden Jobkarte muss **Your Ratings** mit **Job**
   links und **Employer** rechts erscheinen. Unrated bleibt neutral; ein
   Employer-Rating ist nur bei aufgelöster Firmenidentität verfügbar. Änderung
   auf einer Karte speichern, rematchen und Persistenz sowie Persona-Isolation
   prüfen.
9. **Layout:** Job Detail muss wieder eine breite Evidenzspalte und eine schmale
   Aktionsspalte verwenden. Innerhalb der Evidenzkarten dürfen keine
   tabellenartigen Mikrospalten mit extremen Wortumbrüchen entstehen. Die
   Application-State-Grafik darf **See evidence** und das Statusfeld nicht
   überlagern.
10. **Regression:** Home, Compass, Add, Explore, Match, Job Detail, Apply,
    Archive/Jobs, Personas, Account, Export, Providerauswahl und Kostenanzeige
    durchgehen. K-Daten müssen erhalten bleiben; Account- und Persona-Grenzen
    dürfen nicht leaken.
11. **Legal boundary:** Privacy, AI Notice, Terms, Storage und Imprint öffnen.
    Die beschriebenen Provider- und Kontaktdatenflüsse müssen der tatsächlichen
    Konfiguration entsprechen. Readiness-Warnungen nicht als juristische
    Freigabe behandeln und keinen externen Zugang aktivieren.

## 6. Änderungen ohne Git-Pager prüfen

App wieder mit `Ctrl+C` beenden. Unter Windows immer `--no-pager` verwenden;
falls versehentlich `(END)` erscheint, beendet `q` den Pager.

```powershell
cd C:\projects\betteroption

git status --short
git --no-pager diff --stat
git --no-pager diff --check
git --no-pager diff -- pyproject.toml src scripts docs tests .env.example README.md
git --no-pager log -1 --oneline
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Jeden unerwarteten Pfad prüfen. Der letzte Befehl muss ohne Ausgabe enden.
LF/CRLF-Hinweise sind Checkout-Warnungen, keine Testfehler.

## 7. Guarded GitHub Push und annotierter Tag

Der Helper staged nur Produktpfade, lehnt bekannte Runtime-/Privatdateien ab,
zeigt die vorbereiteten Dateien und fragt vor Commit und Push nach:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1m-local-readiness"
```

Nur mit `y` bestätigen, wenn `.env`, `local-data`, `local-backups`, Datenbanken,
CV/Resume-Dateien, Uploads und Provider-Keys nicht in der Liste stehen. Danach
denselben Commit annotiert taggen:

```powershell
git --no-pager log -1 --oneline
git status --short

git tag -a v0.7.1m-local-readiness `
  -m "BetterOption v0.7.1m local readiness"
git push origin v0.7.1m-local-readiness

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Erwartet: sauberer Worktree; `origin/main` und
`v0.7.1m-local-readiness` zeigen auf denselben akzeptierten M-Commit.

## 8. Recoverable Rollback auf K

M fügt keine Migration hinzu, kann aber neuere JSON-/Domänenfelder schreiben.
Nicht die einzige Arbeitskopie blind downgraden. Den verifizierten Snapshot in
einem separaten K-Worktree verwenden:

```powershell
cd C:\projects\betteroption
$preM = (Resolve-Path ".\local-backups\before-v071m-YYYYMMDD-HHMMSS").Path

git worktree add ..\WorkLifeBalanceAI-v071k v0.7.1k-local-evidence
cd ..\WorkLifeBalanceAI-v071k

Copy-Item "$preM\.env" ".\.env" -Force -ErrorAction SilentlyContinue
Copy-Item "$preM\local-data" ".\local-data" -Recurse -Force

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Den Timestamp ersetzen. Erst starten, wenn die letzte Ausgabe
`0.7.1k-local-evidence` ist. Das ursprüngliche M-Verzeichnis und den SQL-Dump
bis zur Diagnose nicht überschreiben.
