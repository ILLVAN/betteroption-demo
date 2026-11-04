> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1k local install, acceptance, and GitHub cycle

This guide upgrades the existing Windows installation to
`v0.7.1k-local-evidence`, validates the local evidence workflow, and records
the accepted source in the existing private GitHub repository. The supported
target is only `http://127.0.0.1:8000`. Do not expose this release through a
server, tunnel, public bind, reverse proxy, or DNS record.

## 1. Stop the app and create a verified full backup

First stop `run_web.ps1` or Uvicorn with `Ctrl+C`. Do not copy a live SQLite
database. Then open PowerShell and run this complete sequence:

```powershell
cd C:\projects\betteroption

# App vorher mit Ctrl+C beenden
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071k-$stamp"

New-Item -ItemType Directory -Force $backup | Out-Null

# Konfiguration und lokale Daten binär sichern
Copy-Item ".\.env" "$backup\.env" -ErrorAction SilentlyContinue
Copy-Item ".\local-data" "$backup\local-data" -Recurse -ErrorAction Stop

# Zusätzlich portablen SQLite-SQL-Dump erzeugen
$db = (Resolve-Path ".\local-data\betteroption.db").Path
$dump = Join-Path (Resolve-Path $backup).Path "betteroption-$stamp.sql"

@'
import sqlite3
import sys

source, destination = sys.argv[1], sys.argv[2]

with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as database:
    with open(destination, "w", encoding="utf-8", newline="\n") as output:
        for statement in database.iterdump():
            output.write(statement + "\n")

print(f"SQL dump created: {destination}")
'@ | .\.venv\Scripts\python.exe - $db $dump

# Sicherungen anzeigen und Prüfsummen erzeugen
Get-ChildItem $backup -Force
Get-FileHash "$backup\local-data\betteroption.db" -Algorithm SHA256
Get-FileHash $dump -Algorithm SHA256

# Portablen Dump in einer neuen In-Memory-Datenbank vollständig einlesen
.\.venv\Scripts\python.exe -c `
  "import sqlite3,sys; db=sqlite3.connect(':memory:'); db.executescript(open(sys.argv[1], encoding='utf-8').read()); print('SQL dump verified successfully')" `
  $dump

git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Do not install until the verification prints `SQL dump verified successfully`,
the binary database and SQL dump both have SHA-256 hashes, and the final Git
command prints nothing. Keep the entire backup directory; it contains `.env`,
the complete `local-data` tree, and the independently portable SQL dump.

`local-backups`, `.env`, databases, CV text, uploads, API keys, and local data
must never enter Git or the release ZIP.

## 2. Install the exact K archive

Place the downloaded ZIP in Downloads and pass its exact path and expected
version:

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1k_local_evidence.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1k-local-evidence"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

The final command must print `0.7.1k-local-evidence`. The overlay installer
preserves `.env`, the database, CV text, and `local-data`; it reinstalls the
editable package but deliberately does not run tests.

K adds no migration. Startup must report the existing linear head
`0028_job_ratings` rather than creating or applying a K-specific revision.

If `.env` overrides an outbound User-Agent, update or remove these old values
so the K defaults are not masked:

```dotenv
BETTEROPTION_TRANSITOUS_USER_AGENT=BetterOption/0.7.1k-local-evidence (+https://github.com/ILLVAN/betteroption)
BETTEROPTION_VALHALLA_USER_AGENT=BetterOption/0.7.1k-local-evidence (+https://github.com/ILLVAN/betteroption)
BETTEROPTION_OSM_GEOCODER_USER_AGENT=BetterOption/0.7.1k-local-evidence (+https://github.com/ILLVAN/betteroption)
```

Do not replace the working `.env`. K needs no new API key. Check configuration
without calling a live provider:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Numeric provider prices must contain a number. Keep explicit `0` only while a
price is uncalibrated; BetterOption then records usage as used but unpriced,
never free. Blank numeric values are invalid.

## 3. Run focused and complete tests

The focused checks use fakes and consume no provider budget:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_release_package.py `
  tests\test_v071f_release.py `
  tests\test_v071k_application_privacy.py `
  tests\test_v071k_compensation_calibration.py `
  tests\test_job_corpus.py `
  tests\test_v071j_matching_core.py `
  tests\test_v071i_evidence_web.py
```

Then run formatting, lint, the complete suite, and compilation through the
shipped gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Do not proceed to GitHub if either command fails.

## 4. Run only on loopback

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000/health/ready` and confirm that it reports ready,
the intended database, and `0.7.1k-local-evidence`. Then open
`http://127.0.0.1:8000`.

Keep `BETTEROPTION_WEB_HOST=127.0.0.1`. This iteration has no server rollout.
Do not use `0.0.0.0`, Cloudflare, a public DNS record, or a tunnel for testing.

## 5. Manual acceptance

Use an existing account/persona and a disposable test persona. Include one
live-URL job with explicit application instructions, one manually pasted job
with an optional citation URL, and one job with incomplete company evidence.

1. Open Compass and find the annual gross compensation range. Confirm the
   neutral state is `0` to `200000` and creates no matching constraint. Save a
   minimum and target, reopen Compass, and confirm both values persist. A guided
   compensation answer should update the same range rather than a second salary
   field. Reset to `0` and `200000` and confirm the salary boundary disappears.
2. Open the incomplete job's **Why it landed here** section. Confirm missing
   relationship/company/reputation/date/route/skill evidence exposes subdued
   grey editing prompts, not completed automatic findings. Change several
   fields and verify one sticky **Save all changes** action appears. Save once,
   rematch only that job, and confirm unrelated match results remain.
3. Review the employer relationship selector. Confirm it includes direct
   employer, staffing and recruitment agencies, freelance, contractor,
   intermediary, platform, consultancy, other, and unknown without treating
   every nuanced arrangement as a proven direct contract.
4. Change multiple required skills to **I can do this**. Leave **Also update my
   Compass from skill changes** enabled, save once, and confirm each new skill
   appears once in the active persona's confirmed Compass. Marking a skill not
   evidenced must not remove an existing Compass skill. Switch persona and
   confirm the changes remain isolated.
5. Rerun Match for a clearly supported job. In score mechanics, confirm
   **Corroborated positive-fit calibration** contributes one point per positive
   hard requirement, preference, or required skill, never exceeds `+4`, and is
   zero when a hard/exclusion violation is present. Existing employer/job star
   effects and explicit 0-star blockers must remain unchanged.
6. Import a live advertisement containing an explicit contact and application
   process in German, English, or French. Confirm local Job Detail shows only
   source-grounded values and evidence. Generate an editable cover letter and
   confirm it uses `[LOCAL SALUTATION]`, a neutral team greeting, or no greeting;
   it must not contain the contact's name, identifying role, honorific, email,
   phone, application URL, or an invented gendered salutation. Insert the
   reviewed local recipient yourself only after generation.
7. Add a job by pasting advertisement text and optionally include its public
   URL. Use refresh for that job and bulk refresh. Both must state that manual
   input is never fetched or reverified, preserve the same local revision, and
   avoid any network-verification badge or timestamp. A live URL import remains
   a separate deliberate workflow.
8. Exercise Home, Add, Explore, Match, Job Detail, Apply, Archive/Jobs,
   Personas, Account, export, provider choices, employer rating, and job rating.
   Confirm existing J data remains present and no cross-persona value leaks.
9. Disable one account provider and exercise its feature: no provider request
   or cost entry may appear. Re-enable a provider priced at `0`, perform one
   minimal action, and confirm usage is shown as used/unpriced rather than free.

Nothing in this acceptance sends an application or contacts an employer.

## 6. Review without the Git pager

Stop the server with `Ctrl+C`. Use `--no-pager`; a bare `git diff` can open the
`(END)` viewer on Windows. Press `q` if a pager was opened accidentally.

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

Review every unexpected path. The final command must print nothing. Windows
LF/CRLF notices are checkout warnings, not test failures.

## 7. Guarded GitHub push and tag

The helper stages only product paths, rejects runtime/private files, shows the
staged set, and asks before committing and pushing the current branch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1k-local-evidence"
```

Only confirm after checking that `.env`, `local-data`, `local-backups`,
databases, CV/resume files, uploads, and provider keys are absent. After the
commit and push succeed, review the exact remote state and tag the same commit:

```powershell
git --no-pager log -1 --oneline
git status --short

git --no-pager tag -a v0.7.1k-local-evidence `
  -m "BetterOption v0.7.1k local evidence"
git --no-pager push origin v0.7.1k-local-evidence

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Expected: the worktree is clean, `origin/main` and
`v0.7.1k-local-evidence` identify the accepted K commit, and private/runtime
paths remain absent from Git.

## 8. Recoverable rollback

K adds no database migration, but it can write newer structured profile and
manual-source metadata. Do not downgrade the only working directory or let J
source write K-created data. Keep the failing K checkout/database for diagnosis
and restore the verified pre-K backup in a separate worktree:

```powershell
cd C:\projects\betteroption
$preK = (Resolve-Path ".\local-backups\before-v071k-YYYYMMDD-HHMMSS").Path

git --no-pager worktree add ..\WorkLifeBalanceAI-v071j `
  v0.7.1j-candidate-control

cd ..\WorkLifeBalanceAI-v071j
Copy-Item "$preK\.env" ".\.env" -Force -ErrorAction SilentlyContinue
Copy-Item "$preK\local-data" ".\local-data" -Recurse -ErrorAction Stop

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Replace the timestamp placeholder with the verified backup directory. Start
the separate checkout only after the final command prints
`0.7.1j-candidate-control`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

If the binary backup ever fails to open, the verified SQL dump in `$preK` is
the portable recovery source; do not overwrite the original dump. Keep both
checkouts and the complete backup until the K fault has been diagnosed.
