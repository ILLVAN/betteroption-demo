> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.4 Release Notes

## Outcome

v0.6.4 adds a web opportunity inbox without changing the established warm
visual design. Users can submit a public job URL, see its verified source and
extracted details, refresh it, and inspect its check and revision history.

Failed URLs no longer vanish from the job workflow. Closed, unreachable, and
extraction-failed sources remain visible with honest states and retry actions.

## Reference failure clarification

The reported reference attempt reached the application successfully. The
external page returned HTTP 404, so it was correctly not stored as a reachable
reference. The message now explains that the job may have expired or used a
temporary redirect and suggests trying the employer's current careers page.

## Windows overlay and verification

```powershell
cd C:\projects\betteroption

if (Test-Path .\local-data\betteroption.db) {
    Copy-Item `
      .\local-data\betteroption.db `
      .\local-data\betteroption.pre-v0.6.4.db
}

Expand-Archive `
  "$HOME\Downloads\betteroption_v0_6_4_opportunity_inbox.zip" `
  -DestinationPath . `
  -Force

.venv\Scripts\Activate.ps1
.\scripts\verify.ps1
```

All tests use pytest. The remaining `unittest.TestCase` suites and runner entry
points were migrated; no `unittest` dependency remains in source or tests.

## Keep the test server running

Use a dedicated PowerShell window:

```powershell
.\scripts\run_web.ps1
```

This runs:

```powershell
python -u -m uvicorn betteroption.web.app:create_app `
  --factory `
  --host 127.0.0.1 `
  --port 8000 `
  --log-level debug
```

Keep that window open while testing [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Acceptance test

1. Confirm the existing Home and My compass design is unchanged.
2. Open **Opportunities** and submit a current public job URL.
3. Confirm that the detail page shows the extracted job, direct URL, HTTP status,
   check history, and Version 1.
4. Refresh it unchanged and verify that no second extraction is made.
5. Refresh after the advertisement changes and verify that Version 2 appears.
6. Submit an HTTP 404 URL and confirm it stays under **Closed**.
7. Confirm unreachable sources stay under **Needs a recheck**.
8. Confirm provider/extraction failures stay under **Needs extraction**.
9. Retry a failed item with **Check this link again**.
10. Submit copied job text and confirm it is rejected before fetching.

## Product policy

The first three matched opportunities remain free. v0.6.4 establishes that
policy explicitly; v0.6.5 applies it to the result experience. Imports are not
counted as free result views. Subscriptions and payment collection remain later
release work.

## Commit guidance

```powershell
git add .env.example .gitignore README.md pyproject.toml docs examples scripts src tests
git commit -m "Add the web opportunity inbox"
git push
```

Never add `.env`, `local-data`, database backups, source snapshots, API keys,
profiles, CVs, or uploads.

## Next increment

v0.6.5 presents Top, Stretch, and Blocked results with evidence, unknowns,
feedback, and application state. It will enforce the three-free-results policy
before subscription work begins.
