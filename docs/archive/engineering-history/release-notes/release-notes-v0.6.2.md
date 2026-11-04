> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.2 Release Notes

## Outcome

v0.6.2 combines the planned 0.6.1 and 0.6.2 increments. It adds a provider-
neutral application foundation, versioned database migrations, privacy-aware
model invocation telemetry, and the first local FastAPI dashboard.

The dashboard is deliberately read-only. It makes the proven profile, corpus,
match, evidence, and verified-URL state visible without introducing a second
mutation path before the web interaction contracts are ready.

## Safe Windows installation

From the project directory, with PowerShell:

```powershell
cd C:\projects\betteroption

if (Test-Path .\local-data\betteroption.db) {
    Copy-Item `
      .\local-data\betteroption.db `
      .\local-data\betteroption.pre-v0.6.2.db
}

Expand-Archive `
  "$HOME\Downloads\betteroption_v0_6_2_foundation_dashboard.zip" `
  -DestinationPath . `
  -Force

.venv\Scripts\Activate.ps1
.\scripts\verify.ps1
```

The verification script installs the new FastAPI, Alembic, settings, template,
and server dependencies before running the full test suite and coverage gate.

## Dashboard test

Start the local server:

```powershell
python examples\run_dashboard.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), then check:

1. Home loads and shows **Welcome home**.
2. Your profile progress appears under **Your compass** when a saved session
   exists.
3. The CMBlu job appears under **Current opportunities** and on the complete
   Opportunities shelf.
4. Opening it shows a direct **Open verified job page** link, the last check
   time, HTTP status, saved-version count, and technical history.
5. Open, Closed, and Needs a recheck filters work.
6. Narrowing the browser window produces a comfortable single-column mobile
   layout.
7. `Ctrl+C` stops the server cleanly.

No OpenAI call is made merely by viewing the dashboard.

## Database migration

The first v0.6.2 command that opens the database adds Alembic version state and
the `model_invocations` table. An intact v0.6.0 corpus is adopted in place. The
migration does not delete or rewrite job records, aliases, revisions, or
observations. A partial legacy schema is rejected with a recovery-oriented error
instead of being guessed.

## Model architecture

- Profile and job extraction have independent task routes.
- The active provider remains OpenAI for this release.
- CLI and web entry points share one application composition root.
- Provider calls record operational metadata, not user or job content.
- Cost remains unknown unless explicit, current per-token rates are configured.

Optional `.env` overrides are documented in `.env.example`.

## Commit after verification

```powershell
git add .env.example README.md pyproject.toml docs examples scripts src tests
git commit -m "Add provider foundation and local dashboard"
git push
```

Never add `.env`, `local-data`, database backups, API keys, or CV files.

## Next increment

v0.6.3 moves the guided profile and protected Review Tray into the web
interface. Its mutation routes will call the existing application logic and
preserve append-only user decisions; the v0.6.2 read-only pages stay as the
regression baseline.

