> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2i

`v0.7.2i` is the first release intended for the clean Netcup private-alpha
deployment. It builds directly on the locally installed and pushed `v0.7.2h`
source. The `h` server state does not exist and no local SQLite data is part of
the deployment.

## Posting dates stay with their vacancy

- Explore identities now remove only known tracking parameters. Meaningful
  query values such as `vacancyId` remain part of the identity, so two vacancies
  behind the same path can no longer collapse into one dated row.
- Duplicate selection prefers richer vacancy evidence instead of preferring the
  row that happens to contain a date. A missing date is copied only when the
  normalized URL, title, and employer prove that both rows describe the same
  vacancy.
- Every result card owns its source URL and labelled `<time>` element. `Posted`
  evidence sits with the card metadata while the footer contains only the
  source-inspection action, including at narrow responsive breakpoints.
- Structured `datePosted`, `first_published`, and equivalent creation fields are
  retained. A Greenhouse `updated_at`, You.com `page_age`, or generic page date
  is no longer presented as a fresh posting date.
- The conservative posting-date parser also understands labelled French,
  Dutch, Spanish, and Italian dates and common relative badges. Missing or
  ambiguous values remain explicitly unknown rather than being guessed.

## A complete manual-source rescue path

- A background import records the exact Explore snapshot that started it.
  Manual-readiness and expired-source updates are applied only to that owned
  snapshot, never to whichever search happened to finish most recently.
- `Needs pasted text` is an action. It opens Add with the safe public URL
  already filled, the manual text area visible, and a small `Inspect source`
  link for copying the public advertisement.
- Only credential-free HTTP(S) URLs may be prefilled. Reasons are fixed
  server-side and untrusted query text is never reflected.
- A single manually recoverable failure goes directly to its prefilled Add
  page. Multiple failures stay in Explore so every affected card keeps its own
  rescue action; expired vacancies are removed and are never offered for paste.

Migration `0032_explore_import_origin` adds the durable source-snapshot link.

## Ratings are emotional score inputs, not Compass boundaries

- Job and employer ratings remain persona-local, server-side Compatibility
  inputs. Neither rating is read by the Compass-integrity report or any Compass
  action gate.
- A zero-star rating can reduce Compatibility to zero, but it no longer labels
  a job `Blocked by a boundary`. Only supported job/Compass evidence can create
  that disposition.
- Rating fingerprints are separated from corrected private evidence. Rating or
  rating removal therefore never unlocks an expensive Full Match as if the
  Compass or source evidence had changed.
- Quickscore now returns an explicit projection state. `no_latest_match`,
  `old_algorithm`, and `job_missing` tell the user that the rating is safely
  stored and when a complete Match is needed; they are no longer silent layout
  successes.
- Local projections use conditional replacement and bounded reload/recompute
  attempts. A concurrent rating update or full Match cannot silently overwrite
  the later confirmed rating, and Quickscore never calls a discovery, research,
  route, or model provider.

## Background work can be stopped and survives web restarts

- Migration `0033_background_task_leases` adds claim owner/token, heartbeat,
  lease expiry, and cancellation timestamps to durable tasks.
- A worker claims with a fence, renews its lease independently of progress, and
  mutates task state only while it still owns that claim. Startup recovery
  touches expired leases only; a second process cannot requeue a healthy task.
- `Abort task` is owner- and persona-scoped and idempotent. Queued work is
  cancelled immediately. Running work stops cooperatively after the current
  bounded network step and cannot begin another provider stage.
- The browser no longer invents progress up to 94%. Running progress is shown
  only with a fresh lease; queued, cancelling, cancelled, and stale work use the
  durable server state and honest copy.
- Local SQLite keeps one embedded worker. Private-alpha Compose runs one
  dedicated worker service while the web service only enqueues. Restarting the
  browser or web container therefore does not stop a healthy server task.
  Stopping the entire machine cannot make work execute while it is off; an
  interrupted claim is recovered after its lease expires on restart.

The queue remains intentionally at-least-once. A hard process loss can repeat an
external call, so provider request and monetary caps remain part of the safety
boundary.

## All Jobs cost is cut at the provider boundary

- `BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=20` replaces the former
  default of 60.
- `BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=120` bounds dataset readback and local
  presentation, down from 300.
- `BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0.40` is the actual
  per-run pay-per-event charge ceiling, and the internal ledger reserves the
  same `0.40` worst-case amount.
- Actor polling remains reliable. Poll requests are control-plane checks, not
  additional paid actor searches. EURES, JobsPipe, JSearch, and every other
  provider keep their existing limits.

At the supplied free-tier event price, the monetary cap and per-platform limit
target roughly the requested 50–70% reduction without arbitrarily removing a
platform before real alpha measurements exist.

## First private-alpha deployment

- The server starts with a fresh PostgreSQL volume. Local personas, jobs,
  ratings, documents, SQLite databases, `.env`, uploads, and test history are
  not copied.
- Migration `0031` now widens PostgreSQL's default 32-character Alembic revision
  column before writing its 33-character identifier. This closes a blocker that
  SQLite could not reveal and lets the clean server reach `0032` and `0033`.
- Netcup VPS 1000 G12 is the capacity recommendation. VPS 500 is an owner-only
  minimum; VPS 2000 is an evidence-based upgrade. VPS 4000/8000 and AWS do not
  remove the dominant external-provider latency in this architecture.
- App, worker, PostgreSQL, Caddy, and cloudflared publish no host web/database
  port. Cloudflare Access must be deny-by-default for exact tester emails before
  the Tunnel route is created.
- The runbook includes Debian/SSH hardening, official Docker installation,
  immutable source staging, fresh secret generation, one-shot migration,
  first-owner bootstrap, `invite_only` closure, task/web-restart acceptance,
  origin-negative tests, encrypted off-host backup, and an isolated timed
  restore drill.

See the
[executable Netcup + Cloudflare runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2i.md)
and [hosting decision](../../discontinued-product-planning/hosting-and-public-roadmap-v0.7.2i.md).

## Naming decision

There is no rename. The current top six are `betteroption.example`,
`suiting.work`, `chilled.work`, `lifelife.work`, `balancedwork.life`, and
`movingon.work`. `chilled.work` is the only new low-cost blind-test candidate;
it is not a release identity. None of the seven €199/year `.jobs` candidates is
recommended because of cost, product narrowing, ambiguity, or direct recruitment
collisions. `suiting.life` remains weaker than `suiting.work`.

See the [complete decision and supplied cost projections](../../discontinued-product-planning/domain-name-decision-v0.7.2i.md).

## Release identity and migration

- Application/source release: `0.7.2i`
- Python distribution: `0.7.2+i`
- Matching algorithm: `matching-v0.7.2i`
- Match-evidence prompt: `match-evidence-v0.7.2i`
- Archive: `betteroption_v0_7_2i.zip`
- Git tag: `v0.7.2i`
- Database migration head: `0033_background_task_leases`
- Privacy draft: `2026-08-05-feedback-draft`

Both migrations are additive. Existing local runtime data remains compatible,
but an `h` Match needs one complete `i` Match before Quickscore can project into
the new algorithm. The clean server has no legacy data to migrate beyond
creating the current schema.
