> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local upgrade and GitHub cycle for v0.7.1g

This guide upgrades the working local installation to
`v0.7.1g-user-controls`, validates the new account/provider and job-workflow
boundaries, and stores the accepted source in the existing private GitHub
repository. It deliberately performs no server deployment.

## 1. Stop the app and preserve local state

Stop `run_web.ps1` with `Ctrl+C`, then run:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force .\local-backups | Out-Null
if (Test-Path .\local-data\betteroption.db) {
  Copy-Item .\local-data\betteroption.db ".\local-backups\before-v071g-$stamp.db"
  Get-Item ".\local-backups\before-v071g-$stamp.db"
}

git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

The final command must print nothing. Never commit or copy `.env`, API keys,
the database, CV text, uploads or local backups into the release.

## 2. Install the exact source overlay

Place the downloaded ZIP in Downloads and run:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1g_user_controls.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1g-user-controls"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

The last command must print `0.7.1g-user-controls`. The installer refreshes the
product source and editable package while preserving `.env`, `local-data`,
accounts, personas and credentials. Startup advances the database to
`0022_application_draft_slots`.

## 3. Keep provider availability and pricing explicit

Do not replace the working `.env`. Check it locally and keep all provider keys
private. A numeric price must contain a real number; use explicit `0` only for
an estimate that has not yet been calibrated. Never leave numeric variables
blank, and never describe `0` as free.

The environment is the installation-wide availability ceiling. The Account
page is the user's narrower permission layer. After this migration all account
provider choices default to off, including OpenAI. This is intentional.

Start the app, sign in, open **Account → Provider choices**, enable only the
configured services you want that account and all of its personas to use, and
save. A second email account has its own choices. A persona cannot change the
account boundary.

For your present local workflow, enable only the services whose functionality
you intend to exercise. In particular:

- OpenAI is needed for AI-backed Compass/CV extraction, cover letters and the
  optional salary research/fallback;
- Brave requires the **Search** plan key; the separate Answers key is not used;
- Exa is a conditional Explore fallback;
- route/geocoder choices govern their respective commute calls;
- disabled means no call and no cost row;
- an enabled call with configured estimate `0` appears as **unpriced**.

Account totals show observed metadata-only operations and configured estimates,
not an invoice or forecast. Keep the provider dashboards' hard monthly limits
in place. Do not invent estimates yet; measure and configure them after the
architecture and UI settle.

## 4. Run the release gate

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

The automated suite uses fakes and must not consume real provider budget. Do
not continue to GitHub if formatting, lint, tests or compilation fails.

## 5. Start locally

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000`. Keep the host on `127.0.0.1`; do not bind to
`0.0.0.0`, expose a tunnel or add DNS for this local iteration.

## 6. Manual acceptance

1. Open Account before any provider action. Confirm all choices initially show
   off, enable the desired configured providers and verify the choice survives a
   restart and applies to every persona in the account.
2. Disable one provider and trigger its feature. Confirm the call is blocked
   before provider traffic and does not add a cost row. Re-enable a provider
   whose estimate is `0`, make one small call and confirm Account says unpriced.
3. Switch personas and confirm Compass, jobs, portals, evidence corrections and
   application drafts remain isolated while provider choices remain account-wide.
4. Add a public HTTPS employer career portal for one persona. Run Explore with
   an allowed search provider and confirm the hostname is used as a search hint.
   Disable it, then confirm another persona neither sees nor uses it.
5. Run Match for an advertisement without pay in a European country. Prefer a
   cited country/occupation benchmark. If validation finds none, confirm the
   broad fallback is visibly unsourced, very-low confidence and does not change
   the compatibility score. Advertised pay must suppress both alternatives.
6. On Job Detail, correct one reason, commute time and skill outcome. Rerun Match
   and confirm the overrides are reapplied only to that job/persona and marked as
   user corrections. Delete them and confirm automatic evidence returns without
   changing Compass.
7. Create three named cover-letter drafts for one eligible job. Rename, edit,
   save, shorten/lengthen/recreate exact drafts and use their direct links. A
   fourth creation must fail before OpenAI is called; deleting one frees a slot.
8. Confirm Apply's job selector is compact/collapsible, Explore cards are shorter,
   draft counts link to Apply, Add ends with Continue to Match, and Rejected or
   Withdrawn jobs remain readable under the stronger terminal-state treatment.
9. Smoke-test Compass, Explore, Add, Match, Apply, Archive, Account and persona
   switching. Nothing may submit a job or contact an employer.

## 7. Review the exact Git change

Stop the server, then inspect the product diff:

```powershell
git status --short
git diff --stat
git diff -- pyproject.toml src scripts docs tests .env.example README.md
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Review unexpected files. The final command must print nothing.

## 8. Commit, push and tag the private GitHub repository

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1g-user-controls"
```

The helper stages only product paths, rejects runtime/private paths, displays
the staged set and asks before commit/push. After it succeeds, tag that exact
commit:

```powershell
git log -1 --oneline
git tag -a v0.7.1g-user-controls `
  -m "BetterOption v0.7.1g user controls"
git push origin v0.7.1g-user-controls

git status --short
git tag --points-at HEAD
git ls-files .env local-data local-backups dist
```

The worktree should be clean, the new tag should point to `HEAD`, and the final
command must print nothing. Confirm both commit and tag in the private GitHub
repository.

## 9. Rollback

Stop the app and retain the failing database/logs for diagnosis. Reinstall the
immutable v0.7.1f ZIP and restore the corresponding
`before-v071g-...db` copy before starting v0.7.1f. Do not run older source
against the v0.7.1g database head or overwrite your only backup.

## 10. Still local, ready for later review

This guide does not deploy Netcup, Cloudflare or any other server. Private-alpha
deployment remains possible later, but first revisit provider contracts,
commercial suitability (especially hosted public routing services), the DPIA,
legal notices, security operations, monitoring and tested backup/restore.
