> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1i local install, acceptance, and GitHub cycle

The supported target remains `http://127.0.0.1:8000`. No server is required.

## 1. Stop and back up

Stop the running app with `Ctrl+C`, then open PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\local-backups\before-v071i-$stamp"
New-Item -ItemType Directory -Force $backup | Out-Null
Copy-Item ".\betteroption.db" "$backup\betteroption.db" -ErrorAction SilentlyContinue
Copy-Item ".\.env" "$backup\.env" -ErrorAction SilentlyContinue
Copy-Item ".\local-data" "$backup\local-data" -Recurse -ErrorAction SilentlyContinue
```

`local-backups`, `.env`, databases, CVs, and local data are excluded from the
release and must never be committed.

## 2. Install the exact ZIP

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1i_evidence_workflow.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1i-evidence-workflow"
```

The overlay installer preserves `.env`, `betteroption.db`, and `local-data`.
Application startup advances the database to migration head
`0024_posting_date_evidence`.

## 3. Keep provider configuration unchanged

No new API key is required for I. Keep real secrets only in `.env`:

```dotenv
OPENAI_API_KEY=<current WorklifebalanceAI project key>
BRAVE_SEARCH_API_KEY=<Brave Search-plan key>
EXA_API_KEY=<Exa key>
GOOGLE_ROUTES_API_KEY=<Google Routes key>
```

Unknown numeric prices must contain explicit `0`, not a blank value. Account
provider choices continue to apply to every persona; this release does not
silently enable a provider that the account disabled.

## 4. Run the complete checks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

## 5. Run locally

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000`.

## 6. Focused acceptance

Use one persona, at least three current jobs, a job with an existing cover-letter
draft, and a job without one.

1. From a no-draft Job Detail page, open Apply. Confirm all eligible jobs remain
   visible, only the requested job is selected, and no unrelated draft group is
   expanded.
2. From a job with drafts, open Apply. Confirm all jobs remain visible, only the
   requested job is selected, and that job's draft group opens.
3. Confirm rejected and withdrawn jobs are absent from Home's current
   opportunities but remain available in Archive/history.
4. Confirm the main navigation orders `Add` before `Explore`.
5. Add one previously missing required skill to the active persona Compass.
   Reopen Compass and verify it is confirmed there; switch persona and verify it
   did not leak.
6. Rate an employer, open another job from the same employer in the same persona,
   and verify the rating follows it. Switch persona and verify isolation. Clear
   the rating with `Unrated`.
7. Inspect a match with an explicit posting date. Confirm its date/freshness is
   visible, edit it, rematch only that job, then restore the automatic date.
8. Inspect a job without a source posting date. It must say `Unknown`, not the
   date BetterOption imported it.
9. Expand several evidence disclosures and confirm explanations, quotes,
   sources, and provider diagnostics are still available.
10. Confirm evidenced skills are teal/green, missing skills are cautionary, and
    application-state watermarks do not cover the state dropdown.

## 7. Review without the Git pager

Use `--no-pager`; a bare `git diff` can open the `(END)` viewer. Press `q` if it
happens.

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git --no-pager log -1 --oneline
```

Windows LF/CRLF messages are checkout warnings, not test failures.

## 8. Commit, push, and tag the private GitHub repository

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1i-evidence-workflow"
```

After the guarded helper succeeds:

```powershell
git --no-pager log -1 --oneline
git status --short

git tag -a v0.7.1i-evidence-workflow `
  -m "BetterOption v0.7.1i evidence workflow"
git push origin v0.7.1i-evidence-workflow

git tag --points-at HEAD
```

Expected: `git status --short` prints nothing and the I tag points at the same
commit as `origin/main`.

## Rollback

The previous code checkpoint is the private tag
`v0.7.1h-workflow-refinement`. Prefer a separate checkout or reinstall the H ZIP
overlay; do not use destructive Git commands against the working copy. Because I
adds migrations, restoring code H also requires the pre-I database backup if H
must write the database. Keep the I backup until acceptance is complete.
