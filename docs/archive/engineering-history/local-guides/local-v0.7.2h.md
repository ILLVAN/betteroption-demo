> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.2h lokal installieren, testen und veröffentlichen

`v0.7.2h` wird direkt über die gepushte `v0.7.2g`-Baseline installiert. Die App
vorher vollständig stoppen und `.env`, Datenbank, `local-data`, Uploads und
lokale Backups privat sichern. Der Installer bewahrt diese Runtime-Daten.

## 1. Installation

Im bestehenden Windows-Repository ausführen:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_2h.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.2h"
```

Danach beide getrennten Kennungen prüfen:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; print(version('betteroption'))"
```

Erwartet:

```text
0.7.2h
0.7.2+h
```

`0.7.2+h` ist die kanonische PEP-440-Paketversion. Beim Start wird die additive
Migration `0031_private_alpha_roles_feedback` ausgeführt. Vor dem ersten Start
ist deshalb ein Datenbank-Backup Pflicht. Der Matchingvertrag ist
`matching-v0.7.2h`; ein gespeicherter älterer Lauf braucht einmal ein
vollständiges neues Matching.

## 2. Erhaltene und neue Konfiguration

Der Installer überschreibt die vorhandene `.env` nicht. Folgenden sicheren
Block in PowerShell ausführen; er ergänzt nur die neue Preview-Einstellung und
aktualisiert ausschließlich bekannte ältere Privacy-Draft-Werte:

```powershell
$envPath = Join-Path (Get-Location) ".env"
$lines = [System.Collections.Generic.List[string]]::new()
if (Test-Path $envPath) {
  Get-Content $envPath | ForEach-Object { [void]$lines.Add($_) }
}

function Set-WlbEnvValue([string]$Key, [string]$Value) {
  $prefix = "$Key="
  for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index].StartsWith($prefix)) {
      $lines[$index] = "$prefix$Value"
      return
    }
  }
  [void]$lines.Add("$prefix$Value")
}

$privacyKey = "BETTEROPTION_LEGAL_PRIVACY_VERSION"
$knownDrafts = @("2026-08-01-draft", "2026-08-05-draft")
$currentPrivacy = $lines |
  Where-Object { $_.StartsWith("$privacyKey=") } |
  Select-Object -First 1
if (-not $currentPrivacy -or $knownDrafts -contains $currentPrivacy.Substring($privacyKey.Length + 1)) {
  Set-WlbEnvValue $privacyKey "2026-08-05-feedback-draft"
}
Set-WlbEnvValue "BETTEROPTION_EXPLORE_PREVIEW_LIMIT" "9"

[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
```

Eigene oder rechtlich freigegebene Privacy-Kennungen werden nicht ersetzt. Der
Preview-Wert darf zwischen 3 und 12 liegen. Für den lokalen Betrieb sind keine
Cloudflare- oder Rollenvariablen nötig.

Für einen neuen privaten Server nicht die lokale `.env` kopieren. Verwende
stattdessen ausschließlich den
[Netcup + Cloudflare Runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2h.md) und
`deploy/.env.staging.example`. Das Token `deploy/cloudflared-token` ist ein
Server-Secret und darf weder ins ZIP noch ins Repository gelangen.

## 3. Diagnose, Migration und vollständiger Test

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

`diagnose_jsearch.py` macht ohne `--live` keinen Provideraufruf. Für dieses
Release ist kein Live-Provider-Probe erforderlich.

## 4. Manuelle Abnahme

1. Auf Home, Matching und Archive jeweils Job- und Arbeitgeber-Sterne ändern.
   Sterne, Score, Gruppe und Reihenfolge müssen den gespeicherten Serverzustand
   zeigen. Eine absichtlich gestörte Layout-Aktualisierung darf die gespeicherten
   Sterne nicht zurücksetzen.
2. Browser-Zurück/Weiter und Job Detail prüfen. Keine gecachte alte Reihenfolge
   darf erscheinen; ein Blocked-Job verschwindet von Home, bleibt aber im
   Archive.
3. Einen neuen vollständigen Match ausführen. Nur tatsächlich ausgewertete
   Jobs wechseln zu `Matched`; ein bereits `Shortlisted`, `Preparing` oder
   später eingeordneter Job behält seinen Zustand. Derselbe Match erzeugt kein
   zweites History-Ereignis.
4. Die Compass-Integritätsnotiz auf Compass, Add, Explore, Matching, Apply und
   Archive öffnen. Außerhalb des Guided-Setup-Dialogs darf kein `Ask me later`
   mehr erscheinen. Im Guided Setup bleibt die funktionierende Option erhalten.
5. Explore starten. Unter dem Status-Tile erscheinen standardmäßig bis zu neun
   nicht-klickbare Spitzenreiter; fehlende Evidenz gibt keinen Bonus. Einen Wert
   von 3 und 12 über `BETTEROPTION_EXPLORE_PREVIEW_LIMIT` gegenprüfen.
6. Einen Treffer mit nicht automatisch lesbarem Text prüfen. Das Badge lautet
   `Needs pasted text`; die Erklärung bleibt im Tooltip verständlich.
7. Im Account-Betrieb den ersten `first_user` prüfen: Er ist Admin. Einen
   weiteren Account in Operations zum Tester machen; dafür muss das aktuelle
   Admin-Passwort erneut eingegeben werden. Job-Poster-Freigabe bleibt getrennt.
8. Das WorkLifeBalance-Feedbackformular ausfüllen, eigenen Eintrag prüfen und in
   Operations Status, Notiz und CSV testen. Keine private Job-/Compass-/CV-
   Information eingeben. Löschen und die 180-Tage-Retention gegenprüfen.
9. Den letzten Admin mit einem zweiten bestehenden Account nicht demoten oder
   löschen können. Nach Löschung aller anderen Accounts darf der einzige Owner
   sein eigenes Konto weiterhin vollständig löschen.
10. Den Staging-Compose-Vertrag nur statisch prüfen, solange keine echten
    Netcup-/Cloudflare-Zugänge vorliegen: keine veröffentlichten Webports,
    separates Tunnel-Secret, Access vor Route und Origin-Negativtests als
    offene Operator-Gates.

## 5. Release-ZIP

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\dump_release.ps1

Get-FileHash .\dist\betteroption_v0_7_2h.zip -Algorithm SHA256
```

Das Archiv muss `docs/archive/engineering-history/release-notes/release-notes-v0.7.2h.md`,
`docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2h.md`,
`docs/archive/discontinued-product-planning/hosting-and-public-roadmap-v0.7.2h.md` und den neuen privaten
Deployment-Runbook enthalten. Es darf `deploy/.env.staging`,
`deploy/cloudflared-token`, Datenbanken, Runtime-Daten, CVs, Uploads oder
Provider-Secrets nicht enthalten.

## 6. Git-Upload

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git check-ignore .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads
git ls-files .env deploy/.env.staging deploy/cloudflared-token local-data local-backups dist uploads

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.2h"

git tag -a v0.7.2h -m "BetterOption v0.7.2h"
git push origin v0.7.2h
git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

`git ls-files` muss für alle privaten Runtime- und Secret-Pfade leer bleiben.
Bestehende Tags nicht verschieben oder wiederverwenden.
