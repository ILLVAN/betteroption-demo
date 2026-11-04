> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1j local install, acceptance, and GitHub cycle

This guide upgrades the existing Windows installation to
`v0.7.1j-candidate-control`, validates the candidate-controlled matching
workflow, and records the accepted source in the existing private GitHub
repository. The supported target remains `http://127.0.0.1:8000`; do not expose
this release through a server, tunnel, public bind, or DNS.

## 1. Stop the app and create a recoverable backup

Stop `run_web.ps1` or Uvicorn with `Ctrl+C`, then open PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071j-$stamp"
New-Item -ItemType Directory -Force $backup | Out-Null

Copy-Item ".\.env" "$backup\.env" -ErrorAction SilentlyContinue
Copy-Item ".\betteroption.db" "$backup\betteroption.db" -ErrorAction SilentlyContinue
Copy-Item ".\local-data" "$backup\local-data" -Recurse -ErrorAction SilentlyContinue

Get-ChildItem $backup -Force
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

The final command must print nothing. Keep the backup directory until J has
been accepted. `.env`, databases, CV text, uploads, API keys, and local data
must never enter Git or the release ZIP.

## 2. Install the exact J archive

Place the downloaded ZIP in Downloads and pass its exact path:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1j_candidate_control.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1j-candidate-control"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

The last command must print `0.7.1j-candidate-control`. The overlay installer
preserves `.env`, the database, and `local-data`; it reinstalls the editable
package but deliberately does not run tests. Application startup advances the
linear migration chain through head `0028_job_ratings`.

If the existing `.env` overrides any outbound User-Agent, update or remove
these three old I values so the J defaults are not masked:

```dotenv
BETTEROPTION_TRANSITOUS_USER_AGENT=BetterOption/0.7.1j-candidate-control (+https://github.com/ILLVAN/betteroption)
BETTEROPTION_VALHALLA_USER_AGENT=BetterOption/0.7.1j-candidate-control (+https://github.com/ILLVAN/betteroption)
BETTEROPTION_OSM_GEOCODER_USER_AGENT=BetterOption/0.7.1j-candidate-control (+https://github.com/ILLVAN/betteroption)
```

## 3. Preserve provider permissions, keys, and numeric costs

J needs no new API key. Do not replace the working `.env`; keep every real key
there and nowhere else. Existing OpenAI, Brave Search, Exa, Google Routes, and
openrouteservice keys remain optional according to the features you use.

Before a provider action, open **Account → Provider choices**. The environment
decides which adapters are technically available; the account's narrower
choices apply to all of its personas. Disabled providers must produce no call
and no provider-cost entry. Enabled calls remain attributed and counted.

Every numeric provider price must be a number. Keep an explicit `0` only while
the price is not calibrated; BetterOption then records the call as used but
unpriced, never free. Do not leave any of these settings blank:

```dotenv
BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD=0
BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD=0
BETTEROPTION_DISCOVERY_ESTIMATED_COST_PER_SEARCH_USD=0
BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_SALARY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD=0
```

`BETTEROPTION_PROVIDER_DAILY_COST_LIMIT_USD=0` and
`BETTEROPTION_PROVIDER_ACTION_COST_LIMIT_USD=0` mean that the corresponding
monetary limit is disabled; they are guardrails, not price estimates. Retain
the separate operation-count limits and provider-dashboard hard limits.

Run the secret-safe configuration check without probing a live provider:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

## 4. Run focused and complete tests

The focused release/package and J behavior tests use fakes and consume no real
provider budget:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_release_package.py `
  tests\test_v071f_release.py `
  tests\test_v071j_matching_core.py `
  tests\test_v071j_application_guidance.py `
  tests\test_v071j_discovery_quality.py `
  tests\test_v071i_employer_reputation.py `
  tests\test_v071i_evidence_web.py
```

Then run formatting, lint, the full suite, and compilation through the shipped
gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Do not continue to GitHub if either command fails.

## 5. Run on loopback and verify the migration head

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000/health/ready` and confirm the response is ready,
uses the expected database, and reports `0.7.1j-candidate-control`. Then open
`http://127.0.0.1:8000`. Startup must complete the migrations through
`0028_job_ratings` without creating a second Alembic head.

Keep `BETTEROPTION_WEB_HOST=127.0.0.1`. Application guidance is supported
locally; its hosted gate remains closed unless separate legal and processor
reviews are explicitly completed. J itself provides no hosted-use approval.

## 6. Manual acceptance

Use one account with two personas, two jobs from the same employer, a third job
from another employer, and at least one advertisement with explicit application
contact/process text.

1. On Job Detail, confirm **Employer rating** and **Job rating** are separate.
   On Home, Archive/Jobs, and Matches, confirm every job card exposes the
   exact-job rating directly. The employer-wide control intentionally remains
   on Job Detail. Confirm the two star sets use distinct BetterOption palette
   colors and neither uses generic yellow.
2. Leave both controls `Unrated`, rematch, and confirm neither blocks nor changes
   the score. Set the employer to 0 stars, rematch, and confirm jobs for that
   normalized employer are blocked. Clear it back to `Unrated` and confirm the
   block disappears after rematching.
3. Set one exact job to 0 stars and confirm only that vacancy is blocked. Give
   the employer and job different 1–5 ratings and verify both published score
   adjustments appear separately in the score mechanics.
4. Change a job rating directly from a job card and the employer rating in Job
   Detail. Confirm each reports that a rematch is required, the employer value
   follows another job for the same company, and the job value does not. Switch
   persona/account and confirm no rating leaks.
5. Inspect score mechanics and verify Compass, required skills, posting
   freshness, employer rating, job rating, and evidence confidence reconcile to
   the displayed final score. An explicit 0 is a blocker; `Unrated` is neutral.
6. Correct employer relationship or company context on Job Detail. Verify the
   automatic evidence remains visible beside the effective private value and a
   one-job rematch keeps all unrelated saved results.
7. Inspect a job advertisement with a named contact and application process.
   If it was saved under I and shows `Unknown`, refresh/re-import its source;
   guidance is populated during extraction/source refresh and is not silently
   backfilled for existing records.
   Confirm every automatic value has source evidence. Correct one field, clear
   another, create an editable cover-letter draft, and verify the grounded
   effective contact is used. Email, phone, and application URL must remain in
   the local guidance tile but stay out of the OpenAI cover-letter prompt; only
   contact name/role and text-relevant application rules may be supplied.
   Restore all source-published values.
8. Test an advertisement without a contact. BetterOption must not invent one.
   No action may submit an application or contact an employer.
9. For equally relevant Exa and Brave copies of the same URL, confirm one Exa
   result remains. Confirm a materially more relevant Brave result can still
   win.
10. Confirm Home's carousel includes all current Top and Stretch opportunities,
    excludes blocked, rejected, and withdrawn jobs, and visibly marks old postings.
11. Disable one account provider and exercise its feature: no provider request
    or cost entry may appear. Re-enable a provider whose price is `0`, perform
    one minimal action, and confirm it is shown as used/unpriced rather than
    free.

## 7. Review without the Git pager

Stop the server. Use `--no-pager`; a bare `git diff` can open the `(END)` viewer
on Windows. Press `q` if a pager was opened accidentally.

```powershell
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

## 8. Commit, push, and tag the private GitHub repository

The guarded helper stages only product paths, rejects runtime/private files,
shows the staged set, creates the commit, and pushes the current branch after
confirmation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1j-candidate-control"
```

After that commit and push succeed, review the exact remote state and tag the
same commit:

```powershell
git --no-pager log -1 --oneline
git status --short

git --no-pager tag -a v0.7.1j-candidate-control `
  -m "BetterOption v0.7.1j candidate control"
git --no-pager push origin v0.7.1j-candidate-control

git --no-pager tag --points-at HEAD
git --no-pager log -1 --decorate --oneline
git status --short
```

Expected: the worktree is clean, `origin/main` and
`v0.7.1j-candidate-control` identify the accepted J commit, and private/runtime
paths remain untracked by Git.

## 9. Recoverable rollback

Do not run I source against a database migrated through `0028_job_ratings`, do
not downgrade the only database, and do not reset the accepted J worktree.
Keep the failing J database/logs for diagnosis and create a separate checkout
of the previous immutable tag:

```powershell
cd C:\projects\betteroption
$preJ = (Resolve-Path ".\local-backups\before-v071j-YYYYMMDD-HHMMSS").Path

git --no-pager worktree add ..\WorkLifeBalanceAI-v071i `
  v0.7.1i-evidence-workflow

cd ..\WorkLifeBalanceAI-v071i
Copy-Item "$preJ\.env" ".\.env" -Force -ErrorAction SilentlyContinue
Copy-Item "$preJ\local-data" ".\local-data" -Recurse -ErrorAction SilentlyContinue
Copy-Item "$preJ\betteroption.db" ".\betteroption.db" -ErrorAction SilentlyContinue

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1
```

Replace the timestamp placeholder with the verified pre-J backup directory.
Immediately verify the immutable checkout with:

```powershell
.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Start the separate I checkout only after it prints
`0.7.1i-evidence-workflow`. The original J checkout and J database stay intact,
so recovery does not discard the new ratings or corrections. Remove neither
checkout nor backup until the fault has been diagnosed.
