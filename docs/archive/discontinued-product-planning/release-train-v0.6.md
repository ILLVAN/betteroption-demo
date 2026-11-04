> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# v0.6 Private-Alpha Release Train

> **Historical record — superseded.** This document preserves the original
> v0.6 assumptions for traceability; it is not the current version sequence or
> launch decision. Use the
> [roadmap to closed alpha and public release](roadmap-to-public-release.md)
> for the active path from `v0.7.2k` to `v0.8.0`.

The 0.6 line is one continuous hardening path. No 0.7 release is planned before
the single-model private-alpha workflow is coherent enough for real testers.

| Version | Product outcome | Safety boundary |
| --- | --- | --- |
| 0.6.0 | Persistent URL corpus, revisions, lifecycle, and cached extraction | Existing deterministic matching remains the decision authority |
| 0.6.1 | Clean application boundaries, provider registry, model policy, prompt versions, invocation/cost metadata, and database migrations; delivered together with 0.6.2 | Provider choices stay outside domain and deterministic decisions |
| 0.6.2 | First FastAPI web shell and calm, responsive home dashboard | Opportunity and matching views remain read-only |
| 0.6.3 | Database-backed profile conversation, resumable onboarding, Review Tray, and verified URL-only reference jobs | User corrections remain authoritative, audited, and protected from model overwrite |
| 0.6.4 | Opportunity inbox, URL imports, corpus states, job detail, and revision history | URL validation and evidence rules remain unchanged |
| 0.6.5 | Top/Stretch/Blocked results, evidence explanations, unknowns, feedback, and application states | Every claim remains linked to advertisement evidence |
| 0.6.6 | Road, rail, bicycle, and walking-time constraints with caching | Mobility uncertainty is explicit; no invented precision |
| 0.6.7 | Unified Job Detail, employer/work-mode evidence, mobility diagnostics, and privacy-aware CV ingestion | CV content has explicit retention/deletion controls; restricted sources are not bypassed |
| 0.6.7b | Explore discovery, Transitous fallback, reviewed CV merge, and salary orientation | Discovery is opt-in; benchmarks and community transit remain labelled estimates |
| 0.6.7c | Compass-driven multi-source discovery and corrected Transitous place resolution | Web results remain candidates until robots, reachability, and evidence verification succeeds |
| 0.6.7d | Company product/reputation evidence, personalized Stretch guidance, transparent proximity ranking, and standard-Tuesday transit sampling | Kununu remains manual or employer-republished; no prohibited scraping |
| 0.6.7e | Route-precision safeguards, attributed company research, review-profile links, and seniority-aware Compass discovery | City labels are not door-to-door evidence; review sites remain manual; proven exclusions block deterministically |
| 0.6.8 | Full-quality routing for all 25 slots, cheap Explore geography, privacy modes, weekday ranges, and outlier protection | Exact routes run only after explicit Matching; provider payloads exclude profile content |
| 0.6.8b | Small-city Transitous recovery, cached geocoding, and warning-free XML-like job fragments | Recovery stays bounded; an unavailable route remains Unknown rather than estimated |
| 0.6.8c | Rate-limit-safe Transitous matching, temporary-error recovery, and standalone mobility diagnostics | One public plan request asks for seven alternatives; persistent failure remains an attributed Unknown |
| 0.6.8d | Locality-safe geocoding, employer identity repair, POI-aware destination hints, and saved-run diagnostics | Fuzzy station names cannot become route evidence; provider failures remain visible and unscored |
| 0.6.8e | Offline German postcode resolution and postcode-safe Transitous routing | A postcode-only Compass origin cannot be truncated by a fuzzy geocoder; old commute caches are invalidated |
| 0.6.8f | Google-free Valhalla routes for car, bicycle, and walking plus immediate Compass activation | Public route endpoints stay transparent and rate-limited; CV/reference evidence still requires review |
| 0.6.8g | Canonical modal limits, readable long durations, and clear slow-operation feedback | Ambiguous mode-free limits stay Open; progress UI never claims a fake completion percentage |
| 0.6.9 | Discovery Source Mesh: direct ATS boards, employer feeds, Brave discovery, and a conditional Exa fallback | Search results remain untrusted candidates until the existing URL, robots, reachability, and evidence pipeline accepts them |
| 0.6.9b | Priority stabilization: bounded parallel Match I/O, cached employer context, postcode-aware Explore distance, Compass-derived work arrangement, and cleaner evidence | Existing jobs and commute caches remain valid; routing origins never become advertisement requirements; unavailable optional sources fail as Unknown |
| 0.6.9c | Regional discovery ranking, deeper feed coverage, explicit feedback learning, active Compass deduplication, CV review state, and language evidence | Regional company discovery stays bounded in the request path; a future background employer pool may grow toward 200 companies without synchronous crawling |
| 0.6.9d | Reliable direct Compass additions, anchored edits, four-state commute presentation, and full keyless feed depth | Explicit user input cannot disappear; route colors never replace textual evidence; paid discovery remains opt-in and bounded |
| 0.6.9e | Locality-first Brave/Exa discovery and candidate-language evidence | Remote or far-away volume cannot satisfy regional coverage; web discoveries remain untrusted until URL verification and extraction; capability evidence stays separate from desired workplace language |
| 0.6.9f | Google-first balanced routing, closed web-result preflight, persistent Explore navigation, and separated local release scripts | Google responses remain uncached; only demonstrably expired discoveries are removed; local secrets and runtime data stay outside release archives and Git staging |
| 0.6.9g | Contextual sensitive-category evidence, likely direct-employer assessment, and evidence-backed seniority inference | Generic operational monitoring cannot prove human surveillance; absence alone never proves a legal employer or formal grade |
| 0.6.9h | Closed-result preflight, atomic slot limits, complete bulk deletion, evidence-shaped Compass prompts, and refreshed code-native branding | Stale structured data cannot override a visible closed status; destructive actions require explicit confirmation and remove the complete local aggregate |
| 0.6.9i | Compass consistency review, evidence-calibrated scores, modal destructive confirmation, card-integrated selection, and lighter branding | Role breadth remains valid; only material contradictions pause Matching; sparse evidence cannot present false certainty |
| 0.6.9j | Unambiguous in-card deletion, server-visible destructive intent, release-version asset caching, and an operational cost-control contract | Accepted matching and source behavior remains unchanged; deletion cannot depend on cached JavaScript |
| 0.6.10a | Narrow exclusion polarity, Compass-first Explore, accessible destructive confirmation, and a privacy-safe provider-operation ledger | Provider metadata cannot contain user payloads; configured daily guards degrade honestly; internship exclusions block internships only |
| 0.6.10b | Visible provider-cost control room, overview-card application states, and mobility-origin consistency | Operation views remain payload-free and read-only; all application views share one append-only interaction history; commute checks stay locality-agnostic |
| 0.6.10c | Explicit provider visibility and per-Match operational KPIs with compact overview-card workflow controls | Opaque workflow correlation contains metadata only; unpriced work is never represented as free; accepted matching behavior remains unchanged |
| 0.6.10 | Provider-operation ledger followed by a cross-source evidence graph and multidimensional match quality | Sensitive payloads are excluded from telemetry; advertisement silence remains Unknown; every dimension keeps source and confidence |
| 0.6.11 | Durable background Matching, real progress, bounded retry recovery, and enforceable daily/per-workflow provider budgets | Slow Match work survives refresh/restart and is idempotent; progress reflects persisted state; retries cannot spend beyond a workflow budget; discovery and extraction retain their accepted behavior |
| 0.7.0 | Authentication, tenant isolation, export, and complete account deletion | Two test users cannot access each other's database rows or files; deletion and recovery are verified before invitations |
| 0.7.0e | Bounded global Explore discovery with cached geography, parallel source stages, multiple focused Exa queries, and explicit Worldwide/Remote filters | Default results stay on the Compass continent without assuming Europe; the whole source mesh returns within 115 seconds; unresolved places never receive invented proximity |
| 0.7.0g | Clean v0.7.0e compatibility rebuild with durable Explore-to-Match handoff and recoverable rejected sources | Worldwide persisted searches remain readable; Matching always exposes an active import or match task; one unusable URL cannot block the next workflow |
| 0.7.0h | Live operator workflow activity, profession-neutral feedback, clean overlay repair, and an invited-alpha deployment decision | Accepted search and matching behavior remains unchanged; current task activity is visibly fresh; stale pre-account tests cannot poison the release gate |
| 0.7.0i | Provider-neutral single-node staging foundation with private PostgreSQL, Caddy HTTPS, migration-first startup, health probes, and guarded logical backups | Only Caddy publishes ports; secrets and runtime data stay outside releases; a clean database reaches one migration head; staging is not treated as tester-ready |
| 0.7.1a | Netcup/Cloudflare staging readiness, public-origin configuration, deployment preflight, and exact invited-alpha runbook | Unsafe database, authentication, cookie, public-origin, password, or operator configuration blocks staging; open readiness work remains visible |
| 0.7.1b | Invitation-only onboarding, exact-address email verification, single-use recovery, proxy-aware throttling, CSRF protection, and owner account controls | Uninvited accounts cannot register; tokens expire and work once; tenant isolation and same-origin enforcement pass adversarial tests |
| 0.7.1 | Legally and operationally ready invited alpha | Consent, disclosures, retention, incident handling, backups, monitoring, and support are reviewed before invitations |
| 0.7.2 | Quality evaluation with 10–30 invited users | Search yield, match precision, latency, failures, feedback, and cost per useful result are measured against a frozen gold set |
| 0.8.0 | Payments and limited public beta | Entitlements, cancellation, abuse controls, support burden, and contribution margin are proven with conservative limits |

Each increment must preserve all earlier product contracts and pass the complete
regression suite. A version can move later or be split when user testing exposes
a real problem; version numbers are not a reason to ship an unsafe boundary.

The private-alpha free-access allowance is 25 stored and matched jobs. v0.6.11
persists 25 unique Top/Stretch grants per profile workspace across reruns and
caps the free archive at 25 records. Every valid slot gets the same Match and
routing quality; Explore uses only offline approximate distance. Confirmed deletion frees a slot. Blocked
explanations remain transparent. The allowance can be revisited with real alpha
usage and provider-cost data; subscription and billing infrastructure follows
only after the result workflow and its contribution margin are trustworthy. See
[Roadmap to closed alpha and public release](roadmap-to-public-release.md).
