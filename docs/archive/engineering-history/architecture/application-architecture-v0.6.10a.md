> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.10a

## New operational boundary

`ProviderOperationLedger` is an append-only, fail-open adapter beside the
existing model-invocation ledger. Provider work emits metadata only after the
domain operation is selected; business logic never reads user payloads back
from this ledger.

```text
Web action
  ├─ discovery source mesh ─┐
  ├─ company research ─────┼─ ProviderOperationLedger ─ provider_operations
  ├─ route provider call ──┤
  └─ LLM invocation ───────┘
             │
             └─ ProviderBudgetPolicy (daily local-alpha guard)
```

The operation row deliberately has no workspace identifier before tenant
isolation exists. Adding an implicit local workspace now would create a false
security boundary. v0.7.0 adds an explicit tenant key to every user-owned row
and operation.

## Budget behavior

- A source-mesh search that exceeds the configured guard returns a clear
  discovery error.
- Optional company research degrades to no extra evidence.
- A blocked route provider remains unavailable and allows the existing fallback
  chain to continue.
- Model invocation accounting mirrors already-sanitized token metadata. A
  provider-specific model budget and reservation belongs to background tasks in
  v0.6.11.

The policy is race-tolerant for the single-process private alpha. It is not a
distributed billing or entitlement system.

## Next evidence increment

v0.6.10b introduces a cross-source evidence graph and separate quality
dimensions for role, capability, seniority, work model, mobility, compensation,
employer relationship, product category, and reputation. Advertisement silence
remains Unknown, and every inference retains its source and confidence.
