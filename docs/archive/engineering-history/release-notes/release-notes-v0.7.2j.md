> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2j

`v0.7.2j` is the final local hardening release before the first clean
Netcup/Cloudflare private-alpha deployment. It builds on the locally accepted,
committed, pushed, and tagged `v0.7.2i`; neither `h` nor `i` was deployed to a
server. Local SQLite test data remains local and is not part of the deployment.

## Explore progress is visible again

- Explore task pages once again show a determinate `0–94%` progress estimate
  while independent external providers are running.
- The estimate is derived from the persisted task start time. Reloading a task
  page or opening it in another tab therefore does not reset the display to
  zero.
- The curve advances deliberately over nine minutes and slows near the end.
  It can never claim completion: only a durable successful task reaches `100%`.
- Stored phase, message, preview cards, lease state, errors, and terminal status
  remain authoritative. The percentage is presentation only and cannot turn a
  failed, stale, or cancelled task into a success.

## Abort is terminal and shutdown is bounded

- `Abort task` now makes queued, retrying, or running work terminal immediately
  and clears its claim fence in the same database transaction. A late worker can
  no longer commit a result after the user has cancelled.
- The embedded local worker is nudged immediately. The separate hosted worker
  detects the lost claim through its heartbeat and cooperative checkpoints.
- After submission the clickable button disappears. A short status sentence is
  rendered as text; `Cancelling…` is no longer presented as a disabled button.
- Explore source fan-out, availability checks, routing, company context, and
  matching waits poll task control at short intervals instead of sitting inside
  one long blocking wait.
- Explore snapshots, Match runs, imported corpus revisions/observations, access
  grants, source-snapshot cleanup and import-triggered follow-up work validate
  the active attempt and claim inside the same database transaction that stores
  their output. Cancel-before-commit saves nothing; a transaction completed
  before Cancel remains prior saved work.
- A provider call already incurred before cancellation remains durable failed
  Operations telemetry with its actual request count and estimated cost. Abort
  cannot be used to erase daily-budget usage.
- Abandonable provider calls use daemon I/O workers that are not registered in
  Python's interpreter-exit join registry. One `Ctrl+C` can therefore close the
  local Uvicorn process without waiting for a remote provider timeout and
  without the former `_python_exit` traceback.

An HTTP request already accepted by a provider cannot be physically withdrawn.
It may finish remotely or run until its configured timeout, but its abandoned
result is fenced from application state and cannot keep the local Python process
alive.

## Provider budgets survive cancellation, restart and two processes

- Every paid discovery, company, route and model call writes a conservative
  `Pending` reservation before outbound I/O. PostgreSQL serializes check plus
  insert across the web and worker containers; SQLite does the same for local
  policy instances.
- A process exit leaves the maximum reservation durable, so repeatedly stopping
  a worker cannot reset the daily or per-action allowance. Final telemetry
  conditionally updates the same UUID rather than inserting a second charge.
- An unresolved crash-surviving reservation is now counted and shown explicitly
  as `Pending` in Explore and Operations. It remains budget-visible, but is no
  longer included in the UI's `Reached`/successful-operation count.
- If cancellation wins after reservation but before outbound I/O, a cooperative
  post-commit check prevents the call and conditionally releases only that
  unused reservation. If usage is already incurred or unknowable, the actual or
  conservative maximum remains budget-visible.
- Profile, job, match-evidence and application OpenAI adapters authorize every
  real `responses.parse` attempt. A job evidence-correction retry is therefore
  a second operation. Salary remains exactly one outer operation: before its
  request, the batch reserves the combined maximum for Web Search calls plus
  conservative model input/output tokens; afterward the same UUID is finalized
  with the known tool-call and token costs. Unknown usage retains that combined
  maximum rather than being double-counted or silently released. The reviewed
  128,000-token Web Search context ceiling is a technical minimum and cannot be
  lowered by an unsafe environment override.

## Manual job details lead directly to one-job Matching

- An unmatched job created from pasted advertisement text now offers
  `Match this job only` directly on Job Detail.
- The action uses the existing durable, persona-bound single-job task. Access,
  active persona, Compass integrity, current job revision, and duplicate active
  task rules are checked server-side.
- A one-job run may create the first Match result for a Compass. If a current
  `matching-v0.7.2i` run exists, the newly added result is merged while all
  other stored results are kept; they are not reevaluated.
- A prior run from an older algorithm still requires complete Matching. Results
  from different algorithms are never silently mixed.
- Manual jobs without the optional source URL are associated through their
  stable current revision identity, so the supported URL-free paste path also
  reaches one-job Matching.

## Overrides are unmistakable and headers use them

- A private company-name override is now the effective employer label in the
  Job Detail hero and on Home, Archive, Matching, and Apply cards.
- The automatic employer name remains visible in its comparison column. Like
  every other overridden Job Detail comparison, that automatic side is grey
  and struck through while the private value is active.
- The same visual contract covers company relationship/context, employer types,
  reputation summary, salary, posting date, commute, work-mode facts, reasons,
  skills and application guidance. Labels, explanations, quotes, links and
  provenance remain readable and are not struck through. Restoring the
  automatic value removes the override treatment.
- These values remain persona-local private evidence. Changing the displayed
  employer name does not rewrite the extracted source advertisement.

## First private-alpha deployment

The server is intentionally a clean installation:

- fresh PostgreSQL and fresh server-only secrets;
- no local SQLite database, personas, jobs, CVs, uploads, `.env`, or backups;
- Ubuntu Server 24.04 LTS, SSH hardening, Docker Engine from Docker's official
  Ubuntu repository, and a
  read-only GitHub deploy key;
- one migration job, separate web and durable-worker containers, internal Caddy,
  and cloudflared with no published host web or database ports;
- Caddy and Uvicorn HTTP access logging disabled, plus Caddy's default runtime
  logger removes the complete request field so reverse-proxy errors cannot
  retain manual-source query URLs. Every Compose service size-rotates its
  remaining diagnostic log (`10 MB`, five files) instead of growing without a
  bound;
- a 20-second Compose stop grace for the worker's bounded ten-second
  cooperative lease release;
- Cloudflare Access deny-by-default for exact tester email addresses before the
  public hostname is routed through the Tunnel;
- first-owner bootstrap, immediate switch to `invite_only`, health/origin/task
  checks, and a real encrypted off-host backup/restore rehearsal.

Follow the
[step-by-step Netcup + Cloudflare runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2j.md).
The capacity and naming decisions remain unchanged from the
[v0.7.2i hosting note](../../discontinued-product-planning/hosting-and-public-roadmap-v0.7.2i.md) and
[v0.7.2i domain note](../../discontinued-product-planning/domain-name-decision-v0.7.2i.md).

The local handoff verifies the published SHA-256 before the ZIP is opened or
installed. The release builder, installer and Git push guard all reject runtime
environment files, the Cloudflare Tunnel token, databases, keys, CV/resume
artifacts and other private runtime paths; the builder also rejects symlinks.

## Release identity

- Application/source release: `0.7.2j`
- Python distribution: `0.7.2+j`
- Matching algorithm: `matching-v0.7.2i` (unchanged)
- Match-evidence prompt: `match-evidence-v0.7.2i` (unchanged)
- Archive: `betteroption_v0_7_2j.zip`
- Git tag: `v0.7.2j`
- Database migration head: `0033_background_task_leases` (unchanged)
- Privacy draft: `2026-08-05-feedback-draft` (unchanged)

Because the scoring and evidence-prompt contracts do not change, a current
`i` Match remains valid after upgrading to `j`; no release-forced full rematch
is required. The existing cost boundary also remains intact: Quickscore never
calls a discovery, research, route, or model provider.
