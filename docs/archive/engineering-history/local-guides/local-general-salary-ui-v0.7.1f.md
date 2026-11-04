> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local upgrade and GitHub cycle for v0.7.1f

This guide upgrades the existing local v0.7.1e installation to
`v0.7.1f-general-salary-ui`, validates the general salary and interface fixes,
and stores the accepted source in the existing private GitHub repository. It
does not deploy a server or open a private alpha.

## 1. Stop the app and preserve local state

Stop `run_web.ps1` with `Ctrl+C`, then create a recoverable database copy:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force .\local-backups | Out-Null
if (Test-Path .\local-data\betteroption.db) {
  Copy-Item .\local-data\betteroption.db ".\local-backups\before-v071f-$stamp.db"
  Get-Item ".\local-backups\before-v071f-$stamp.db"
}

git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

The first Git command should identify the ignored private/runtime paths that
exist. The second command must print nothing. Do not paste, commit or place the
`.env`, database, CV text or API keys in a release ZIP.

## 2. Install the exact source overlay

Download the release ZIP into Downloads, then run:

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1f_general_salary_ui.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1f-general-salary-ui"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

The final command must print `0.7.1f-general-salary-ui`. The installer refreshes
product source and the editable Python installation while preserving `.env`,
`local-data`, personas and provider keys.

## 3. Keep the local account/persona boundary

Salary research uses the existing OpenAI key but has new explicit opt-in
settings. Check and update the existing `.env` locally without sharing it:

```dotenv
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_DATABASE_URL=sqlite:///local-data/betteroption.db
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_ACCOUNT_PERSONAS_ENABLED=true
BETTEROPTION_PERSONA_LIMIT=5
BETTEROPTION_LOCAL_PERSONAS_ENABLED=false
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000

BETTEROPTION_SALARY_RESEARCH_ENABLED=true
# BETTEROPTION_SALARY_RESEARCH_MODEL=<OPTIONAL_TASK_SPECIFIC_MODEL>
BETTEROPTION_SALARY_RESEARCH_MAX_JOBS=10
BETTEROPTION_SALARY_RESEARCH_MAX_TOOL_CALLS=10
BETTEROPTION_SALARY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0

BETTEROPTION_LEGAL_TERMS_VERSION=2026-08-01-draft
BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-01-draft
```

Use `BETTEROPTION_REGISTRATION_MODE=open` only while intentionally creating a
new local email account; return it to `disabled` afterwards and restart. Persona
creation inside an authenticated account is independent of registration mode.

Keep every numeric provider price as a real number or explicit `0` for
unknown/unpriced. Do not leave a numeric variable blank. Existing OpenAI,
Brave Search, Exa and routing keys remain in the private `.env`; automated tests
use fakes and must not spend provider budget.

`BETTEROPTION_SALARY_RESEARCH_ENABLED=true` is the deliberate local opt-in. It
uses the existing OpenAI project key and at most one bounded Web Search batch per
Match, only when the active Compass has a compensation criterion and an
advertisement omits pay. The provider receives public job title, resolved
country/coarse location, summary and limited public role, experience,
employment and weekly-hours facts—not the profile or target salary. The call may
incur model and Web Search charges; keep the provider-side budget plus
BetterOption operation/cost guards active. The configured per-call salary
estimate is conservatively reserved for the maximum allowed Web Search calls
before the batch starts.

The two `2026-08-01-draft` identifiers are intentional: salary research changes
the engineering-draft Terms and Privacy Notice. Existing accounts and personas
remain intact, while Account can show that the updated drafts need acknowledgement.

## 4. Run the complete release gate

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Do not continue to GitHub unless formatting, lint, tests and compilation all
pass.

## 5. Start locally

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000`. The database head remains
`0019_application_drafts`; startup should not apply a v0.7.1f schema migration.

## 6. Manual acceptance

### General salary behaviour

1. Run Match for a non-engineering role such as accounting, healthcare,
   customer service, education, skilled trades or sales.
2. When reliable benchmark evidence exists, confirm the salary section names
   the detected occupation, gives its source and labels the range as an
   estimate rather than employer pay.
3. Match an advertisement that states its own salary. Confirm the advertised
   evidence is used and no benchmark replaces it.
4. Match a vague or unsupported role. Confirm BetterOption leaves salary
   unknown instead of forcing it into an unrelated occupation family.
5. Match a vacancy in another supported European country. Confirm it never
   receives a German band and that country, original currency/pay period and
   source provenance are explicit. A EUR normalization, if shown, must retain an
   attributable ECB conversion reference no older than 31 days and remain
   distinct from the original benchmark.
6. Confirm a benchmark above or below a Compass target remains an `Unknown`
   evidence comparison and never hard-blocks the job.
7. Match an unsupported European or clearly non-European role. Confirm salary
   remains unknown rather than falling back to an unrelated country's range.
8. Open an older v0.7.1e result and confirm it remains readable but is marked as
   an older matching algorithm. Run Match again to create a v0.7.1f snapshot.

### Interface corrections

1. Open Apply on desktop and a narrow browser width. Confirm every checkbox,
   title, company, location, match label and draft status form one aligned row.
2. Open Job Detail and confirm the cover-letter action sits naturally with the
   application workflow and still opens the same selected job in Apply.
3. Open Personas and confirm a visible gap separates each name and creation
   date.
4. Mark one job `Rejected` and another `Withdrawn`. Confirm both Match and
   Archive cards show readable semi-transparent diagonal grey striping in
   addition to the state colour.
5. Change the states back and confirm the terminal treatment disappears.

Also smoke-test Compass, Explore, Add, Match, Apply, Archive, account switching
and persona isolation. No Apply action may submit a job or contact an employer.

## 7. Review the exact Git change

Stop the local server, then inspect before staging:

```powershell
git status --short
git diff --stat
git diff -- pyproject.toml src scripts docs tests .env.example README.md
git check-ignore .env local-data local-backups dist
git ls-files .env local-data local-backups dist
```

Review unexpected files. The final `git ls-files` command must print nothing.

## 8. Commit, push and tag the private repository

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1f-general-salary-ui"
```

The helper stages only product paths, checks for forbidden runtime or secret
files, shows the release set and asks before committing and pushing.

After the push succeeds, tag that exact commit:

```powershell
git log -1 --oneline
git tag -a v0.7.1f-general-salary-ui `
  -m "BetterOption v0.7.1f general salary and UI"
git push origin v0.7.1f-general-salary-ui

git status --short
git tag --points-at HEAD
git ls-files .env local-data local-backups dist
```

The worktree should be clean, the new tag should point at `HEAD`, and the final
command must print nothing. Confirm the commit and tag in the private GitHub
repository.

## 9. Rollback

If the release behaves unexpectedly, stop the app and keep both the current
database and logs for diagnosis. Reinstall the immutable v0.7.1e ZIP and restore
the matching `before-v071f-...db` backup before starting the older source. Do not
repeatedly overwrite the only database copy.

The conservative database restore matters even though v0.7.1f adds no table:
newer match-result snapshots may contain newer serialized evidence that older
source was never designed to interpret.

## 10. Still local only

Do not bind to `0.0.0.0`, publish a tunnel, add DNS or deploy the private-alpha
stack from this guide. Server security, processor review, DPIA, legal pages,
incident response, monitoring, encrypted backups and restore evidence remain a
separate go-live track.
