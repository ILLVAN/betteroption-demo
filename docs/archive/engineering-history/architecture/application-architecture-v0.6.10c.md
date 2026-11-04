> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.10c

v0.6.10c adds workflow correlation and per-Match operational KPIs to the
existing provider ledger. It does not change the accepted matching algorithm.

## Opaque workflow correlation

`provider_operation_scope` carries an opaque workflow UUID and a coarse
workflow type through synchronous and bounded worker-thread calls. Provider
recorders persist those identifiers with operational metadata only. Search
phrases, locations, route endpoints, URLs, prompts, CV/job text, model output,
and API keys remain outside the ledger.

The Match run UUID is also the workflow UUID. This provides a stable join
between one immutable result run and its provider-operation envelopes without
creating a second mapping table or copying private payloads into telemetry.

## Match-run metrics

The result repository records an additive metrics snapshot after the immutable
run and free-result grants are saved:

- total verified jobs evaluated and exact-route jobs;
- included slots and Top/Stretch/Blocked counts;
- correlated provider calls, results, failures, and priced calls;
- end-to-end latency and configured estimated cost.

Older match runs remain valid and simply have no metrics snapshot. The operator
page lists only runs with measured snapshots.

## Provider attribution and pricing

Discovery and company-research adapters are recorded at their actual provider
boundary. Brave and Exa no longer disappear behind a generic mesh label. Each
provider can have a separate operator-configured per-call estimate.

An absent estimate is not zero-cost evidence. The control room displays the
known subtotal plus “unpriced” whenever at least one correlated operation lacks
a configured estimate. Provider invoices remain authoritative.

## Product-card boundary

Application state and complete deletion remain distinct operations in card
footers. State updates are reversible and append to interaction history;
deletion is permanent and uses the existing modal confirmation. The same
controls are available in Matching and Archive without changing Job Detail.

## Next architectural step

v0.6.11 moves slow provider work behind persistent background tasks. The
workflow and run identifiers introduced here become the correlation boundary
for real progress, retry limits, idempotency, and per-action budgets.
