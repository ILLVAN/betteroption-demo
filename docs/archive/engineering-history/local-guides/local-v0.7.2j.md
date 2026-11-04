> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2j lokal installieren, testen und veröffentlichen

`v0.7.2j` wird als Overlay über das bereits lokal installierte und als
`v0.7.2i` gepushte Repository installiert.
Die lokale Datenbank bleibt ausschließlich lokal. Für den neuen Netcup-Server
wird später eine leere PostgreSQL-Datenbank nach dem separaten
[Private-Alpha-Runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2j.md) angelegt.

## 1. Lokale Runtime sichern und App sauber stoppen

Im Repository zuerst die App mit `Ctrl+C` vollständig beenden und auf den
Uvicorn-Shutdown warten. Danach `.env` und `local-data` privat sichern. Diese
Dateien gehören nie in Git oder das Release-ZIP.

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path (Get-Location) "local-backups\before-v0.7.2j-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path .env) { Copy-Item .env (Join-Path $backup ".env") }
if (Test-Path local-data) {
  Copy-Item local-data (Join-Path $backup "local-data") -Recurse
}
```

## 2. Release-ZIP installieren

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2j.zip"
$expectedSha256 = "PASTE-THE-64-CHARACTER-SHA-256-FROM-THE-RELEASE-HANDOFF"

$actualSha256 = (Get-FileHash -LiteralPath $release -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
  throw "Paste the complete SHA-256 from the trusted v0.7.2j handoff first."
}
if ($actualSha256 -ne $expectedSha256.ToLowerInvariant()) {
  throw "SHA-256 mismatch. Do not open or install this ZIP."
}
Write-Host "Verified release SHA-256: $actualSha256"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2j"
```

Die Hashprüfung steht absichtlich **vor** dem Installer: Beim Upgrade von `i`
läuft zunächst noch das `i`-Installationsskript, das den neuen Parameter
`-ExpectedSha256` nicht kennt. Erst die oben gezeigte, erfolgreiche Prüfung
erlaubt das Öffnen, Entpacken und Installieren. Der mit `j` ausgelieferte
Installer verlangt den Hash künftig selbst; ab der nächsten Version lautet der
Aufruf zusätzlich `-ExpectedSha256 $expectedSha256`.

Der Installer erhält `.env`, `.venv`, `local-data`, Uploads und lokale Backups.
Danach die getrennten App- und Paketkennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartet:

```text
0.7.2j
0.7.2+j
```

Die additiven `i`-Migrationen `0032_explore_import_origin` und
`0033_background_task_leases` bleiben der aktuelle Schema-Head. Der Matchingvertrag
bleibt bewusst `matching-v0.7.2i`, weil `j` weder Gewichtung noch Prompt ändert.
Ein bereits aktueller `i`-Match bleibt daher gültig; ein vollständiger Rematch
ist für dieses Upgrade nicht erforderlich.

## 3. Bestehende `.env` kontrolliert ergänzen

Der Installer überschreibt `.env` absichtlich nicht. `j` führt keine neue
Pflichtvariable ein. Der folgende Block stellt die bereits in `i` eingeführten
Kosten- und Workerwerte sicher und ersetzt nur ältere Defaults. Eigene bereits
kalibrierte Werte bleiben erhalten.

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
App-Prozess. Den Browser zu schließen unterbricht ihn nicht. `Abort task` macht
den Task sofort terminal; ein bereits gesendeter externer HTTP-Request kann noch
bis zu seinem Timeout auslaufen, darf danach aber nichts mehr speichern. Ein
sauberes `Ctrl+C` cancelt den aktuell eingebetteten Task und wartet nicht mehr
auf solche Fremdserver-Threads. Auf dem Server gilt umgekehrt `ENABLED=false`
und `EXTERNAL=true`, weil dort der eigene Compose-Worker läuft.

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

1. Eine Explore-Suche starten. Der Balken muss bei `0 %` beginnen, während der
   Wartezeit langsam steigen und vor Abschluss höchstens `94 %` anzeigen. Nach
   Neuladen derselben Task-Seite darf er nicht auf null zurückspringen; nur ein
   erfolgreicher Abschluss darf `100 %` erreichen.
2. Eine Explore-Aufgabe abbrechen. Der anklickbare Button muss sofort
   verschwinden; `Cancelling…` darf nicht wie ein zweiter Button aussehen. Die
   Task-Seite muss direkt `Cancelled` anzeigen und darf nicht wieder auf
   `Running` wechseln.
3. Eine zweite Explore-Suche starten und im PowerShell-Fenster einmal `Ctrl+C`
   drücken. Uvicorn muss ohne zweiten Tastendruck und ohne
   `concurrent.futures.thread._python_exit`-/`KeyboardInterrupt`-Traceback
   enden. Nach Neustart darf der lokal abgebrochene Task nicht bei `94 %`
   weiterlaufen.
4. Einen Job per Text einfügen, speichern und in Job Detail öffnen. Falls kein
   Match vorhanden ist, muss dort `Match this job only` erscheinen. Die Aktion
   darf genau diesen Job auswerten; andere gespeicherte Jobs dürfen nicht
   rematcht werden. Das gilt auch für einen Paste ohne optionale Quell-URL.
5. Einen weiteren manuellen Job nach einem vollständigen Match hinzufügen und
   nur diesen matchen. Die vorhandenen Resultate und ihre Reihenfolge müssen
   erhalten bleiben; nur der neue Job wird in den aktuellen Lauf gemischt. Bei
   einem wirklich alten Matchingalgorithmus muss die UI stattdessen einen
   vollständigen Match verlangen.
6. In Job Detail den Arbeitgebernamen überschreiben. Der neue Name muss sofort
   im Detail-Header sowie auf Home-, Archive-, Matching- und Apply-Karten stehen.
   Der automatische Name links bleibt sichtbar, ist aber grau und
   durchgestrichen.
7. Je einen weiteren Override für Gehalt, Postingdatum, Pendelweg,
   Arbeitsmodus, Reason, Skill, Company Context, Arbeitgebertypen, Reputation
   und Bewerbungshinweise speichern. Bei jedem
   betroffenen Vergleich muss die automatische linke Seite grau und
   durchgestrichen erscheinen; Labels, Belege, Links und Provenienz dürfen
   nicht durchgestrichen werden. `Restore automatic` muss die Darstellung
   wiederherstellen.
8. Zwischen zwei Personas wechseln. Die Einzel-Match-Route darf einen Job ohne
   Grant der aktiven Persona weder anzeigen noch starten. Overrides und
   angezeigter Arbeitgebername bleiben persona-lokal.
9. Prüfen, dass ein vorhandener `i`-Match nach dem Upgrade weiterhin
   Quickscore-Aktualisierungen annimmt. `j` verlangt keinen künstlichen
   Full-Rematch und ändert weder `matching-v0.7.2i` noch
   `match-evidence-v0.7.2i`.
10. Die wichtigsten `i`-Abnahmen nochmals stichprobenartig prüfen: Vacancy-ID
    und Postingdatum bleiben derselben Karte zugeordnet, `Needs pasted text`
    rettet robots-gesperrte Quellen, Ratings ändern keine Compass-Integrität,
    und All Jobs bleibt bei 20 Ergebnissen je Plattform, 120 Readback sowie
    USD 0.40 Laufdeckel.

## 6. Der erste Server-Deploy ist ein eigener, sauberer Vorgang

Nicht die lokale `.env`, SQLite-Datei, Testpersonas, CVs, Uploads oder Backups
auf den Server kopieren. Für den neuen VPS ausschließlich
[`deploy/.env.staging.example`](../../../../deploy/.env.staging.example) und den
[vollständigen Netcup-/Cloudflare-Ablauf](../deployment/netcup-cloudflare-private-alpha-v0.7.2j.md)
verwenden.

Der Ablauf verlangt unter anderem:

- Netcup VPS 1000 G12 als Startgröße und ein frisch gehärtetes Ubuntu Server
  24.04 LTS;
- Docker aus dem offiziellen Repository;
- einen exakt fixierten `v0.7.2j`-Commit/Tag oder das geprüfte Release-ZIP;
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

Get-FileHash .\dist\betteroption_v0_7_2j.zip -Algorithm SHA256
```

Das Archiv muss die `j`-Release Notes, den lokalen Leitfaden, die Domain- und
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
  -CommitMessage "Release BetterOption v0.7.2j"

git tag -a v0.7.2j -m "BetterOption v0.7.2j"
git push origin v0.7.2j
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für alle privaten Runtime- und Secret-Pfade leer bleiben.
Den Tag `v0.7.2i` weder verschieben noch wiederverwenden.
