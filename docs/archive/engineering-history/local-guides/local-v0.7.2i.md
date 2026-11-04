> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2i lokal installieren, testen und veröffentlichen

`v0.7.2i` wird als Overlay über das gepushte `v0.7.2h`-Repository installiert.
Die lokale Datenbank bleibt ausschließlich lokal. Für den neuen Netcup-Server
wird später eine leere PostgreSQL-Datenbank nach dem separaten
[Private-Alpha-Runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2i.md) angelegt.

## 1. Lokale Runtime sichern und App sauber stoppen

Im Repository zuerst die App mit `Ctrl+C` vollständig beenden und auf den
Uvicorn-Shutdown warten. Danach `.env` und `local-data` privat sichern. Diese
Dateien gehören nie in Git oder das Release-ZIP.

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path (Get-Location) "local-backups\before-v0.7.2i-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path .env) { Copy-Item .env (Join-Path $backup ".env") }
if (Test-Path local-data) {
  Copy-Item local-data (Join-Path $backup "local-data") -Recurse
}
```

## 2. Release-ZIP installieren

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2i.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2i"
```

Der Installer erhält `.env`, `.venv`, `local-data`, Uploads und lokale Backups.
Danach die getrennten App- und Paketkennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartet:

```text
0.7.2i
0.7.2+i
```

Die additiven Migrationen sind `0032_explore_import_origin` und
`0033_background_task_leases`. Der aktuelle Matchingvertrag ist
`matching-v0.7.2i`; nach dem Upgrade einmal ein vollständiges Match ausführen,
bevor Quickscore in einen alten `h`-Lauf projizieren soll.

## 3. Bestehende `.env` kontrolliert ergänzen

Der Installer überschreibt `.env` absichtlich nicht. Der folgende Block setzt
neue Werte und ersetzt nur bekannte `h`-Defaults. Eigene bereits kalibrierte
Werte bleiben erhalten.

```powershell
$envPath = Join-Path (Get-Location) ".env"
$lines = [System.Collections.Generic.List[string]]::new()
if (Test-Path $envPath) {
  Get-Content $envPath | ForEach-Object { [void]$lines.Add($_) }
}

function Upgrade-WlbEnvValue(
  [string]$Key,
  [string]$Value,
  [string[]]$KnownOldValues = @()
) {
  $prefix = "$Key="
  for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index].StartsWith($prefix)) {
      $current = $lines[$index].Substring($prefix.Length).Trim()
      if ($KnownOldValues -contains $current) {
        $lines[$index] = "$prefix$Value"
      }
      return
    }
  }
  [void]$lines.Add("$prefix$Value")
}

Upgrade-WlbEnvValue "BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM" "20" @("60")
Upgrade-WlbEnvValue "BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS" "120" @("300")
Upgrade-WlbEnvValue "BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD" "0.40" @("", "0", "0.0", "0.00")
Upgrade-WlbEnvValue "BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD" "0.40" @("0", "0.0", "0.00", "0.06", "0.060", "0.0600")
Upgrade-WlbEnvValue "BETTEROPTION_BACKGROUND_WORKER_ENABLED" "true"
Upgrade-WlbEnvValue "BETTEROPTION_BACKGROUND_WORKER_EXTERNAL" "false"
Upgrade-WlbEnvValue "BETTEROPTION_BACKGROUND_TASK_LEASE_TTL_SECONDS" "30"
Upgrade-WlbEnvValue "BETTEROPTION_BACKGROUND_TASK_HEARTBEAT_SECONDS" "5"

[System.IO.File]::WriteAllLines(
  $envPath,
  $lines,
  [System.Text.UTF8Encoding]::new($false)
)
```

Lokal bedeutet `ENABLED=true` und `EXTERNAL=false`: genau ein Worker läuft im
App-Prozess. Den Browser zu schließen unterbricht ihn nicht; den Python-Prozess
zu beenden pausiert ihn. Nach einem Neustart wird nur eine abgelaufene Lease
wieder aufgenommen. Auf dem Server gilt umgekehrt `ENABLED=false` und
`EXTERNAL=true`, weil dort der eigene Compose-Worker läuft.

`MAX_ITEMS` ist kein garantierter Kostenstopp für den pay-per-event Actor. Der
harte Laufdeckel ist `MAX_TOTAL_CHARGE_USD=0.40`. Andere Explore-Anbieter bleiben
unverändert.

## 4. Konfiguration, Migration und vollständigen Test ausführen

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

`diagnose_jsearch.py` macht ohne `--live` keinen Provideraufruf. Für die
Release-Abnahme ist kein Live-Provider-Probe erforderlich.

## 5. Manuelle lokale Abnahme

1. Zwei Explore-Treffer mit demselben Pfad, aber unterschiedlichen
   `vacancyId`-Werten prüfen. Beide Karten und ihre jeweils eigenen
   `Posted`-Zeiten müssen erhalten bleiben. Bei schmalem Browserfenster darf das
   Datum nie optisch zur nächsten Karte rutschen.
2. Englische, deutsche, französische, niederländische, spanische und
   italienische gelabelte Posted-Werte stichprobenartig prüfen. Ein reines
   `updated_at` oder `page_age` darf nicht als neues Postingdatum erscheinen.
3. Einen durch `robots.txt` nicht automatisch lesbaren Treffer speichern.
   `Needs pasted text` muss Add mit exakter URL öffnen, das manuelle Textfeld
   anzeigen und `Inspect source` anbieten. Eine URL mit Credentials oder einem
   Nicht-HTTP(S)-Schema darf nicht vorgefüllt werden.
4. Zwei Explore-Tabs derselben Persona verwenden. Ein Importfehler aus dem
   älteren Tab darf nur dessen ursprünglichen Snapshot markieren, nicht den
   zuletzt fertiggestellten Lauf.
5. Vor dem ersten Match beide Ratings ändern. Die Sterne müssen gespeichert
   bleiben und die Oberfläche muss ehrlich erklären, dass erst Matching einen
   Compatibility-Wert erzeugt. Nach einem vollständigen Match müssen einzelne
   Ratingänderungen Score, Gruppe und Reihenfolge ohne Provideraufruf ändern.
6. Beide Ratings auf null und wieder zurück setzen. Der Score darf lokal fallen;
   der Compass-Integritätsreport und seine Gates müssen identisch bleiben. Ohne
   echte Boundary-Evidenz darf die Karte nicht `Blocked by a boundary` heißen.
7. Nach einer reinen Ratingänderung darf Full Match nicht als notwendige
   Evidenzaktualisierung freigeschaltet werden. Ein alter Algorithmus oder ein
   Job außerhalb des letzten Laufs muss eine klare Projektionswarnung anzeigen.
8. Eine Explore- oder Match-Aufgabe starten und `Abort task` wählen. Queued muss
   sofort `Cancelled` werden; Running muss `Stopping after the current network
   step` und anschließend `Cancelled` zeigen. Wiederholtes Abort bleibt sicher.
9. Während einer laufenden Aufgabe den Browser schließen und wieder öffnen. Der
   lokale Python-Prozess läuft weiter. Bei hartem Prozessabbruch darf kein
   künstliches 94% stehen bleiben; nach Neustart wird die abgelaufene Arbeit
   wieder aufgenommen oder kann abgebrochen werden.
10. All Jobs in der Konfigurationsdiagnose prüfen: 20 je Plattform, 120
    Readback und USD 0.40 Laufdeckel. EURES und JobsPipe müssen ihre bisherigen
    Limits behalten.

## 6. Der erste Server-Deploy ist ein eigener, sauberer Vorgang

Nicht die lokale `.env`, SQLite-Datei, Testpersonas, CVs, Uploads oder Backups
auf den Server kopieren. Für den neuen VPS ausschließlich
[`deploy/.env.staging.example`](../../../../deploy/.env.staging.example) und den
[vollständigen Netcup-/Cloudflare-Ablauf](../deployment/netcup-cloudflare-private-alpha-v0.7.2i.md)
verwenden.

Der Ablauf verlangt unter anderem:

- Netcup VPS 1000 G12 als Startgröße und ein frisch gehärtetes Debian;
- Docker aus dem offiziellen Repository;
- einen exakt fixierten `v0.7.2i`-Commit/Tag oder das geprüfte Release-ZIP;
- Cloudflare Access mit exakten E-Mail-Adressen **vor** der Tunnelroute;
- eine neue Server-`.env` und ein separates Modus-`600`-Tunnel-Token;
- eine leere PostgreSQL-Datenbank und den Migration-Head `0033`;
- genau einen ersten Owner, danach sofort `invite_only`;
- keinen veröffentlichten App-, Caddy- oder Datenbankport;
- den Test, dass eine laufende Aufgabe einen Web-Container-Neustart überlebt;
- einen Abort-Test, Origin-Negativtests und einen verschlüsselten Off-Host-
  Backup-/Restore-Drill vor der ersten Einladung.

Ein kompletter VPS- oder Worker-Stopp kann keine Berechnung im ausgeschalteten
Zustand fortsetzen. Der Lease-Vertrag sorgt für kontrollierte Wiederaufnahme,
nicht für unmögliche Offline-Ausführung.

## 7. Release-ZIP bauen und prüfen

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2i.zip -Algorithm SHA256
```

Das Archiv muss die `i`-Release Notes, den lokalen Leitfaden, die Domain- und
Hostingentscheidung, den privaten Deployment-Runbook sowie Migrationen `0032`
und `0033` enthalten. Es darf keine `.env`, Tunnel-Tokens, Datenbanken,
Runtime-Daten, Uploads, Bewerbungsdokumente, Backups oder echten Secrets
enthalten.

## 8. Im Windows-Repository committen, pushen und taggen

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads
git ls-files .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2i"

git tag -a v0.7.2i -m "BetterOption v0.7.2i"
git push origin v0.7.2i
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für alle privaten Runtime- und Secret-Pfade leer bleiben.
Den Tag `v0.7.2h` weder verschieben noch wiederverwenden.
