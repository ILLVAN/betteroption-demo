> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.5 Release Notes

## Outcome

v0.6.5 adds database-backed Top, Stretch, and Blocked results while retaining the
accepted v0.6.4 design. Results show concrete supporting evidence, conflicts,
unknowns, required-skill coverage, and **Why still apply?** guidance for Stretch
opportunities.

The accepted page story is now explicit: Compass owns profiling, Matches is
the single job/reference input, and Opportunities is the archive. Five jobs can
be stored, matched, and inspected without an email gate. The allowance persists
across reruns. Confirmed deletion frees a slot. Feedback, notes, application
state, and append-only decision history survive restarts.

## Upgrade on Windows

```powershell
cd C:\projects\betteroption

Copy-Item `
  .\local-data\betteroption.db `
  .\local-data\betteroption.pre-v0.6.5.db `
  -ErrorAction SilentlyContinue

Expand-Archive `
  "$HOME\Downloads\betteroption_v0_6_5_evidence_results.zip" `
  -DestinationPath . `
  -Force

.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -v --cov=betteroption --cov-report=term
.\.venv\Scripts\python.exe -m compileall -q src examples scripts
.\.venv\Scripts\python.exe -u -m uvicorn betteroption.web.app:create_app `
  --factory `
  --host 127.0.0.1 `
  --port 8000 `
  --log-level debug
```

The raw commands above do not depend on Windows allowing unsigned PowerShell
scripts. `verify.ps1` and `run_web.ps1` remain optional shortcuts and activate
`.venv` automatically when policy permits them. The Uvicorn command is:

```powershell
.\.venv\Scripts\python.exe -u -m uvicorn betteroption.web.app:create_app `
  --factory `
  --host 127.0.0.1 `
  --port 8000 `
  --log-level debug
```

## Acceptance path

1. Open **Compass** and either resume the current conversation or explicitly
   confirm a clean restart. Verify the opening free-text box starts section one.
2. Open **Matches** and add a job URL with positive, negative, and optional
   learning-scope settings.
3. Confirm the job and reference settings appear on Matches while the source and
   revision history appear in the Opportunities archive.
4. Add five jobs and confirm a sixth new URL is rejected before fetching.
5. Create a match run and inspect the Top, Stretch, and Blocked groups.
6. Verify that explanations cite advertisement text and preserve unknowns.
7. Confirm all five stored Top/Stretch details remain included.
8. Inspect a Blocked result and verify the boundary conflicts remain visible.
9. Save feedback and an application state, refresh, and inspect decision history.
10. Delete one job from its archive detail after checking the confirmation box.
    Confirm its history and reference settings disappear and a new job can use
    the freed fifth slot.
11. Change the compass and confirm the old run is marked stale before rerunning.

## Git staging and push

New v0.6.5 files:

```text
docs/archive/engineering-history/architecture/application-architecture-v0.6.5.md
docs/archive/engineering-history/release-notes/release-notes-v0.6.5.md
src/betteroption/migrations/versions/0004_match_results.py
src/betteroption/result_repository.py
src/betteroption/results.py
src/betteroption/web/templates/match_detail.html
src/betteroption/web/templates/matches.html
src/betteroption/web/templates/result_card.html
tests/test_results_web.py
```

Updated v0.6.5 files:

```text
README.md
docs/archive/engineering-history/design/job-and-matching-v0.1.md
docs/archive/engineering-history/design/job-corpus-v0.1.md
docs/archive/discontinued-product-planning/release-train-v0.6.md
pyproject.toml
scripts/build_release.py
scripts/run_web.ps1
scripts/verify.ps1
src/betteroption/__init__.py
src/betteroption/access.py
src/betteroption/container.py
src/betteroption/dashboard.py
src/betteroption/database.py
src/betteroption/job_corpus.py
src/betteroption/job_repository.py
src/betteroption/migrations/env.py
src/betteroption/profile_repository.py
src/betteroption/profile_workflow.py
src/betteroption/web/app.py
src/betteroption/web/static/app.css
src/betteroption/web/templates/base.html
src/betteroption/web/templates/dashboard.html
src/betteroption/web/templates/job_detail.html
src/betteroption/web/templates/jobs.html
src/betteroption/web/templates/profile_conversation.html
src/betteroption/web/templates/profile_start.html
tests/test_dashboard.py
tests/test_foundation.py
tests/test_opportunity_web.py
tests/test_profile_web.py
tests/test_release_package.py
```

After the verification script succeeds:

```powershell
git status --short
git add -A -- README.md pyproject.toml docs scripts src tests
git diff --cached --name-only
git diff --cached --check
git commit -m "Complete v0.6.5 evidence results and five-job flow"
git push
git status
git log -1 --oneline
```

The staged file list must not contain `.env`, `local-data`, databases, source
snapshots, profiles, CVs, uploads, or virtual-environment files.

## Safety boundary

- Matching remains deterministic.
- Every source link was successfully verified when the run was created.
- Unknown advertisement facts remain unknown.
- Feedback never silently changes the compass.
- Match/profile/job snapshots are database data and never packaged with source.
- Subscription and payment collection are not claimed by this release.

## Automated verification

- 98 pytest tests pass.
- Total branch-aware coverage is 83.62%, above the 80% gate.
- Ruff formatting and lint checks pass.
- Python bytecode compilation passes.
- A migrated v0.6.4 database reaches Alembic head `0004_match_results` without
  losing the existing corpus.

## Next increment

v0.6.6 adds cached road, rail, bicycle, and walking-time constraints with
explicit uncertainty. It does not begin until v0.6.5 is manually accepted and
pushed.
