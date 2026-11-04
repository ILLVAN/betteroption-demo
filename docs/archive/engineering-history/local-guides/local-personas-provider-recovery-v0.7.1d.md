> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Local personas and provider recovery for v0.7.1d

This runbook restores the complete BetterOption application as a local job-search
tool. It supports several isolated, password-protected personas on one Windows
computer while preserving the existing database and a later go-live path.

It does not require or start Netcup, Cloudflare, DNS, Docker, PostgreSQL, a
domain, or a public listener. The supported address is
`http://127.0.0.1:8000` only.

Release identity:

- application: `0.7.1d-local-personas`
- package: `0.7.1+d.local.personas`
- archive: `betteroption_v0_7_1d_local_personas.zip`

## 1. Preserve the existing local state

The first local persona can adopt the existing unowned single-user workspace,
so a new database is not required. Before installing an overlay, make a private,
recoverable copy if the files exist:

```powershell
cd C:\projects\betteroption
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force .\local-backups | Out-Null

if (Test-Path .\local-data\betteroption.db) {
  Copy-Item .\local-data\betteroption.db ".\local-backups\betteroption-$stamp.db"
}
if (Test-Path .\.env) {
  Copy-Item .\.env ".\local-backups\env-$stamp.txt"
}
```

`local-backups`, `.env`, and `local-data` contain secrets or personal data. Keep
them outside Git and release ZIPs. The installer preserves them.

For a deliberate fresh start, omit the old database. Application startup creates
`local-data/betteroption.db` and applies the current migrations.

## 2. Install the exact release

Old `b`, `b-legal`, `c`, and `d` ZIPs may coexist. Do not rely on the most recent
download timestamp:

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1d_local_personas.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1d-local-personas"

.\.venv\Scripts\python.exe -c "import betteroption; print(betteroption.__version__)"
```

Expected output:

```text
0.7.1d-local-personas
```

The installer overlays product files, creates `.venv` if necessary, reinstalls
the editable package, preserves runtime data, and removes only the exact known
superseded tests. It deliberately does not run the full test suite.

If this is a clean extracted folder rather than an existing project tree, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bootstrap_local.ps1
```

## 3. Set the local-persona boundary

Create `.env` from the example only when no real file exists:

```powershell
if (-not (Test-Path .\.env)) {
  Copy-Item .\.env.example .\.env
}
notepad .env
```

Keep these values exactly for this iteration:

```dotenv
BETTEROPTION_DATABASE_URL=sqlite:///local-data/betteroption.db
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_PUBLIC_BASE_URL=
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_LOCAL_PERSONAS_ENABLED=true
BETTEROPTION_REGISTRATION_MODE=disabled
BETTEROPTION_AUTH_SESSION_DAYS=30
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000
```

Do not use `BETTEROPTION_AUTH_MODE=local` with personas. Do not use
`BETTEROPTION_REGISTRATION_MODE=open` or `invite_only` for this workflow.
Settings reject local personas outside the local, accounts, loopback boundary.

The local session still benefits from a stable rate-limit secret. Generate one
and place it only in `.env`:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToHexString($bytes).ToLowerInvariant()
```

```dotenv
BETTEROPTION_AUTH_RATE_LIMIT_SECRET=replace-with-the-generated-value
```

## 4. Recreate provider credentials

Create separate local-development credentials, apply the provider's narrowest
use/API restrictions, and set small quota or budget alerts where available.
Never paste keys into chat, Git, screenshots, source files, or client-side code.

Add only the providers you intend to exercise:

```dotenv
OPENAI_API_KEY=replace-with-a-new-project-key
OPENAI_MODEL=gpt-5.6-luna

BRAVE_SEARCH_API_KEY=replace-with-a-brave-search-plan-key
# BRAVE_ANSWERS_API_KEY is intentionally unsupported and unused.

EXA_API_KEY=replace-with-a-new-exa-key
BETTEROPTION_EXA_FALLBACK_MIN_RESULTS=30

GOOGLE_ROUTES_API_KEY=replace-with-a-new-routes-key
BETTEROPTION_MOBILITY_PROVIDER=auto
BETTEROPTION_MOBILITY_PRIVACY_MODE=balanced
```

Important distinctions:

- BetterOption calls Brave **Web Search**. Create a key under an active Brave
  Search plan and put it in `BRAVE_SEARCH_API_KEY`.
- Brave Answers is a separate product. `BRAVE_ANSWERS_API_KEY` is never consumed
  by BetterOption, and an Answers-only key cannot authorize Explore.
- Exa remains a conditional fallback when the primary source mesh provides too
  little coverage; it need not appear in every Explore run.
- Google Routes is used first in `balanced` mobility mode when its key is valid.
  `privacy_first` deliberately avoids Google even when the key exists.
- Transitous, Valhalla, Nominatim, Arbeitnow, and configured public ATS boards do
  not use these four paid keys, but they still disclose the limited request data
  described in the privacy drafts and remain best-effort public services.

Numeric cost settings must contain a real number or explicit `0`; blank values
are invalid. Zero means unknown/unpriced, not free:

```dotenv
BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD=0
BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD=0
BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD=0
```

Keep the operation-count rails enabled even while cost estimates are zero.

## 5. Diagnose configuration without exposing keys

First inspect the effective settings and duplicate `.env` assignments:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

The report names configured providers but never prints their credential values.
It must show authentication `accounts`, registration `disabled`, SQLite, and no
duplicate assignments. It reports Brave Search separately from the unused Brave
Answers variable.

Check OpenAI authentication and configured-model access without sending user
text:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_openai.py
```

The diagnostic retrieves model metadata only. A successful result explicitly
says that no Compass or CV text was sent. If it fails, correct the key, project,
model access, quota, billing, or network issue before relying on structured
extraction; do not expose the key while troubleshooting.

When Brave returns no cards, distinguish key/product failure from normal
filtering with one fixed Search endpoint probe:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
```

Test routing independently from Compass/CV state:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_mobility.py `
  --origin "Frankfurt am Main" `
  --destination "Mülheim an der Ruhr" `
  --mode car
```

Repeat with `transit`, `bicycle`, and `walk` for the modes you need.

## 6. Run the hermetic release gate

Run the complete checks with the normal `.env` in place:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

The v0.7.1d tests are isolated from runtime provider credentials and make no paid
provider call. The gate checks Ruff formatting/lint, the complete test suite, and
Python compilation. It also removes only the exact obsolete overlay tests
`tests\test_v070a1.py` and `tests\test_v071a.py` before validation.

## 7. Start loopback-only

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000/personas`. Keep the PowerShell window open; press
`Ctrl+C` to stop the application and its in-process background worker.

Do not change the host to `0.0.0.0`, create a router port forward, or publish the
process through a tunnel. Forwarded or Cloudflare IP headers do not grant access
to the persona chooser, but they are not a reason to expose a development server.

## 8. Create the first persona and adopt legacy data

On `/personas`:

1. Create the first named persona with a unique name and a password of at least
   ten characters.
2. The app signs into that persona immediately.
3. If the database contains an unowned legacy single-user workspace, this first
   creation adopts it transactionally, including the saved-job grants needed to
   open its Archive and match data.
4. Open **Home → Compass → Explore → Match → Archive** and verify that the
   previous local data is present.

The adoption happens only once. Do not create a disposable first persona when
you intend a particular person to own the legacy workspace.

For a fresh database, the first persona simply starts an empty isolated
workspace; there is no `first_user` email-registration step.

## 9. Verify a second isolated persona

Return through **Switch persona** or `/personas`, then create a second named
persona. Creating it signs out the previous session and opens the new one.

Verify:

1. The second persona does not see the first persona's Compass, Archive, matches,
   application state, or background-task URLs.
2. Switching back requires the first persona's password; a wrong password does
   not replace the current session.
3. Names that differ only by capitalization cannot both be created.
4. Signing out returns to the persona chooser, where either persona remains
   available after a browser or application restart.

These are normal stored accounts with synthetic internal local-only email
identifiers. The UI does not expose those identifiers.

## 10. Verify Compass and CV recovery behavior

### Compass

Add a direct Compass answer with the valid OpenAI configuration and confirm its
structured facts appear. Then, if you deliberately test a missing or invalid key:

1. Keep the app loopback-only and temporarily remove or replace only the local
   `OPENAI_API_KEY` value.
2. Add a clearly recognizable direct Compass sentence.
3. Confirm the page reports a secret-safe provider problem rather than a server
   error.
4. Confirm the exact input remains locally checkpointed as an active, editable
   statement.
5. Restore the valid key and rerun `scripts\diagnose_openai.py`.

The local checkpoint occurs before the provider call. If local persistence fails,
the provider is not called. The direct editable fallback is not a claim that AI
structuring succeeded; edit or reclassify it normally in Compass.

### CV

Upload a TXT, DOCX, or text-based PDF only after reviewing the on-screen data
notice. The original binary remains transient. The expected flow is:

1. Local parsing and identifier/sensitive-category screening.
2. An editable minimised preview.
3. If the local scanner removes more data, a second review of that exact text.
4. One provider extraction only after the required confirmations.
5. Proposed facts in the Review Tray, inactive until individually confirmed.

Windows `CRLF` textarea line endings no longer make unchanged preview text look
different from server `LF`. Labeled inline personal URLs such as
`Artist Web: corecut.net` are removed, while a technology reference such as
`socket.io` is retained when it is not labeled as personal contact information.

Unlike direct Compass input, CV provider failure remains fail-closed: the whole
CV selection is not promoted to a confirmed statement.

## 11. Verify Explore provider contribution

Run one **Search with Compass** and inspect **What the last source run
contributed** above the result cards.

The panel uses metadata only. It shows whether each attempted source was reached,
partly reached, failed, or blocked by the safety budget; how many usable
candidates it returned; and how many appear in the final ranking. It never shows
or stores the search query, candidate URLs, raw responses, or keys.

A reached source with zero final cards can be correct: its candidates may fail
source policy, duplicate a stronger source, or fall outside the bounded final
ranking. Use provider-specific failure guidance or the Brave Search probe only
when the panel reports failure, rather than treating every zero as a bad key.

Also verify the retained `v0.7.1c-local-quality` behavior: no Absolventa
search/category page, nearby regional results, conditional Exa fallback,
immediate but inactive reference-job learning suggestions, corrected matching
semantics, and the shortest confirmed route for each mode on multi-location jobs.

## 12. Publish the accepted source to private GitHub

The private repository remains the source-history archive. The ZIP is an
immutable recovery checkpoint, not a substitute for Git. Use the full
[private GitHub release cycle](../release-process/github-release-cycle-v0.7.1d.md), especially its
step that preserves and tags the preceding `v0.7.1c-local-quality` commit first
if that has not happened yet.

After all local acceptance checks pass:

```powershell
cd C:\projects\betteroption
git status --short
git diff --stat

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\push_release.ps1 `
  -CommitMessage "Release BetterOption v0.7.1d-local-personas"

git tag -a v0.7.1d-local-personas -m "BetterOption v0.7.1d local personas"
git push origin v0.7.1d-local-personas

git log -2 --oneline
git status --short
git ls-files .env local-data local-backups dist
```

The last command must print nothing. Never commit `.env`, `local-data`,
`local-backups`, CVs, databases, API keys, certificates, or `dist`.

## 13. Keep the future go-live path dormant

Do not use the Netcup/Cloudflare deployment scripts for this iteration. Do not
enable invitation creation or treat draft legal readiness flags as complete.

A later go-live remains possible from the same source tree, but it is a separate
release and acceptance decision. It must disable local personas and revalidate
HTTPS/origin restrictions, account onboarding, tenant isolation, provider
contracts and transfers, legal notices, retention/deletion, incident handling,
monitoring, encrypted off-server backups, restore evidence, and rollback.

Until that work is deliberately resumed, the product is the loopback-only local
tool described here.
