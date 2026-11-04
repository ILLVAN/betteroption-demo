> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1g-user-controls

`v0.7.1g-user-controls` makes external processing an account decision, extends
the job workflow without weakening persona isolation, and replaces a missing
salary result with a clearly separated Europe-aware orientation channel.

Application version: `0.7.1g-user-controls`  
Python package version: `0.7.1+g.user.controls`  
Release archive: `betteroption_v0_7_1g_user_controls.zip`  
Database head: `0022_application_draft_slots`  
Matching algorithm: `matching-v0.7.1g`

## Account-wide provider choices

Deployment configuration still decides which adapters and credentials are
technically available. The Account page is a second, narrower authorization
boundary: an account may enable only the available external services it wants
BetterOption to call. The choice applies to every persona in that account;
personas cannot silently widen it.

The conservative migration default is an empty selection. Existing accounts
must therefore open **Account → Provider choices** once after upgrading and
enable the desired configured services. A disabled provider is stopped before
its adapter call and creates neither provider traffic nor a cost row.

The selectable boundaries cover OpenAI, Arbeitnow, Brave Search, Exa, supported
employer ATS boards, Wikimedia company context, Google Routes, Transitous,
openrouteservice, Valhalla/FOSSGIS and OpenStreetMap Nominatim. Brave Answers is
not an application dependency; BetterOption uses the separate Brave Search API
key only.

## Operation and cost semantics

New provider operations are attributed to the authenticated account. Account
shows metadata-only totals for that account: operation count, known configured
estimates and the number of operations whose price is unknown.

- disabled provider: no call and no cost entry;
- enabled provider with a positive configured estimate: the stored estimate is
  included in the known total;
- enabled provider with estimate `0`: the call is recorded as **unpriced**, not
  as free;
- provider-side invoices and limits remain authoritative;
- historical rows are neither reassigned nor repriced;
- these totals are observed configured estimates, not a forecast or invoice.

No speculative prices or business-model estimates are introduced in this
release. Cost calibration remains a separate step after the UI and provider
architecture stabilize. Shared operator-level operation/cost limits remain a
safety rail in addition to each account's choices.

## Europe-aware salary orientation

Salary handling remains evidence-first and occupation-agnostic. Advertised pay
always wins. For a European vacancy without stated pay, the bounded research
adapter first seeks attributable occupation/country evidence from the reviewed
official-source allowlist. It retains country, original currency and period,
annualization basis, sources, confidence and any attributable ECB conversion.

When no acceptable source survives validation, the same structured response may
provide a broad EUR gross/year AI orientation for the detected occupation and
country. That fallback is visibly labelled **unsourced AI orientation**, has
very-low confidence and no source link, and is kept outside compatibility
scoring. It is not employer pay, market evidence, a promise or a blocker. Salary
research no longer requires a salary criterion in the Compass, so a user can
receive orientation without first inventing a target.

## Candidate-controlled job evidence

Job Detail can store typed, persona/job-specific corrections for:

- a matching reason or boundary outcome;
- commute duration;
- whether a displayed skill is matched or missing.

Corrections are validated against the current owned match, shown as user
overrides and reapplied on the next Match run. They never edit the public job
observation or the Compass. Deleting a correction restores automatic evidence.

## Employer portals and application drafts

Each persona may save up to ten public HTTPS employer career portals under Add.
Enabled hostnames become bounded Explore search hints when an allowed search
provider runs. BetterOption does not turn this list into an unrestricted direct
crawler; local/private/reserved targets and credential-bearing URLs are rejected.

Apply now supports up to three named cover-letter drafts for each persona/job.
Each draft has a stable direct link, can be renamed, edited, shortened,
lengthened, recreated or deleted independently, and appears as a count on job
cards. Capacity is checked before a provider call. BetterOption still never
submits an application or contacts an employer.

## Interface changes

- Add keeps **Continue to Match** at the end of the intake workflow.
- Apply collapses the selection panel once drafts exist and uses a compact,
  aligned job selector plus individual draft panels.
- Explore cards omit the repeated seniority paragraph and clamp long excerpts.
- Rejected and Withdrawn cards use readable diagonal striping; Job Detail uses
  a stronger matching state treatment without lowering text opacity.

## Migrations and rollback

Three additive migrations advance the single Alembic head:

1. `0020_g_user_controls`: account provider preferences, account attribution on
   new operation rows, and persona portal sources.
2. `0021_job_evidence_overrides`: typed workspace/job evidence corrections.
3. `0022_application_draft_slots`: three named slots while preserving the former
   single draft as `Draft 1`.

Back up `local-data/betteroption.db` before installation. The safe source
rollback is to reinstall the prior immutable ZIP and restore its matching
pre-upgrade database copy. Do not assume older source understands the new head.

## Operating boundary

This iteration is for the loopback-only local product. It does not deploy a
server, open registration publicly, complete provider/commercial review, or
declare the legal package ready for a private alpha. Transitous remains
technically selectable for local evaluation, but its public hosted service must
undergo explicit suitability and provider review before any commercial or
for-profit launch.

Use [the complete local, acceptance and GitHub cycle](../local-guides/local-user-controls-v0.7.1g.md).
