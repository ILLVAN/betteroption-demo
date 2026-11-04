> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1d-local-personas

`v0.7.1d-local-personas` advances the localhost revival without opening a
server or a private alpha. It keeps the complete application and the later
account/deployment foundations in one source line, but its supported operating
boundary is a password-protected, loopback-only tool on the user's own Windows
computer.

Application version: `0.7.1d-local-personas`  
Python package version: `0.7.1+d.local.personas`  
Release archive: `betteroption_v0_7_1d_local_personas.zip`  
Database head: `0017_invitation_onboarding` (unchanged)

The preceding `v0.7.1c-local-quality` release remains the historical quality
checkpoint for Explore filtering, reference-job learning, matching semantics,
and multi-location routing. This release includes those corrections and adds a
safer local identity and provider-recovery layer.

## Local personas

- Local use now runs through the existing account, session, and tenant-isolation
  boundary instead of a shared anonymous workspace.
- `/personas` can create and switch named, password-protected personas. Each
  persona has its own Compass, Archive, Explore state, match results, and
  application history.
- Persona names are unique case-insensitively; switching requires the selected
  persona's password and revokes the previous session.
- The first persona transactionally adopts any existing unowned single-user
  workspace and saved-job access. This preserves an existing local database
  without copying its data into every later persona.
- Later personas start with their own isolated workspace. They cannot view the
  first persona's profile, saved jobs, match history, or task URLs.
- Local persona routes use the actual network peer. Forwarded, real-IP, and
  Cloudflare headers cannot make a remote request look local.

The feature is accepted only with this boundary:

```dotenv
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_LOCAL_PERSONAS_ENABLED=true
BETTEROPTION_REGISTRATION_MODE=disabled
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000
```

Settings reject local personas in staging or production, in legacy local-auth
mode, or on a non-loopback host such as `0.0.0.0`. The supplied run helper also
binds Uvicorn directly to `127.0.0.1:8000`.

## Compass provider resilience

- A direct Compass answer is checkpointed in the local database before any
  OpenAI call begins. If that checkpoint fails, no provider request is made.
- Missing, invalid, inaccessible, or otherwise unavailable OpenAI configuration
  no longer discards a direct answer or produces a generic server error. The
  user's original wording is kept as an active, visible, editable Compass
  statement, and the page gives secret-safe recovery guidance.
- Provider errors never echo an API key or raw internal exception into the
  browser.
- `scripts\diagnose_openai.py` verifies authentication and access to the
  configured profile model by retrieving model metadata. It sends no Compass or
  CV text and does not print the key.

The editable direct-statement fallback is intentionally limited to explicit
Compass input. CV extraction remains fail-closed: provider failure does not turn
an entire CV preview into confirmed profile facts.

## CV confirmation and minimisation

- The second CV confirmation now treats browser `CRLF` and server `LF` line
  endings as the same reviewed text. A Windows textarea therefore reaches the
  provider once after the required sanitisation review instead of repeatedly
  returning to the confirmation page.
- The local minimiser removes labeled bare personal URLs even when they appear
  inline, for example `Artist Web: corecut.net`, `Portfolio: example.dev`, or
  `Personal website: example.net`.
- Technology names that merely resemble domains, such as `socket.io`, remain
  available as skills/evidence when they are not presented as personal contact
  fields.
- The original CV binary is still not retained. Only the user-reviewed,
  minimised selection can be sent after the two explicit confirmation checks.

## Provider diagnostics and Explore transparency

- BetterOption uses `BRAVE_SEARCH_API_KEY` with Brave's Web Search product.
  `BRAVE_ANSWERS_API_KEY` is unsupported and unused; an Answers-only key cannot
  power Explore.
- The configuration report distinguishes the two Brave products without
  revealing either credential. Its optional fixed Search probe remains
  available through `scripts\diagnose_config.py --probe-brave-search`.
- Explore now shows a secret-safe contribution panel for the last source run.
  For each reached, partly reached, failed, or budget-blocked provider, it shows
  returned usable candidates and how many remain in the final ranking.
- A provider can validly contribute zero final cards after source-policy
  filtering, deduplication, or bounded ranking. The panel makes that different
  from authentication or transport failure without storing or displaying
  queries, URLs, responses, or keys.

## Release-test hygiene

- The v0.7.1d test process is hermetic with respect to the developer's real
  `.env`; provider credentials cannot silently alter test behavior or trigger a
  paid request.
- Overlay installation and the release gate remove the exact known superseded
  tests `tests/test_v070a1.py` and `tests/test_v071a.py`. They do not broadly
  delete tests or touch current account, persona, security, or isolation tests.
- Local persona coverage includes first-persona legacy adoption, password
  switching, case-insensitive uniqueness, cross-persona isolation, remote-peer
  rejection, and rejection of unsafe configuration.
- Compass/CV coverage exercises missing and invalid keys, local checkpoint
  failure, secret-safe diagnostics, CRLF confirmation, and labeled personal URL
  minimisation.

## Install and operate

Use the exact archive and verify the application version:

```powershell
cd C:\projects\betteroption
$release = "$HOME\Downloads\betteroption_v0_7_1d_local_personas.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1 `
  -ArchivePath $release `
  -ExpectedVersion "0.7.1d-local-personas"

.\.venv\Scripts\python.exe scripts\diagnose_config.py

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Open `http://127.0.0.1:8000/personas`. See
[Local personas and provider recovery](../local-guides/local-personas-provider-recovery-v0.7.1d.md)
for the exact data, key, diagnostic, acceptance, and troubleshooting path.

After local acceptance, preserve the release in the existing private repository
using [the v0.7.1d GitHub release cycle](../release-process/github-release-cycle-v0.7.1d.md). That
guide also preserves `v0.7.1c-local-quality` as the earlier tagged checkpoint.

## Explicit non-goals

This release does not deploy Netcup, Cloudflare, Docker, PostgreSQL, DNS, HTTPS,
monitoring, online backups, public registration, invitations, or a private
alpha. It does not assert that draft legal pages, processor reviews, a DPIA,
incident procedures, or backup/restore evidence are complete.

Do not bind the local helper to `0.0.0.0`, publish it through a router or tunnel,
or reuse local-persona mode on a server. A later go-live must deliberately turn
off local personas and revalidate the existing deployment, legal, security,
retention, processor, monitoring, backup, and invitation boundaries.
