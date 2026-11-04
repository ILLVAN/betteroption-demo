# UI walkthrough

The prototype uses server-rendered Jinja templates with progressive JavaScript
updates. Its interface name is WorkLifeBalance. The following screens are
implemented; live results depend on your local data and configured providers.

| Screen | Route | What to inspect | Template |
| --- | --- | --- | --- |
| Home | `/` | Workflow entry points, saved state, and current opportunities | [dashboard.html](../src/betteroption/web/templates/dashboard.html) |
| Compass | `/profile` | Guided preferences, fact levels, evidence, review, and integrity notices | [profile_compass.html](../src/betteroption/web/templates/profile_compass.html) |
| Explore | `/explore` | Search controls, progressive candidates, provenance, and source status | [explore.html](../src/betteroption/web/templates/explore.html) |
| Add a job | `/add` | URL ingestion or deliberate manual input | [add.html](../src/betteroption/web/templates/add.html) |
| Saved jobs | `/jobs` | Imported jobs and lifecycle state | [jobs.html](../src/betteroption/web/templates/jobs.html) |
| Job Detail | `/jobs/{record_id}` | Source evidence, private corrections, employer context, and ratings | [job_detail.html](../src/betteroption/web/templates/job_detail.html) |
| Matching | `/matches` | Ranked results, known/unknown conditions, and inspectable scoring | [matches.html](../src/betteroption/web/templates/matches.html) |
| Apply | `/apply` | Candidate-controlled drafts and application progress | [apply.html](../src/betteroption/web/templates/apply.html) |
| Account | `/account` | Personas, provider choices, account controls, and export | [account.html](../src/betteroption/web/templates/account.html) |
| Operations | `/operations` | Operator-visible tasks, provider activity, budgets, and diagnostics | [operations.html](../src/betteroption/web/templates/operations.html) |

Account/persona scope and operator permissions affect which pages and actions
are available. Routes and authorization are composed in
[web/app.py](../src/betteroption/web/app.py).

## Suggested review path

1. Start locally with a fresh database and synthetic account/profile data.
2. Inspect the Compass: user answers and corrections determine active facts;
   indirect evidence has a review path.
3. Inspect Explore's source status and provenance. Approximate distance helps
   scan candidates; it is separate from exact commute estimates.
4. Save or manually add one synthetic job and inspect Job Detail before Match.
   Full AI workflows require an explicitly configured extraction provider.
5. Inspect the result explanations, unknown conditions, corrections, and rating
   effects. Application material remains under the candidate's control.

Tests such as [test_profile_web.py](../tests/test_profile_web.py),
[test_results_web.py](../tests/test_results_web.py), and
[test_v072j_manual_job.py](../tests/test_v072j_manual_job.py) exercise these
flows with controlled data and fake providers.

## Frontend implementation

[base.html](../src/betteroption/web/templates/base.html) owns the shared shell.
[app.css](../src/betteroption/web/static/app.css) supplies the visual system;
[app.js](../src/betteroption/web/static/app.js) and
[task_progress.js](../src/betteroption/web/static/task_progress.js) handle
interactive controls and progress. Templates keep evidence, uncertainty, task
state, and user corrections visible alongside results.
