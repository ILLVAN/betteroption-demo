> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2g lokal installieren, testen und veröffentlichen

`v0.7.2g` wird direkt über die gepushte `v0.7.2f`-Baseline installiert. Die
App vorher vollständig stoppen und `.env`, `local-data`, Uploads und lokale
Backups privat sichern. Der Installer bewahrt diese Runtime-Daten.

## 1. Installation

Im bestehenden Windows-Repository ausführen:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2g.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2g"
```

Danach beide getrennten Kennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartet:

```text
0.7.2g
0.7.2+g
```

`0.7.2+g` ist die kanonische PEP-440-Paketversion. Es gibt keine
Datenbankmigration. Der Matchingvertrag ist `matching-v0.7.2g`; ein gespeicherter
`f`-Lauf braucht deshalb einmal ein vollständiges neues Matching.

## 2. Erhaltene Konfiguration

Der Privacy-Draft bleibt
`BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-draft`, weil `g` keinen neuen LLM-Datenweg
einführt. Eine bereits nach dem `f`-Leitfaden aktualisierte `.env` braucht keine
weitere Änderung. Die Integritätsprüfung läuft deterministisch im Prozess, und
die Explore-Vorschau enthält ausschließlich bereits gefundene öffentliche
Anzeigedaten.

Vor einer öffentlichen Registrierung weiterhin nicht einfach
`BETTEROPTION_REGISTRATION_MODE=open` aktivieren. Die geschlossene Alpha bleibt
invite-only. Turnstile mit serverseitiger Prüfung und eine enge Cloudflare-
Rate-Limit-/Challenge-Regel für den Registrierungs-POST sind spätere Hosted-
Launch-Gates, keine lokale `g`-Funktion.

## 3. Diagnose und vollständiger Test

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

`diagnose_jsearch.py` macht ohne `--live` keinen Provideraufruf. Für dieses
Release ist kein neuer Live-Probe erforderlich.

## 4. Manuelle Abnahme

1. Matching öffnen, einen Job und anschließend dessen Arbeitgeber bewerten.
   Score, Gruppe, Counts und Reihenfolge müssen sich ohne Reload aktualisieren;
   die Karten dürfen nur kurz gleiten. Mit reduzierter Bewegung gibt es keine
   Animation.
2. Im Job Detail Bewertung oder Evidenz ändern und über `Back to Matching`, die
   Navigation und die Browser-Zurück-Taste zurückkehren. Keine alte Reihenfolge
   darf sichtbar bleiben.
3. Einen konfliktfreien Score von mindestens 60 prüfen: Er gehört zu Top. Ein
   Score unter 60 gehört zu Stretch. Ein belegter harter Widerspruch oder eine
   0-Sterne-Sperre bleibt Blocked.
4. Im Compass dieselbe Bedingung als Must-have und Ausschluss anlegen. Add,
   freie Explore-Suche und Archive bleiben nutzbar; Search with Compass,
   Matching und neue Cover Letters warten auf die Klärung. `Ask me later`
   blendet nur den aktuellen Hinweis aus und umgeht den Gate nicht.
5. Remote-only plus On-site-only als harte positive Grenzen prüfen. Der Hinweis
   muss eine klare Hauptaktion und gegebenenfalls eine zweite Persona anbieten.
   On-site-only plus Ausschluss von fully remote darf nicht fälschlich als
   Konflikt gelten. Zwei bestätigte Limits wie höchstens zwei und mindestens
   vier Bürotage können dagegen nicht dieselbe Suche leiten und müssen die
   konsumierende Aktion bis zur Korrektur blockieren.
6. In Guided Setup einen neuen Mobilitätsursprung und eine Sprache mit Niveau
   angeben. Compass-Widget und Compass-Explore müssen dieselben Werte verwenden.
   Eine Sprache ohne sicheres Niveau erscheint als Hinweis zur Niveauwahl.
7. Guided Setup auf Desktop mit langem Chat prüfen. Die größere weiße
   `Edit your answers`-Kachel bleibt vertikal zentriert und enthält das
   ausklappbare `Start a new compass`.
8. Explore starten. Unter dem großen Status-Tile müssen bis zu sieben
   nicht-klickbare aktuelle Spitzenreiter erscheinen und sich nach neuen
   Quellen neu ordnen. Fehlende Evidenz darf keinen Bonus anzeigen.
9. Eine veröffentlichte Stelle aus der eigenen HR-Eingabe prüfen. Sie muss in
   Explore mit dunkelblauem `Own` erscheinen. Kein Job-Badge darf `Scraper` oder
   `Scraping` enthalten.
10. Wartetexte beobachten: eine Zeile, ein Satz, keine Semikolons und deutlich
    langsamere Wechsel. Kandidatenoberflächen dürfen den Namen `BetterOption`
    nicht anzeigen.

## 5. Release-ZIP

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2g.zip -Algorithm SHA256
```

## 6. Git-Upload

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env local-data local-backups dist uploads
git ls-files .env local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2g"

git tag -a v0.7.2g -m "BetterOption v0.7.2g"
git push origin v0.7.2g
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für die privaten Runtime-Pfade leer bleiben. Bestehende Tags
nicht verschieben oder wiederverwenden.
