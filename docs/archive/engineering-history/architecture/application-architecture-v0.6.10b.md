> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.10b

## One interaction state, three views

Job Detail, Archive, and Matching now project the same `JobInteraction` row.
Overview dropdowns call a narrow application endpoint; `ResultRepository` keeps
the current state and appends an application event exactly as the detail-page
workflow already did.

```text
Archive card ──┐
Matching card ─┼─ POST /jobs/{record}/application-state
Job Detail ────┘                 │
                                 └─ ResultRepository
                                    ├─ job_interactions (current state)
                                    └─ interaction_events (append-only history)
```

No interaction state is copied into the job source revision. Deleting the job
through the existing aggregate deletion path removes its interaction and history
through database cascade behavior.

## Read-only operational projection

`ProviderOperationLedger.breakdown_since()` groups sanitized rows by provider
and purpose. The web control room is a projection only. It cannot mutate limits
or reveal secret configuration.

The guard remains process-local and race-tolerant for the private alpha.
Persisted background-task reservations, retries, and provider-specific budgets
remain v0.6.11 work.

## Compass consistency boundary

The pre-match check now considers commute limits and origins. It accepts
different precision levels and relies on generic offline place/postcode indexes;
it does not hardcode a city or district. Exact routing still belongs to the
provider chain and is not performed by the consistency checker.

The next 0.6.10 increment can build the cross-source evidence graph on top of
these observable provider and interaction boundaries without mixing telemetry,
candidate data, or source evidence.
