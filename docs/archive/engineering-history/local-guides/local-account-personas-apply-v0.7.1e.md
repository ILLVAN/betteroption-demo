> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local accounts, personas and Apply for v0.7.1e

This is the complete Windows path from an installed
`v0.7.1d-local-personas` checkout to the tested
`v0.7.1e-account-personas-apply` checkpoint in the existing private GitHub
repository. It preserves the local SQLite database and `.env`; it does not
deploy a server or open an alpha.

## 1. Stop and back up the local database

Stop `run_web.ps1` with `Ctrl+C`, then create a recoverable database copy:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force .\local-backups | Out-Null
if (Test-Path .\local-data\betteroption.db) {
  Copy-Item .\local-data\betteroption.db ".\local-backups\before-v071e-$stamp.db"
  Get-Item ".\local-backups\before-v071e-$stamp.db"
}
```

`.env`, `local-data`, `local-backups`, uploaded CVs, databases and API keys must
remain untracked and outside every release ZIP.

## 2. Install the exact release overlay

Place the release ZIP in Downloads, then run:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1e_account_personas_apply.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1e-account-personas-apply"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

The printed version must be `0.7.1e-account-personas-apply`. The installer
copies product files only, refreshes the editable virtual-environment install,
and preserves `.env` and `local-data`.

## 3. Configure local account/persona use

Review `.env` without pasting it into chat or committing it. The relevant local
boundary is:

```dotenv
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_DATABASE_URL=sqlite:///local-data/betteroption.db
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=open
BETTEROPTION_ACCOUNT_PERSONAS_ENABLED=true
BETTEROPTION_PERSONA_LIMIT=5
BETTEROPTION_LOCAL_PERSONAS_ENABLED=false
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000

OPENAI_API_KEY=<CURRENT_PROJECT_KEY>
OPENAI_MODEL=<CURRENT_SUPPORTED_MODEL>
# BETTEROPTION_APPLICATION_DRAFT_MODEL=<OPTIONAL_TASK_SPECIFIC_MODEL>
BETTEROPTION_APPLICATION_BATCH_LIMIT=5
BETTEROPTION_RETENTION_APPLICATION_DRAFT_DAYS=180
```

Keep all numeric price variables numeric. Use a real price or explicit `0` for
unknown/unpriced; never leave a numeric value blank.

`BETTEROPTION_REGISTRATION_MODE=open` is useful on loopback to create several
real email accounts. After creating the accounts needed for local testing,
change it to `disabled` if you want to prevent accidental registrations. That
does not remove existing accounts or their personas.

Each email/password registration is an independent account. A signed-in account
can then create up to five passwordless personas. Persona switching never asks
for another account's password and must never reveal another account.

## 4. Run the complete automated gate

The tests use fakes for paid provider calls; the release gate must not spend API
budget.

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Do not continue to GitHub if formatting, lint, tests or compilation fails.

## 5. Start and migrate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000`. The first application startup applies:

- `0018_account_owned_personas`: one `Main` persona per existing account,
  existing account workspaces attached to that persona, and existing sessions
  pointed at it;
- `0019_application_drafts`: private editable drafts keyed by persona workspace
  and job.

The migration intentionally does not merge email accounts. For example, two
v0.7.1d registrations such as `legacy-one` and `legacy-two` stay separate accounts, each
with its own `Main` persona. Create additional perspectives below the desired
account after signing in.

If startup migration fails, stop the app, keep the traceback, preserve the
failed database separately, and restore the pre-v0.7.1e copy. Do not repeatedly
modify the only backup.

## 6. Manual local acceptance

### Accounts and personas

1. Sign in as account A and open Personas.
2. Confirm only account A's personas appear.
3. Create and switch to a persona without entering another password.
4. Add different Compass content or a saved job in that persona.
5. Switch back and verify the other persona's private data is absent.
6. Sign out, sign in as account B, and verify neither account A's personas nor
   their Compass/jobs/matches/drafts are visible.
7. Confirm the sixth persona is refused when the five-slot limit is reached.

### Add and Match

1. Confirm navigation order includes `Explore`, `Add`, `Match`, `Apply`,
   `Archive`.
2. Open Add, save or update a public job URL, and check existing references.
3. Open Match and verify matching content begins immediately instead of sitting
   below the Add form.
4. Confirm prior jobs, references and results were preserved.

### Apply

1. Open a current eligible matched job and follow `Create cover letter`, or open
   Apply from navigation.
2. Select one job first and explicitly request generation.
3. Confirm the draft is concise and grounded in the real job and confirmed
   Compass; remove anything unsupported.
4. Edit and save the text, then verify it remains after reload.
5. Exercise recreate, longer and shorter; each is a new explicit provider call.
6. Delete the draft and verify it is gone.
7. Confirm no action sends an email, contacts an employer or submits an
   application.

For provider troubleshooting, run diagnostics that do not print secrets. Never
post `.env` or API keys in logs or screenshots.

## 7. Review the exact Git change

Stop the app, then inspect before staging:

```powershell
git status --short
git diff --stat
git diff -- pyproject.toml src scripts docs tests .env.example
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

`git ls-files` must print none of those private/runtime paths. Review any
unexpected file before committing.

## 8. Commit and push the product to the private repository

The guarded helper stages only product paths, checks the index for runtime data
and secrets, asks once, commits, and pushes the current branch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1e-account-personas-apply"
```

After that push succeeds, tag the exact release commit and push the tag:

```powershell
git log -1 --oneline
git tag -a v0.7.1e-account-personas-apply `
  -m "BetterOption v0.7.1e account personas and Apply"
git push origin v0.7.1e-account-personas-apply
```

If the commit already exists, do not create a duplicate. Verify its imported
version and tag that commit.

Final verification:

```powershell
git status --short
git log -2 --oneline
git tag --points-at HEAD
git ls-files .env local-data local-backups dist
```

The worktree should be clean, the new tag should point at `HEAD`, and the final
command must print nothing. Confirm both the commit and tag in the private
GitHub repository.

## 9. What this checkpoint does not do

This release does not deploy a public server, publish DNS, enable automatic
applications or declare the legal package complete. The legal pages and
compliance documents remain engineering drafts pending qualified external
review. Before any private alpha, revalidate HTTPS/origin controls, invitation
mode, processors/transfers, DPIA, retention jobs, incident response,
monitoring, encrypted backups and restore evidence against the real deployment.
