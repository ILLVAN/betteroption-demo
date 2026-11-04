> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.3 Release Notes

## Outcome

v0.6.3 turns **My compass** into the first complete interactive web workflow.
Users can answer nine free-text sections, review every extracted statement,
resume after interruption, return to skipped questions, answer clarifications,
and save verified reference-job URLs.

Profiles and conversation history now live in the SQL database. The ZIP
contains no runtime profile, database, secret, CV, upload, or local-data file.

## Safe Windows overlay

From the project directory in PowerShell:

```powershell
cd C:\projects\betteroption

if (Test-Path .\local-data\betteroption.db) {
    Copy-Item `
      .\local-data\betteroption.db `
      .\local-data\betteroption.pre-v0.6.3.db
}

Expand-Archive `
  "$HOME\Downloads\betteroption_v0_6_3_profile_conversation.zip" `
  -DestinationPath . `
  -Force

.venv\Scripts\Activate.ps1
.\scripts\verify.ps1
```

The first application command upgrades the database additively to
`0003_profile_workspaces`.

## Product acceptance test

```powershell
python examples\run_dashboard.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and verify:

1. **My compass** opens a natural-language conversation.
2. Submitting an answer opens the Review Tray.
3. Confirm, edit wording and category together, and remove all work.
4. Restarting during review resumes only the undecided statements.
5. A clarification resumes before the next core section.
6. **Ask me later** is reversible through **Revisit skipped questions**.
7. A valid public reference URL is checked and displayed with its resolved URL
   and HTTP status.
8. Copied text, private targets, unreachable pages, disallowed pages, and
   expired pages are not stored as verified references.
9. The home dashboard reflects confirmed profile categories from the database.

An OpenAI request occurs when a profile answer is submitted. Viewing pages,
reviewing existing facts, skipping, revisiting, and managing an already fetched
reference do not require profile extraction.

## Database and migration behavior

- `profile_workspaces` stores the validated typed session checkpoint.
- `conversation_messages` stores resumable section dialogue.
- Existing corpus and telemetry tables remain intact.
- If the database has no profile, the newest legacy JSON checkpoint is imported
  once and marked as the active workspace.
- New web profile state is never written back to a JSON checkpoint.

## Trust boundaries

- The model cannot confirm user intent.
- Each review mutation is durable and audited.
- User-reviewed facts are protected from later extraction refreshes.
- Reference learning is off by default and scoped explicitly when enabled.
- v0.6.3 stores learning permission but does not silently derive preferences
  from the advertisement.

## Verification result

The release gate runs Ruff formatting and lint checks, the complete pytest suite
with branch coverage, and Python bytecode compilation. The prepared release was
validated with 80 tests at 82.63% total coverage before packaging.

## Commit guidance

```powershell
git add .env.example .gitignore README.md pyproject.toml docs examples scripts src tests
git commit -m "Add database-backed web profile conversation"
git push
```

Never add `.env`, `local-data`, database backups, API keys, profiles, CV files,
or uploads.

## Next increment

v0.6.4 adds the opportunity inbox and URL-import workflow. It will reuse the
same public-URL safety and evidence contracts. Matching result views and
feedback stay in v0.6.5.
