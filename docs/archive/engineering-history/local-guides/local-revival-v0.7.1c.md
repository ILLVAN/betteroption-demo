> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local revival and provider setup for v0.7.1c

This path restores the full BetterOption application for one person's local job
search. It keeps the future private-alpha architecture in the repository, but it
does not require Docker, Netcup, Cloudflare, DNS, a domain, PostgreSQL, or a
publicly reachable port.

The safe local boundary is:

```dotenv
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_AUTH_MODE=local
BETTEROPTION_DATABASE_URL=sqlite:///local-data/betteroption.db
BETTEROPTION_PUBLIC_BASE_URL=
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000
```

`scripts/run_web.ps1` deliberately binds `127.0.0.1:8000` regardless of the two
generic web variables. Use the deployment scripts, not this local helper, for a
future server.

## 1. Choose the data path

Both choices use the same application code.

### Start with a fresh local database

Do not copy an older database. Startup creates
`local-data/betteroption.db` and migrates it to the current Alembic head. Local
auth has no sign-in screen and therefore no `first_user` step.

### Reuse the existing local database

Make a recoverable copy before installing the overlay:

```powershell
cd C:\projects\betteroption
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force .\local-backups | Out-Null
Copy-Item .\local-data\betteroption.db ".\local-backups\betteroption-$stamp.db"
Copy-Item .\.env ".\local-backups\env-$stamp.txt"
```

`local-backups` contains secrets/private data: keep it out of Git. The release
installer does not replace `.env` or `local-data`. Startup applies additive
migrations automatically. The server database is not needed for this revival.

## 2. Install the exact release

Never rely on “newest ZIP” when old `b`, `b-legal`, and `c` archives coexist.
Pass the exact file.

### Existing BetterOption project tree

Download `betteroption_v0_7_1c_local_quality.zip`, then run the installer already
present in the project:

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1c_local_quality.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Expected:

```text
0.7.1c-local-quality
```

An older installer may not know the new `-ExpectedVersion` option; the explicit
Python check above is intentionally compatible with it. Once this release is
installed, later exact installs can add:

```powershell
-ExpectedVersion "0.7.1c-local-quality"
```

### Clean folder or restored private repository

```powershell
$release = "$HOME\Downloads\betteroption_v0_7_1c_local_quality.zip"
$project = "C:\projects\betteroption-local"
New-Item -ItemType Directory -Force $project | Out-Null
Expand-Archive -Path $release -DestinationPath $project -Force
Set-Location $project

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1
```

For an existing database, copy the old `.env` and
`local-data\betteroption.db` into this clean folder before running bootstrap.
Bootstrap never deletes either file.

Keeping the source in a private Git repository is sufficient source history.
The ZIP is a tested, immutable checkpoint and recovery input; it is not a
replacement for the private repository.

## 3. Create fresh provider keys

Edit only the untracked `.env`:

```powershell
notepad .env
```

Use separate project/development keys and never paste them into chat, Git,
screenshots, source files, or browser JavaScript.

### OpenAI

1. Create or select a dedicated BetterOption project in the OpenAI API platform.
2. Create a new project-scoped secret key under that project's **API Keys**.
3. Configure a deliberately small project spend limit/alerts and restrict model
   usage as appropriate.
4. Put the key only in `.env`.

```dotenv
OPENAI_API_KEY=replace-with-new-project-key
OPENAI_MODEL=gpt-5.6-luna
BETTEROPTION_LLM_PROVIDER=openai
```

The release already uses the Responses API structured-output path. The current
OpenAI model catalog identifies `gpt-5.6-luna` as the cost-sensitive GPT-5.6
variant; keep it initially so restoration and quality changes are not mixed.

Official sources:

- https://platform.openai.com/docs/quickstart/make-your-first-api-request
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://help.openai.com/en/articles/8304786-preventing-unauthorized-usage

### Brave Search

1. Sign in to the Brave Search API dashboard.
2. Subscribe to the **Search** API plan, not the consumer search subscription
   and not the separate **Answers** API plan.
3. Open **API Keys**, create a local-development key, and copy it once.

```dotenv
BRAVE_SEARCH_API_KEY=replace-with-new-brave-key
```

BetterOption calls Brave's `/res/v1/web/search` endpoint for Explore candidates
and employer research. It has no Brave Answers code path, so an Answers-only key
cannot replace `BRAVE_SEARCH_API_KEY`; `BRAVE_ANSWERS_API_KEY` is deliberately
unused. Validate the Search credential with one fixed, non-user-data request
(one billed/credited Search call):

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
```

Official sources:

- https://api-dashboard.search.brave.com/documentation/quickstart
- https://api-dashboard.search.brave.com/documentation/guides/authentication
- https://api-dashboard.search.brave.com/api-reference/web/search/get

### Exa

1. Sign in to the Exa dashboard.
2. Open **API Keys** and create a separate local-development key.
3. Keep Exa as the conditional low-coverage fallback.

```dotenv
EXA_API_KEY=replace-with-new-exa-key
BETTEROPTION_EXA_FALLBACK_MIN_RESULTS=30
```

Official sources:

- https://dashboard.exa.ai/api-keys
- https://exa.ai/docs/reference/search-api-guide

### Google Routes

The old Google project can be reused, but an empty Credentials page plus a
disabled `routes.googleapis.com` service means the previous key is no longer an
active credential. To restore Google routing:

1. Select the intended Google Cloud project.
2. Attach/enable a billing account.
3. Enable **Routes API** (`routes.googleapis.com`).
4. Open **APIs & Services → Credentials → Create credentials → API key**.
5. Restrict the key to **Routes API**. For a stable public source IP, also apply
   a web-server IP restriction. A changing residential IP may require updating
   that restriction; never use a browser-referrer restriction for this
   server-side call.
6. Set small quotas/budget alerts in Google Cloud.

```dotenv
GOOGLE_ROUTES_API_KEY=replace-with-new-google-key
BETTEROPTION_MOBILITY_PROVIDER=auto
BETTEROPTION_MOBILITY_PRIVACY_MODE=balanced
```

`privacy_first` deliberately does not call Google even when a key exists.
`balanced` explicitly opts the local tool into Google-first routing; Transitous
and Valhalla remain fallbacks.

Official source:

- https://developers.google.com/maps/documentation/routes/get-api-key

## 4. Preserve the numeric cost contract

Numeric settings may be a real current estimate or explicit `0`; they must not
be blank. `0` means unknown/unpriced, never free:

```dotenv
BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD=0
BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD=0
BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD=0
```

Keep the operation-count rails active even while monetary estimates are zero:

```dotenv
BETTEROPTION_PROVIDER_DAILY_OPERATION_LIMIT=1000
BETTEROPTION_PROVIDER_ACTION_OPERATION_LIMIT=200
```

## 5. Validate configuration without printing secrets

```powershell
cd C:\projects\betteroption
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

The report should show OpenAI, Brave, Exa, and Google Routes as `configured`,
SQLite, local authentication, no duplicate `.env` keys, and mobility privacy
`balanced` if Google should be used.

Test one explicit route without reading Compass or CV data:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_mobility.py `
  --origin "Frankfurt am Main" `
  --destination "Mülheim an der Ruhr" `
  --mode car
```

The configured provider order should begin with `google-routes` when the key and
`balanced` mode are effective. A provider error should be fixed before judging
match quality; it must not be worked around by exposing the key.

## 6. Run the complete release gate

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

This runs Ruff formatting/lint, the full test suite, and Python compilation. It
makes no paid provider call.

## 7. Start local-only

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open http://127.0.0.1:8000. Do not change the helper to `0.0.0.0`, add a router
port forward, or create a public tunnel for this local iteration. `Ctrl+C` stops
the application and its in-process background worker.

## 8. Product acceptance pass

Use small provider calls and verify in this order:

1. **Home/health:** `/health/ready` reports `0.7.1c-local-quality`, `sqlite`, and
   `ready`.
2. **Compass:** add or edit one preference. Confirm it persists after restart.
3. **Reference learning:** save a real reference job with learning enabled, at
   least one positive note, and one scope. The Review Tray must appear
   immediately. Matching changes only after confirmation. Negative notes must
   not become desired Explore terms or exclusions automatically.
4. **Explore:** run one Compass search. No Absolventa category/search result may
   appear. Brave is primary web discovery; Exa is conditional fallback.
5. **Archive/extraction:** save one reachable job and confirm evidence quotes and
   source state.
6. **Multi-location Match:** use a vacancy with two workplaces. Each travel mode
   must show the shortest confirmed workplace route; an unresolved alternative
   must not create a false hard commute blocker.
7. **Semantic regressions:** `international team` must not mean internship;
   building/equipment monitoring must not mean people surveillance; an actual
   internship or explicit video/person surveillance must still be recognized.
8. **Restart:** stop and restart, then confirm Compass, Archive, Explore snapshot,
   application state, and match history remain.

## 9. Commit only after local acceptance

The current private repository is the right long-term archive. Because this
iteration has not yet been pushed, first inspect the remote and changes:

```powershell
git remote -v
git status --short
git diff --stat
```

Then use the guarded helper, which stages only product paths, rejects tracked or
staged runtime secrets/private files, prompts before committing, and pushes to
the configured private remote:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1c-local-quality"
```

Do not commit `.env`, `local-data`, backups, CVs, databases, API keys,
certificates, or the built `dist` archive.

## 10. Later private-alpha path

No fork is required. When the local product is useful enough, keep this source
line and re-enable the existing controlled deployment path only after:

- account mode and invitation-only registration are retested;
- PostgreSQL migration/backup/restore and monitoring are proven;
- HTTPS/origin/proxy boundaries are restored;
- legal identity, privacy/terms/AI notice, provider contracts/transfers,
  retention, incident response, and processor review are truthfully completed;
- all external providers intended for testers are reviewed and configured;
- readiness flags represent evidence rather than a workaround.

Until then, local mode is the intended product boundary, not a reduced or
throwaway implementation.
