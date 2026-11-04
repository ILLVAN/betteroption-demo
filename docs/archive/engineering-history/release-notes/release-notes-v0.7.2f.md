> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2f

`v0.7.2f` is a candidate-control and evidence-quality release on top of the
installable `v0.7.2e` baseline. It makes the normal account export smaller,
turns provider attribution into useful local Explore controls, keeps
recoverable discoveries from disappearing during import, and adds a bounded
semantic relation pass for Compass criteria that deterministic Matching cannot
resolve by itself.

The product and UI remain WorkLifeBalance. There is no database migration.

## Portable profile export

- **Download profile JSON** now returns
  `betteroption-portable-profile-v1`: account basics, accepted legal-document
  versions, personas and the current Compass for each persona.
- A current Compass contains its setup state, location, work model,
  compensation, confirmed statements and open questions. It does not expose
  internal row IDs or historical rejected proposals.
- Raw conversations, older workspaces, tasks, provider operations, Explore
  snapshots, saved-job grants, Match runs and results are absent from the
  user-facing file.
- The complete secret-safe operational/private graph remains available to the
  authorized internal export and diagnostic paths. The new file is a portable
  profile, not a deletion of operational evidence and not a substitute for the
  complete data-subject-request procedure.
- The download is marked `no-store` and uses the stable filename
  `betteroption-profile-export.json`.

## Compass, waiting copy and feedback

- Guided setup is the Compass primary action. **Add a job**, **Explore jobs**
  and **Open Matching** follow as secondary routes in that order.
- Progress phrases that implied the page could not be used, promised automatic
  navigation or congratulated a page reload have been removed. Persisted tasks
  still show their independent live technical status.
- **Save feedback** uses the standard black primary-button treatment in Job
  Detail and Match Detail rather than the teal confirmation style.

## Explore provenance and local source filters

- Each discovery retains stable provenance from every provider that supplied
  the same normalized vacancy URL. Deduplication still chooses the richer row
  as the primary record; merging does not turn provider identity into a ranking
  signal.
- The richer row's provider appears as one small light-blue source badge beside
  readiness and date badges. Redundant source tags such as `Source:` and
  `Published via` are not repeated on the card.
- The **Info** disclosure remains available but is visually secondary to search
  and filters.
- **What the last source run contributed** keeps the secret-safe found and
  contributed counts and now owns the provider filters. Every source that
  contributed a displayed result starts checked; sources with no filterable
  result remain visible but disabled.
- Toggling a provider filters the completed cards immediately in the browser.
  It does not start a search, spend a provider request, mutate the snapshot,
  rerank a job or change account provider permissions.
- A vacancy supplied by several providers remains visible while at least one of
  its providers is checked. Because provenance is preserved, the same merged
  vacancy can correctly contribute to more than one provider's source-run
  count while remaining one result card.
- Old Explore snapshots without provenance or readiness fields still restore:
  their primary provider becomes their effective provider and their safe
  default readiness is **Verify on save**.

## Individual-vacancy and readiness contract

- Every provider now passes the same structural single-vacancy gate before
  final ranking. Bare domains, search results, category pages, generic job
  indexes, editorial pages and error landings are rejected even when a
  structured provider returned them.
- The gate does not require a careers hostname. A non-root, non-generic
  employer URL with a role-shaped path and job evidence can still enter, which
  preserves useful direct-employer recall.
- Raw Brave/Exa/You.com-style web results remain fail-closed: they enter the
  final list only after the bounded preflight fetched a plausible individual
  page. A raw result that could not be checked is not presented as trustworthy.
- Structured provider results may remain when the bounded preflight did not
  reach them. Their status says **Verify on save** rather than implying that the
  page was checked.
- Readiness labels have deliberately narrow meanings:
  - **Source checked**: Explore fetched a plausible individual page; save still
    performs a fresh verification and extraction.
  - **Verify on save**: a structured provider listed the vacancy, but BetterOption
    has not yet checked the individual source page.
  - **Manual text may be needed**: fetching or extraction could not complete;
    the source remains available for inspection and recovery.
- During Save or Save and run Match, a classified unreachable or extraction
  failure updates the stored Explore row to manual-required instead of silently
  deleting it. A definitively expired vacancy is removed. Failures remain
  reported, and a Match starts only for jobs that were actually imported.

These checks improve the observed Explore-to-Match survival rate without making
an availability, employer-identity or contractual claim that the evidence does
not support.

## Evidence-bound semantic Matching

- Matching remains deterministic first. Only confirmed must-haves,
  preferences and exclusions that the fixed rules leave unresolved are eligible
  for the optional semantic relation pass.
- When OpenAI is configured and allowed by the existing processor boundary, the
  pass receives a bounded set of those criteria and canonical public job facts
  with short evidence quotes. It does not receive account/persona metadata, raw
  Compass answers, CV text, private ratings, home location or the complete job
  advertisement.
- The model may classify a relation as satisfied, supporting, violated or
  unknown and cite only supplied fact IDs. It cannot set a Compatibility score
  or recommendation category, and provider failure degrades to Unknown without
  preventing the deterministic Match.
- Deterministic results always win over a conflicting semantic response. The
  model cannot return high confidence; a low-confidence contradiction is
  normalized to Unknown. A server-validated medium-confidence violation of a
  hard Compass criterion can become a blocker, including cross-key conflicts
  such as a documented on-site arrangement against a maximum office-days
  boundary.
- Each retained assessment is bound to the cited job facts with fingerprints
  and stored in the Match snapshot. Job/employer Quickscore changes can reuse
  it locally without another model call. A changed or removed cited fact makes
  the old relation unusable, and changed Compass/source/private evidence remains
  visible through the existing full-rematch gate.
- The Matching identity is now `matching-v0.7.2f`. Older stored Match runs are
  deliberately marked as using an older algorithm and require one complete
  Match before per-job refresh or current Quickscore reuse.

## Naming decision, not a rename

The expanded comparison keeps `betteroption.example` as the private-alpha
canonical address. `balancedwork.life` is the strongest practical challenger
and `lifelife.work` the strongest personality challenger; the other supplied
options have clarity, collision, trust or price drawbacks. No product name,
logo, static UI or canonical-domain change is included. See the
[v0.7.2f naming note](../../discontinued-product-planning/domain-name-decision-v0.7.2f.md).

## Release identity and compatibility

- Application and source release: `0.7.2f`
- Python distribution: `0.7.2+f`
- Matching algorithm: `matching-v0.7.2f`
- Database migration: none
- ZIP: `betteroption_v0_7_2f.zip`
- Git tag: `v0.7.2f`

Existing accounts, personas, jobs, application history and Explore snapshots
remain readable. Follow the [local install and acceptance guide](../local-guides/local-v0.7.2f.md)
for backup, overlay, version checks, regression testing, archive creation and
publication. The [v0.7.2d source review](../providers/job-source-review-v0.7.2d.md) remains
the provider request/contract baseline; this release adds common provenance,
shape and readiness behavior after those adapters return.
