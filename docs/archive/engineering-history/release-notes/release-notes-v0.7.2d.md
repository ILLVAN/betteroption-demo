> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2d

> **Withdrawn source archive.** The product changes below passed their
> regression gate, but the handed-off ZIP used the invalid Python distribution
> version `0.7.2d` and cannot be installed by current setuptools. Use
> [`v0.7.2e`](release-notes-v0.7.2e.md), which contains the same product behavior
> with corrected package metadata.

`v0.7.2d` makes long workflows calmer and small user judgments immediate. It
does not rename WorkLifeBalance and does not change the stored Matching
algorithm identity.

## Immediate private Quickscore

- Clicking a job star saves the private rating and locally recalculates that
  saved match in the current page.
- Clicking an employer star recalculates every saved result belonging to the
  same normalized effective employer, including ordinary company-suffix
  variants.
- The response updates Compatibility, disposition labels and peer rating
  controls without opening Job Detail.
- A felt rating does not need evidence. There is no “Apply it to this Match” or
  implicit provider-backed rematch.
- Zero stars remain an explicit private blocker. Clearing a rating reverses its
  deterministic adjustment using the stored match inputs.

## Explore order and presentation

- Provider identity is not a ranking signal. Role content, Compass relevance,
  seniority, exclusions, distance, known posting age and evidence completeness
  decide locally.
- Posting age stays a small signal: a known Fresh date adds 2 Explore points,
  a date older than four calendar months removes 4, and unknown/future dates
  add nothing. Relevance and exclusions remain much stronger.
- A detected Compass exclusion conflict is marked with a warning badge and
  reduces the Compass relevance component to one quarter. Explicit title-level
  seniority conflicts keep their existing strong penalty and transparent tail
  placement.
- The maximum-distance control now has 41 practical stops: 5 km increments
  through 100 km, 25 km increments through 500 km, then 100 km increments
  through 1,000 km/Any distance. The URL and local state retain real kilometre
  values. Remote and unresolved-location results remain exempt.
- Explore titles use the same serif family as other job cards. “Web discovery”
  and “Semantic web fallback” badges are removed. Valid non-future dates show
  Fresh or Older; missing, invalid or future dates remain unlabeled.
- Every reached source reports both jobs found and jobs contributed to the
  bounded ranked results, including an honest zero.

## Search providers

- The controlled JSearch live diagnostic reached `search-v2` and returned ten
  jobs. `v0.7.2d` broadens terse Compass concepts into small role-family queries
  such as software developer, embedded software engineer or QA engineer while
  retaining at most three bounded requests. This proves key, transport and
  response parsing; real Explore contribution still depends on the query and
  final local comparison.
- Exa, Brave, You.com and structured sources enter the same local ranking. Exa
  is no longer granted an implicit fallback tie-break. For duplicate URLs, the
  more complete dated/location/company evidence may win regardless of provider.
- All configured and account-enabled providers can continue to run in parallel
  under the shared 390-second Explore budget.

## Calmer background work

- Explore and Match progress pages rotate through 180 unique local lines. Each
  page draws from 80 common plus 50 workflow-specific lines at a random 12–42
  second interval. Some Explore lines safely include the stored location.
- Technical progress stays live on its own line and is hidden whenever it would
  duplicate the heading.
- No LLM, analytics or provider call is used for waiting copy. A future
  AI-generated batch should be generated only when Compass changes, cached,
  safety-checked and visibly labelled as AI output.
- Concurrent local tabs now share one active Explore, Match, identical import
  or single-job rematch task. A graceful worker stop requeues its current claim;
  attempt guards prevent a late stopped worker from overwriting a restarted
  attempt.

The pasted Uvicorn log already ended with `Finished server process` and the
PowerShell prompt, so that particular shutdown was clean. Durable queued work
surviving a restart is intentional. This release fixes duplicate-creation and
ambiguous interrupted-claim behavior, not the persistence itself.

## Copy, footer, configuration and naming

- “Corroborated positive-fit calibration” becomes “Confirmed fit signals” and
  “56 base” becomes a readable starting-point explanation. The fixed point
  mechanics remain inspectable.
- The footer is one short line with internal legal/storage links only.
- Secret-safe diagnostics now identify temporary local open registration, the
  old Exa-named fallback alias, disabled zero-dollar cost guards and unsafe
  hosted basics.
- The staging example includes every current background and provider-cost field.
- WorkLifeBalance remains the UI and canonical alpha name. `LifeLife.work` is
  documented as the strongest alternative to test, not an approved rename.

See the [environment audit](../local-guides/local-environment-v0.7.2d.md),
[domain note](../../discontinued-product-planning/domain-name-decision-v0.7.2d.md),
[source review](../providers/job-source-review-v0.7.2d.md) and
[provider setup](../providers/discovery-provider-setup-v0.7.2d.md).

## Release identity

- Application and source release: `0.7.2d`
- Python package version: `0.7.2d` (invalid PEP 440; archive withdrawn)
- Matching algorithm: `matching-v0.7.2c`, unchanged
- Database migration: none
- ZIP: `betteroption_v0_7_2d.zip`
- Git tag: `v0.7.2d`

Keeping the Matching identity means existing `v0.7.2c` matches remain current.
The release changes when and where private-rating rescoring is applied, not the
published deterministic scoring formula.
