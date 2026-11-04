> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.6 Release Notes

## Outcome

v0.6.6 completes three related product corrections without changing the
accepted warm design:

1. **Compass** supports one-section additions and direct fact maintenance, so a
   user no longer has to repeat all nine onboarding conversations.
2. Compatibility no longer falls merely because a job advertisement omits
   detailed preferences. Unknown evidence is visible but neutral.
3. Confirmed car, public-transit, bicycle, and walking limits can use cached,
   provider-backed route durations with explicit uncertainty.

The other navigation labels are now **Archive** and **Matching**, whole job
cards are clickable, and the private-alpha free allowance is 25 stored and
matched jobs.

## Upgrade on Windows

```powershell
cd C:\projects\betteroption

Copy-Item `
  .\local-data\betteroption.db `
  .\local-data\betteroption.pre-v0.6.6.db `
  -ErrorAction SilentlyContinue

Expand-Archive `
  "$HOME\Downloads\betteroption_v0_6_6_compass_mobility.zip" `
  -DestinationPath . `
  -Force

.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -v --cov=betteroption --cov-report=term
.\.venv\Scripts\python.exe -m compileall -q src examples scripts
```

Start the application and keep this PowerShell window open:

```powershell
cd C:\projects\betteroption

.\.venv\Scripts\python.exe -u -m uvicorn betteroption.web.app:create_app `
  --factory `
  --host 127.0.0.1 `
  --port 8000 `
  --log-level debug
```

These commands do not depend on permission to run unsigned PowerShell scripts.

## Optional commute provider

The application works without a route provider and will state that route time
is unknown. For local Google Routes testing, add only to `.env`:

```dotenv
BETTEROPTION_MOBILITY_PROVIDER=google
GOOGLE_ROUTES_API_KEY=replace-with-your-local-key
```

## Acceptance path

1. Open **Compass**, add one answer to a single section, and review only the new
   proposals.
2. Edit or reclassify one confirmed fact and remove another without restarting
   onboarding.
3. Open **Matching**, add a reachable job URL, and confirm the reference controls
   exist only there.
4. Open **Archive** and verify source state, checks, history, retry, and deletion.
5. Confirm the entire visible surface of archive and result cards opens detail.
6. Run matching and verify an otherwise relevant job is not penalized for
   unmentioned preferences; coverage and compatibility remain separate.
7. Confirm an unrelated job is not promoted to Top merely because unknowns are
   neutral.
8. Add a confirmed origin and one modal maximum, configure a provider, rerun,
   and verify duration, distance, limit result, observation time, and cache use.
9. Remove the provider configuration and confirm matching still completes with
   explicit route uncertainty.
10. Add up to 25 jobs, confirm the 26th new source is rejected before fetch, and
    confirm deletion frees a slot.

## New v0.6.6 files

```text
docs/archive/engineering-history/architecture/application-architecture-v0.6.6.md
docs/archive/engineering-history/release-notes/release-notes-v0.6.6.md
src/betteroption/migrations/versions/0005_commute_estimates.py
src/betteroption/mobility.py
src/betteroption/web/templates/profile_compass.html
tests/test_matching_v066.py
tests/test_mobility.py
```

## Updated v0.6.6 areas

```text
.env.example
README.md
docs/archive/engineering-history/design/job-and-matching-v0.1.md
docs/archive/engineering-history/design/job-corpus-v0.1.md
docs/archive/discontinued-product-planning/release-train-v0.6.md
pyproject.toml
scripts/build_release.py
src/betteroption/__init__.py
src/betteroption/access.py
src/betteroption/container.py
src/betteroption/database.py
src/betteroption/matching.py
src/betteroption/profile_workflow.py
src/betteroption/providers/openai.py
src/betteroption/result_repository.py
src/betteroption/results.py
src/betteroption/settings.py
src/betteroption/web/app.py
src/betteroption/web/static/app.css
src/betteroption/web/templates/base.html
src/betteroption/web/templates/dashboard.html
src/betteroption/web/templates/job_detail.html
src/betteroption/web/templates/jobs.html
src/betteroption/web/templates/match_detail.html
src/betteroption/web/templates/matches.html
src/betteroption/web/templates/opportunity_card.html
src/betteroption/web/templates/profile_conversation.html
src/betteroption/web/templates/profile_review.html
src/betteroption/web/templates/result_card.html
tests/test_dashboard.py
tests/test_foundation.py
tests/test_opportunity_web.py
tests/test_profile_web.py
tests/test_results_web.py
```

## Git staging and push

Run these only after the complete verification succeeds:

```powershell
git status --short
git add -A -- .env.example README.md pyproject.toml docs scripts src tests
git diff --cached --name-only
git diff --cached --check
git commit -m "Release v0.6.6 Compass mobility and calibrated matching"
git push
git status
git log -1 --oneline
```

The staged list must not contain `.env`, `local-data`, databases, source
snapshots, profile records, route caches, CVs, uploads, or virtual environments.

## Safety boundary

- Matching and commute-limit evaluation remain deterministic.
- Every advertisement claim remains linked to verified source evidence.
- Unknown advertisement and route facts remain unknown.
- User corrections remain authoritative and cannot be overwritten by later
  extraction.
- Route estimates and match snapshots are private database data and are never
  packaged with source.
- Authentication, subscriptions, and billing are not claimed by this release.

## Automated verification

- 106 pytest tests pass in both the source tree and a freshly extracted release
  archive.
- Branch-aware coverage is 83.40%, above the 80% gate.
- Ruff formatting and lint checks pass.
- Python bytecode compilation and a clean extracted-package test are part of
  the release procedure.
