> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application architecture v0.6.11c

v0.6.11 adds a durable execution boundary around Matching and Explore without
changing either accepted algorithm or the user-owned aggregates they read.

## Background task aggregate

`background_tasks` stores an opaque task identifier, the current local workspace,
task kind, lifecycle state, phase, percentage, public status message, attempt and
retry counters, a local result path, a short failure class/message, and timestamps.
It deliberately stores no profile answer, search text, route endpoint, job or CV
content, source URL, prompt, model output, or API key.

The lifecycle is:

`queued -> running -> succeeded`

A temporary failure becomes `retry_wait` and can return to `running` until the
configured maximum attempt count is reached. A permanent or exhausted failure
becomes `failed`. A task observed as `running` during a new application startup is
returned to `queued`, because the prior process cannot still own it.

## Worker boundary

The local private alpha uses one daemon worker inside the FastAPI process. It
claims one persisted task at a time, which avoids uncontrolled concurrency against
SQLite and paid providers. The worker is started and stopped through FastAPI's
lifespan. Its handler receives a progress reporter and returns a local result URL.

This is not presented as the final hosted topology. The repository and handler
boundary permit a later PostgreSQL-backed worker process without changing the
web contract or user-visible task states.

## Idempotency and retries

The task UUID is also the Match workflow UUID. `ResultService` first checks for a
completed result with that workflow identifier. If a process failed after saving
the Match but before marking the task complete, retrying returns the saved result
instead of charging providers and creating another run.

Progress is persisted at preflight, routing, company-evidence, matching, saving,
and completion boundaries. The browser polls a workspace-scoped status endpoint;
refreshing the page never invents or resets progress.

Explore uses the same task lifecycle with a separate `explore_searches` aggregate.
That aggregate owns the workspace identifier, normalized query inputs, and ranked
public result snapshot. The generic `background_tasks` row therefore remains free
of user payloads. The discovery result is saved before the task is marked
successful; a retry after that boundary returns the saved result rather than
calling Brave, Exa, ATS feeds, or other discovery providers again.

## Provider budgets

The provider-operation ledger now enforces two independent scopes:

- daily operation and configured estimated-cost limits;
- per-workflow operation and configured estimated-cost limits.

Authorization is serialized in-process so concurrent provider calls cannot all
pass the same stale ledger snapshot. Automatic retries keep the same workflow
identifier and therefore cannot reset the action allowance. A denied optional
provider degrades through its existing fallback contract and records the budget
decision without fabricating evidence.

## Web contract

`POST /matches/run` creates or reuses the active Match task and redirects to
`/tasks/{id}`. `GET /matches` performs the same active-task lookup, so leaving and
returning cannot hide an in-flight run behind a second Run button.
`POST /explore/search` does the same for Explore, while `GET /explore` resumes an
active task or renders the latest completed durable snapshot. A previous GET-style
search URL is accepted for compatibility and deduplicated against that snapshot.
`/tasks/{id}/status` exposes only public lifecycle metadata for the active
workspace. Completed tasks redirect to Matching both server-side and through the
poller, or to Explore for discovery work. The operator page shows recent task
state and configured rails alongside the privacy-safe provider ledger.

The worker loop catches repository-level failures that previously could terminate
the only worker thread after it had claimed a task. It returns interrupted work to
the durable queue and continues polling. Handler failures retain the bounded
retry-or-fail behavior.

When the background worker is explicitly disabled, the route retains a synchronous
fallback for diagnostics and isolated web tests.

## Next boundary

v0.7.0 adds accounts, secure sessions, tenant ownership, authorization, export,
and complete deletion. Every background task and provider operation must be owned
and queried through the authenticated tenant boundary before invited online use.
