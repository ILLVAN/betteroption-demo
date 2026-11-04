> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.11c release notes

## Outcome

Matching and Explore are durable, resumable background workflows. The browser
returns immediately to a real progress page; refresh, navigation, and returning
through the corresponding navigation item all resolve to the same active task.
Repeated starts do not create duplicate work, interrupted runs recover, and
completed work redirects even when JavaScript has not polled yet.

## Included

- persisted queued, running, retrying, completed, and failed task states;
- database-backed phase, percentage, attempts, timestamps, and result link;
- startup recovery for tasks interrupted by a stopped process;
- idempotent Match retries through a shared task/workflow identifier;
- workspace-scoped progress page and JSON status endpoint;
- canonical `Match -> active task` resume behavior;
- canonical `Explore -> active task` resume behavior;
- durable workspace-owned Explore query and ranked-result snapshots;
- idempotent Explore recovery when paid discovery completed before task status
  could be committed;
- automatic restoration of the latest completed Explore results after navigation
  or application restart;
- no network-heavy discovery call inside the browser request lifecycle;
- no misleading “Continue browsing” control on the task page;
- server-side redirect for an already completed task;
- last-update and worker-health visibility on the progress page;
- worker-loop recovery instead of silently stranding a claimed task;
- completion-order progress reporting, so a slow first provider does not hide
  other route or company checks that have already finished;
- one conservative local worker suitable for SQLite private-alpha use;
- daily and per-workflow provider operation/cost ceilings;
- concurrency-safe in-process budget authorization;
- recent background activity and configured rails on `/operations`;
- migration `0011_background_tasks`;
- migration `0012_background_explore`;
- regression coverage for persistence, retry, recovery, privacy, budgets, and
  workspace-scoped status access.

## Preserved behavior

- the matching algorithm remains `matching-v0.6.10b`;
- Compass, Archive, Job Detail, evidence, mobility, application states, source
  validation, Explore discovery/ranking, and the 25-slot alpha allowance retain
  their prior contracts;
- existing databases migrate additively and no job needs to be re-imported;
- provider-operation and task metadata remain free of user payloads.

## Configuration

The defaults run a single local worker and allow two attempts. Optional settings:

```dotenv
BETTEROPTION_BACKGROUND_WORKER_ENABLED=true
BETTEROPTION_BACKGROUND_WORKER_POLL_SECONDS=0.5
BETTEROPTION_BACKGROUND_TASK_MAX_ATTEMPTS=2
BETTEROPTION_BACKGROUND_TASK_RETRY_SECONDS=2
BETTEROPTION_PROVIDER_ACTION_OPERATION_LIMIT=100
BETTEROPTION_PROVIDER_ACTION_COST_LIMIT_USD=0
```

A zero cost limit disables that monetary ceiling. Prices must be configured before
estimated-cost guards can represent real provider economics.

## Verification

The release gate is Ruff formatting, Ruff lint, bytecode compilation, the complete
pytest suite, and the profile-free release-package checks.

## Next

After v0.6.11c is accepted, v0.7.0 establishes accounts, authentication, tenant
isolation, secure sessions, data export, and complete account deletion before any
invited online deployment.
