> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# Cost control and business-plan checkpoint

Status: working plan for the post-`v0.7.2k` checkpoint · 5 August 2026

This document turns the next product decision into a measurable gate. It is not
a forecast built from invented prices. Provider dashboards and invoices remain
authoritative, and every zero cost in BetterOption means **unpriced**, not free.
The infrastructure, administrator, vendor-ownership, mail and exposure gates
are defined in
[`hosting-and-public-roadmap-v0.7.2i.md`](hosting-and-public-roadmap-v0.7.2i.md);
this document owns measurement, plan limits and unit economics.

## Decision to make before inviting testers

Before the first friend receives an invitation, the operator must be able to
answer four questions with observed data:

1. What does one complete Explore → Match workflow cost at the median and at
   the expensive 90th percentile?
2. Which providers add unique, relevant first-page jobs after deduplication,
   rather than merely returning many rows?
3. Which provider bundle is affordable for free closed-alpha use and for each
   eventual paid offer?
4. At the intended price, does a normal user produce a positive contribution
   margin after provider, model, routing, payment and allocated infrastructure
   costs?

The early product ideas of a roughly EUR 4 one-off report and EUR 8 monthly
access remain **pricing hypotheses**, not launch prices. Closed-alpha access is
free and invitation-only.

## Business hypothesis to test

The first target segment is not “everyone looking for work.” The calibration
must select one narrow initial segment—for example invited German-speaking
knowledge workers making an active regional or remote search—and record:

- the expensive or frustrating job-to-be-done BetterOption solves;
- the promised outcome and why existing boards/search are insufficient;
- the moment at which a tester first experiences that value;
- the one-off or recurring behavior for which that segment might pay.

This statement is a hypothesis until observed tester behavior supports it. A
large provider pool is not itself customer value; a small set of relevant,
trustworthy options with understandable trade-offs may be.

## What the provider-operation ledger records

The payload-free provider-operation ledger records provider, purpose, outcome,
latency, request/run units, returned result count, configured estimated cost,
workflow ID and time. The private Operations page displays this ledger together
with configuration, provider summaries and invoice-calibration controls; the
entire page is not itself one storage table.

The ledger deliberately excludes search text, location, Compass/CV content,
job bodies, URLs, responses and keys.

`v0.7.2f` adds two local presentation facts that must not be mistaken for
provider-cost controls:

- Source checkboxes in **What the last source run contributed** filter only the
  completed browser list. Every contributing source starts selected, and
  toggling one spends no request and changes no operation row.
- One deduplicated vacancy can retain several contributing providers. The
  source-run tile may therefore count that vacancy once for each provider that
  supplied it, while the visible job total still counts one vacancy. Cost and
  marginal-yield analysis must keep this provenance without adding the same
  vacancy several times to total product value.

The optional semantic relation pass is a separate bounded model cost inside
Matching. It considers only confirmed criteria left unresolved by deterministic
rules and canonical public job facts. Record its model invocation and token
cost in the complete workflow total. A later local Quickscore can reuse the
stored assessment while its cited evidence is unchanged and must not be counted
as another model call.

## Alpha entitlement and the future usage ledger

The provider-operation ledger above measures external work; it is not yet the
customer quota, entitlement or billing ledger. Keep that separation explicit.
Before any advertised quota or payment can depend on a counter, a durable usage
ledger must atomically record:

- account, plan and separately priced product unit;
- time bucket, configured allowance and configuration version;
- reservation, consumption, release and reconciliation state;
- an idempotency key so retries and concurrent requests cannot double-spend;
- counts and cost metadata only, never Compass/CV text, job bodies, URLs,
  provider responses or secrets.

Searches, provider operations, full Matches, draft generations, active job
slots, Compass changes and scheduled notifications are different units. Do not
compress them into one misleading request count. Reserve before paid work,
consume only what was used, and release the unused reservation on a safe
failure path. Reconcile the ledger against the payload-free provider-operation
rows and invoices.

During private alpha, invited testers should receive the full **test/max**
product entitlement so missing features do not distort feedback. It remains
bounded by hard per-workflow, per-account, daily and deployment-wide provider
and model budgets, plus a global kill switch. Public free and paid allowances
remain configuration hypotheses until calibration and observed repeat use make
them defensible.

## Vendor ownership, mail and billing inputs

Before friend alpha, move every enabled provider, model, routes, hosting,
monitoring and mail account to a controlled business-domain ownership identity.
Record the real legal/billing party, currency and tax treatment, MFA and recovery
owners, credential scope, current price, invoice location, spend alert and
disable/cancellation path. A personal mailbox or invented company identity is
not an acceptable substitute.

Before public registration, include verified transactional-email fixed and
variable cost in the worksheet: provider plan, messages, dedicated sender or
domain if used, bounce/complaint monitoring and operator time. Registrar
forwarding is not application mail. Before taking money, also price payment
fees, VAT/tax handling, invoices, refunds, disputes, support and reconciliation;
do not let payment state itself confer administrative authority.

For each provider:

- enter the current per-call or per-run estimate in the deployment environment;
- run representative workflows and confirm that every provider has a distinct
  ledger row;
- add the matching billing interval under **Calibrate estimates from invoices**;
- treat a base subscription separately until it can be allocated across the
  number of completed workflows in that month;
- never convert an unknown price to zero.

Record each source price with effective date, billing currency and source
(contract, pricing page, dashboard or invoice). Convert scenarios into one
planning currency using one named, dated FX source/rate, and retain the native
amount. Do not silently mix USD provider prices with EUR revenue.

## Ten-run calibration protocol

Run this owner-only before invitations. Keep the underlying profiles and search
origins stable so later changes remain comparable.

| Run group | Runs | Purpose |
| --- | ---: | --- |
| All configured providers | 5 | Cover distinct role families and locations, including one cross-border and one remote-heavy case |
| Measured provider bundles | 4 | Repeat representative cases with the proposed baseline and expanded bundles |
| Repeatability check | 1 | Repeat one unchanged all-provider run to expose source volatility |

For each completed run, record outside the payload-free ledger:

- total estimated and, where available, invoice-calibrated cost;
- elapsed time and provider failures;
- returned candidates per provider;
- unique candidates surviving policy and deduplication;
- appearances in the first 30 results;
- operator-selected/saved roles;
- obvious stale, duplicate, wrong-country and wrong-seniority rows.
- elapsed operator support minutes and any manual recovery action.

Record readiness separately from relevance: checked individual page,
provider-listed pending save verification, or manual text potentially required.
A recoverable source that remains visible after an import failure is not a
successful save, but it is also not a vanished candidate; include both the
failure and the recovery effort in the measurement.

Raw result volume is not a success metric. The useful marginal yield is the
number of unique, credible first-page or selected jobs a provider adds after the
common filters.

## Demand, conversion and operating measurements

The owner-only cost runs answer provider economics, not product demand. During
the later invited alpha also measure:

| Measure | Working definition |
| --- | --- |
| Acquisition channel | How an eligible person learned about BetterOption |
| CAC | Paid acquisition and attributable onboarding effort divided by activated users; friend referrals must not be recorded as zero-cost public acquisition proof |
| Activation | Tester completes Compass, Explore and saves or matches at least one credible role within the agreed window |
| Conversion intent | Tester reaches the value moment and truthfully indicates willingness to pay at a stated price/format |
| Retention | Activated tester returns for another meaningful workflow in the chosen 7-/30-day interval |
| Workflows per subscriber | Completed Explore/Match workflows per active subscriber and billing period, including failed charged runs |
| Support load | Operator minutes per activated user and per completed workflow |

Define the window and denominator before collecting results. Do not infer public
conversion or retention from the close-friend relationship alone.

## Unit-economics worksheet

Use the same accounting basis and currency for every scenario.

```text
variable cost per workflow
  = Explore provider calls/runs
  + model extraction and matching
  + route calls
  + email or other per-action services

variable cost per subscriber per period
  = variable cost per workflow
    × observed workflows per subscriber in the period
    + other observed per-subscriber variable costs

allocated fixed cost per subscriber per period
  = (hosting + backups + monitoring + fixed provider plans + support tools)
    / active paying subscribers in the same period

net revenue per subscriber per period
  = customer price - VAT/tax collected - payment fees - refunds/credits

contribution per subscriber per period
  = net revenue
    - variable cost per subscriber per period
    - allocated fixed cost per subscriber per period
    - allocated support cost

contribution margin
  = contribution per subscriber per period / net revenue
```

Calculate at least three demand cases—closed alpha, modest public use and a
stress case—and show both median and p90 workflow cost. A subscription scenario
must multiply by observed workflows per subscriber and period, not assume one
search per month. Model a one-off report separately because its repeat-use,
support and acquisition economics differ from a subscription.

## Provider-bundle decision

During local calibration it is useful to call every configured source. Public
economics may justify a staged bundle:

- **baseline:** reliable low-cost structured sources;
- **expanded:** sources called when baseline coverage or regional density is
  insufficient;
- **specialist/experimental:** explicitly chosen sources with a fixed fee,
  unstable contract or narrow marginal benefit.

The decision is evidence-led. A more expensive provider can still be the right
choice when it contributes substantially better unique jobs; a cheap provider
with no selected results is not automatically valuable.

Use account provider permissions or deployment configuration for bundle runs.
Do not infer a cheaper bundle from an Explore checkbox: that control only
changes what the user sees after every enabled source has already finished.
When a merged vacancy came from several providers, evaluate each provider's
incremental contribution with leave-one-source-out or equivalent deduplicated
analysis rather than crediting the full vacancy value independently to all of
them.

### Fantastic.jobs

Fantastic.jobs is not added to the `v0.7.2f` runtime; it was also deliberately
absent from `v0.7.2d`. The plan observed on 4 August 2026 offers a seven-day
trial with 50 requests and 500 jobs, followed
by no free monthly allowance; the lowest displayed paid tier is USD 95/month.
That fixed commitment is premature before marginal-yield measurement.

Use the trial only as a manual, bounded benchmark during the cost checkpoint.
Do not add a BetterOption credential, runtime adapter, background importer or
scheduled job for the trial. Record its result sample and cost outside normal
Explore, then remove/expire the test access. Integrate it later only if it adds
enough unique, relevant jobs to beat the best existing bundle and its fixed
monthly fee fits the demand scenario. Recheck the
[current pricing page](https://fantastic.jobs/api/pricing) before deciding.

## Keep, change and stop thresholds

Write thresholds before the ten-run protocol so a favorite provider is not
protected after the results are known. Use explicit numbers after the first
calibration pass; the categories are:

- **keep:** acceptable failure rate and p90 latency, positive unique first-30
  or selected yield, and marginal cost below the bundle ceiling;
- **change/conditional:** useful yield only for particular roles, locations or
  baseline shortfalls; define the trigger and maximum additional spend;
- **stop:** repeated unavailable/rejected runs, no meaningful unique yield, an
  unresolved hosted-use gate, or marginal cost above the safety threshold;
- **business stop:** acquisition, activation, retention, support minutes,
  workflows/subscriber or contribution margin misses the prewritten threshold
  for the agreed observation window.

For closed alpha, separately define a hard monthly spend cap, per-workflow cap,
maximum support burden and the person who disables providers or invitations.

## Exit gate for `v0.7.3`

The cost/business checkpoint is complete only when:

- [ ] all enabled paid providers have a current price and billing unit;
- [ ] the ten-run protocol is complete and failures are included, not discarded;
- [ ] median and p90 cost are known for the baseline and expanded bundles;
- [ ] fixed monthly costs are allocated in at least three demand scenarios;
- [ ] the EUR 4/EUR 8 hypotheses are accepted, changed or rejected explicitly;
- [ ] one target segment, value proposition and activation moment are written;
- [ ] acquisition/CAC, conversion-intent, retention, workflows/subscriber and
      support-minute definitions and thresholds are written;
- [ ] every non-EUR amount has its native value and a named dated FX basis;
- [ ] a closed-alpha monthly budget and per-workflow safety rail are configured;
- [ ] every enabled vendor has controlled business-domain ownership, real
      billing details, MFA/recovery, scoped credentials and spend alerts;
- [ ] the private-alpha test/max entitlement is configured under hard
      per-workflow, account, daily and global safety budgets;
- [ ] the provider-operation ledger reconciles every priced external action;
- [ ] a durable reservation/consumption/release usage-ledger contract is proven
      before any public quota or billing promise depends on it;
- [ ] each provider has a keep, conditional, experimental or disable decision;
- [ ] keep/change/stop thresholds were fixed before the final comparison run;
- [ ] the friend-alpha stop condition for uncontrolled spend is written down;
- [ ] the public-release scenario remains positive after realistic repeat use.

This is a product-planning model, not accounting, tax or legal advice.
