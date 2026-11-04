> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# JobsPipe via Apify source review — v0.7.2a

Status: local evaluation only · 4 August 2026

This is the current review record for the new JobsPipe discovery path. It does
not rewrite the historical [v0.7.1r source review](job-source-review-v0.7.1r.md)
for EURES, JSearch and mobility providers.

## Reviewed technical contract

- Actor: [`jobspipe/jobspipe-job-search`](https://apify.com/jobspipe/jobspipe-job-search)
- Published API schema: [Apify actor OpenAPI page](https://apify.com/jobspipe/jobspipe-job-search/api/openapi)
- BetterOption endpoint: the actor-specific synchronous dataset endpoint
  `jobspipe~jobspipe-job-search/run-sync-get-dataset-items`
- Input fields: up to eight bounded role/title alternatives, zero or one
  offline-resolved ISO country code, the remote-only flag and a maximum result
  count; no raw city/postcode is sent after successful local resolution
- BetterOption limit: default 150, hard maximum 180
- Operation shape: one actor run and one returned dataset page per Explore
  invocation within that bound; the actor currently documents up to 500 items
  per page
- Identity: provider `apify-jobspipe`, label `JobsPipe via Apify`, Account
  permission `jobspipe`; none of these identifiers is shared with EURES

Malformed rows, non-HTTP result links and unsupported response shapes fail
closed. Returned vacancies remain untrusted public evidence until the candidate
checks the source or application link. A numeric salary value of zero is treated
as unknown rather than as a real `USD 0` statement.

## Recipient and data boundary

The recipient chain is broader than EURES even when both actors use the same
local `APIFY_API_TOKEN`: Apify runs the actor, while the JobsPipe-published actor
and its upstream JobsPipe service/source chain provide the vacancy corpus. Apify
and JobsPipe therefore require separate recipient, processor/controller,
subprocessor and transfer analysis.

BetterOption does not send JobsPipe an account identifier, persona name, home
address, CV, full Compass, salary target, private employer rating, saved jobs or
application history. The adapter sends only the bounded fields listed above.
Provider telemetry records purpose, status, units and an operator-supplied cost
estimate, never the search terms, location, response body or token.

## Consent and activation boundary

- The new Account permission defaults to **off**. A previously configured Apify
  token and an existing EURES choice do not silently authorize JobsPipe.
- Local evaluation requires the account owner to enable **JobsPipe via Apify**
  explicitly in Provider choices.
- Hosted/staging construction remains fail-closed until the existing processor
  review gate is deliberately enabled after completing this source review.
- Disabling JobsPipe does not disable EURES, and disabling EURES does not
  disable JobsPipe.

## Cost interpretation

The actor page currently publishes a per-request price, but provider pricing can
change. BetterOption therefore uses the operator-controlled
`BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD` value for ledger
estimates. Its default `0` means **unpriced**, never free. Before any hosted
test, the operator must verify the current actor/account price and set the local
estimate accordingly.

## Open decisions before external alpha

The following evidence is still required before JobsPipe can be approved for
external users:

- executed DPA/terms and a documented controller/processor role analysis for
  Apify, the actor publisher, JobsPipe and any subprocessors;
- international-transfer location and safeguard review;
- exact actor dataset retention, deletion, logging and incident/security
  controls, including deletion after failed and successful runs;
- current upstream source list plus each source's collection, reuse,
  redistribution, attribution and removal terms;
- freshness, expiry, deduplication, provenance and application-link quality
  sampling against the existing structured sources;
- a lawful-basis, transparency and recipient-notice update for the real
  deployment, followed by an updated RoPA/DPIA decision where applicable;
- a measured cost, latency, timeout and provider-failure baseline with the
  bounded one-run policy; and
- a documented disable/rollback procedure that preserves EURES and all other
  providers.

Until these items are signed off, JobsPipe is an inspectable local discovery
experiment, not an approved private-alpha dependency.
