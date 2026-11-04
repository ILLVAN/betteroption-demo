> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1h local install, acceptance, and GitHub cycle

The supported target is `http://127.0.0.1:8000`. No server is needed.

## 1. Stop and back up

Stop the running app with `Ctrl+C`, then open PowerShell:

```powershell
cd C:\projects\betteroption

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force ".\local-backups\before-v071h-$stamp" | Out-Null
Copy-Item ".\betteroption.db" ".\local-backups\before-v071h-$stamp\betteroption.db" -ErrorAction SilentlyContinue
Copy-Item ".\.env" ".\local-backups\before-v071h-$stamp\.env" -ErrorAction SilentlyContinue
Copy-Item ".\local-data" ".\local-backups\before-v071h-$stamp\local-data" -Recurse -ErrorAction SilentlyContinue
```

`local-backups`, `.env`, databases, CVs, and local data are excluded from the
release and must never be committed.

## 2. Install the exact ZIP

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1h_workflow_refinement.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1h-workflow-refinement"
```

The overlay installer preserves `.env`, the local database, and `local-data`.
The database remains at migration head `0022_application_draft_slots`.

## 3. Verify local provider configuration

Keep real secrets only in `.env`. Relevant variables include:

```dotenv
OPENAI_API_KEY=<current WorklifebalanceAI project key>
BRAVE_SEARCH_API_KEY=<Brave Search-plan key>
EXA_API_KEY=<Exa key>
GOOGLE_ROUTES_API_KEY=<Google Routes key>
```

Brave Answers uses a different product/key and is not called by BetterOption.
Unknown numeric prices must be explicit `0`, not blank. Zero means unpriced,
not free.

All technically available providers now start enabled. After sign-in, use
`Account → External services` only when you want to opt out. Provider choices
belong to the email account and apply to every persona.

## 4. Run tests

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

Use at least two jobs and one job with two drafts.

1. Open Apply normally. Confirm each job appears once and its drafts are nested
   beneath it.
2. From Job Detail, choose Create cover letter. Confirm only that job is shown,
   checked, and ready for the one-time action.
3. Save a boundary/skill/commute correction. Confirm the automatic and user
   values remain side by side and the one-job rematch prompt appears.
4. Choose the one-job rematch and verify other job results remain present.
5. Run a complete Match and verify the correction is still applied.
6. Under Account, disable one harmless provider, run the related action, and
   confirm it is blocked before a request. Re-enable it afterwards.
7. Add a saved employer portal. In Explore, verify `Include custom portals` is
   checked by default and the portal scope appears in source-run diagnostics.
8. Confirm `/Error` or `SearchJobs` landing pages do not appear as jobs.
9. Review all application states; terminal cards should be light and readable.

## 7. Review changes without the Git pager

Use `--no-pager`; a bare `git diff` can open the `(END)` viewer. If it happens,
press `q` to return to PowerShell.

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
git --no-pager log -1 --oneline
```

The LF/CRLF messages on Windows are warnings about future checkout line endings,
not test failures.

## 8. Commit, push, and tag the private GitHub repository

The guarded helper shows the staged file list and asks before committing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1h-workflow-refinement"
```

Then verify and tag:

```powershell
git --no-pager log -1 --oneline
git status --short

git tag -a v0.7.1h-workflow-refinement `
  -m "BetterOption v0.7.1h workflow refinement"
git push origin v0.7.1h-workflow-refinement

git tag --points-at HEAD
```

Expected: `git status --short` prints nothing and the H tag points at the same
commit as `origin/main`.

## Rollback

The code checkpoint is the existing private tag `v0.7.1g-user-controls`; the
database schema is unchanged. Restore the pre-H database backup only if local
data itself was damaged. Do not use destructive Git commands against the working
copy; install the G ZIP overlay or create a separate checkout from the tag.

