> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2g

`v0.7.2g` is a live-ranking, Compass-integrity, and Explore-transparency release
on top of the pushed `v0.7.2f` baseline. The candidate-facing product name
remains WorkLifeBalance and the canonical domain remains
`betteroption.example`.

## Dynamic Matching order

- A private job rating rescales the affected job locally from stored evidence.
  An employer rating rescales every job with the same normalized employer in
  one database transaction. Neither action starts extraction, research,
  routing, or an LLM request.
- Each rating response now includes the complete authoritative saved layout:
  run ID, every record ID, score, disposition, global/group position, and group
  counts. The browser moves cards between Top, Stretch, and Blocked immediately,
  updates counts and empty states, and uses a 180 ms position-switch animation.
  Reduced-motion preferences disable the animation.
- Returning from Job Detail receives fresh no-store HTML. The same-run layout is
  compared with the last rendered layout for the small move cue, while a real
  browser back/forward-cache restore reloads before it can show stale order.
- For every non-blocked result, the visible group now follows the visible score:
  60 or more is Top and less than 60 is Stretch. Unknown must-haves already
  reduce evidence coverage and score contributions; they no longer impose a
  second hidden grouping threshold. A supported hard conflict or explicit
  0-star blocker still produces Blocked regardless of score.

The Matching identity changes to `matching-v0.7.2g`. A saved `f` result remains
readable but needs one complete Match run before the new local reranking contract
is active.

## Always-available Compass integrity companion

- One deterministic, source-aware integrity report is shared by Add, Explore,
  Matching, Apply, Archive, and the Compass itself. It uses the confirmed facts
  from guided answers, reviewed CV proposals, and direct Compass edits. It does
  not make a provider call merely because a page opens.
- Exact wanted/excluded duplicates, opposite hard workplace modes, and
  impossible confirmed numeric bounds such as at most two versus at least four
  office days stop only the actions that consume the whole Compass: Compass
  Explore, Matching, and creation or AI rewriting of a cover-letter draft. The
  server enforces the same rule as the disabled UI action. Negated statements
  such as not wanting fully remote work remain exclusions, not invented remote
  requirements.
- Add, a user-written Explore search, viewing/editing existing drafts, and
  Archive stay available. `Ask me later` hides the note only for the current
  page visit and never bypasses an applicable server gate.
- Broad or adjacent career interests remain allowed. Junior/senior breadth,
  distant alternative origins, and unfinished guided questions are warnings or
  notes rather than automatic blockers. When the facts look like two real
  search directions, the notice offers a second persona where the persona limit
  permits one.
- The checker is deliberately conservative rather than a second always-on LLM.
  This keeps the result fast, repeatable, private, and free of a new per-page
  processing dependency. Ambiguity remains visible for the user instead of
  becoming an invented contradiction.

## Guided and widget consistency

- A newer confirmed mobility origin or modal limit now supersedes the older
  active fact and rebuilds the legacy typed projection. Compass, Explore, and
  route preparation therefore use the same newest public starting point.
- Guided/CV spoken and programming language evidence now appears in the catalog
  widget. An explicit level is selected; a mention without a reliable level is
  shown as `Found in Compass · choose a level` rather than receiving an invented
  proficiency. Saving the widget supersedes prior canonical language facts.
- The white Guided Setup side tile is taller, remains vertically centered on
  desktop, and contains the expandable `Start a new compass` control. The
  current checkpoint replacement still requires explicit confirmation.

## Progressive Explore preview and first-party jobs

- The background Explore page shows up to seven current leaders below the main
  status tile. The cards are intentionally not selectable or clickable until
  the complete search is ready.
- Each completed source triggers a new local merge and rank. Primary and
  fallback results remain cumulative in configured source order, and the final
  source-readiness pass produces the last preview. A slow provider can therefore
  move the current ranking without losing earlier results.
- Preview responses contain display fields only: no source URL, external ID,
  checkbox, or action link. Late callbacks cannot overwrite the completed full
  snapshot. A failed preview callback or intermediate preview/status write is
  best effort and cannot abort provider search or final-result storage.
- Missing distance, seniority, or other incomplete evidence adds no positive
  points. The card says that the detail is pending until evidence exists.
- Published vacancies from the verified internal HR input already participate
  in the same search and ranking. They now receive a prominent dark-blue `Own`
  badge and remain `Source checked` without an inappropriate loopback network
  preflight.
- Provider identity remains presentation metadata, not a ranking signal. The
  visible AgentX badge is `All Jobs via Apify`; no job badge uses “Scraper” or
  “Scraping”.

## Candidate-facing language

- Rotating waiting lines change approximately half as often, use one line and
  one sentence, contain no semicolons, avoid `thorough`, and mix practical
  reassurance with job-search-specific humour and observations.
- Candidate-facing templates, controls, notices, and saved match explanations
  use WorkLifeBalance rather than the internal BetterOption package/project
  name. Technical package names, environment-variable prefixes, archive names,
  and HTTP user-agent identifiers remain stable for compatibility.

## Naming and later abuse protection

The updated comparison adds `whata.work`, `thesejobs.life`, `movingon.work`,
`milesahead.work`, `localjob.life`, and `localife.work`. `movingon.work` is the
best new option but does not displace `betteroption.example`,
`balancedwork.life`, or `lifelife.work`. There is no UI or deployment rename;
see the [full v0.7.2g naming note](../../discontinued-product-planning/domain-name-decision-v0.7.2g.md).

No bot-control integration is enabled for this private local baseline. Before
public registration, the deployment roadmap now requires server-verified
Cloudflare Turnstile plus a narrowly calibrated registration rate-limit or
challenge rule. Invite-only registration remains the earlier and stronger
closed-alpha control. Implementation must follow Cloudflare's
[server-side Turnstile validation](https://developers.cloudflare.com/turnstile/get-started/)
and [WAF rate-limiting guidance](https://developers.cloudflare.com/waf/rate-limiting-rules/)
for the real hosted configuration.

## Release identity and migration

- Application/source release: `0.7.2g`
- Python distribution: `0.7.2+g`
- Matching algorithm: `matching-v0.7.2g`
- Archive: `betteroption_v0_7_2g.zip`
- Git tag: `v0.7.2g`
- Database migration: none
- Privacy draft: unchanged at `2026-08-05-draft`; this release adds no new LLM
  data route

Existing accounts, personas, Compass data, jobs, tasks, ratings, drafts,
provider diagnostics, and internal operational records remain in place.
