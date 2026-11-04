> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption compliance dossier

Status date: 2026-08-05
Current product baseline: v0.7.2k
Original dossier checkpoint: v0.7.1b-legal
Status: **internal draft — external legal review and operational evidence required**

This folder turns the private-alpha product boundaries into an auditable
compliance baseline. It is not a legal opinion, does not prove compliance, and
must not be used to set the application's readiness flags to `true` by itself.

## Binding alpha decisions

The operator has selected the conservative alpha described in
[`01-alpha-product-boundaries.md`](01-alpha-product-boundaries.md). In
particular:

- recommendations are controlled by and visible only to the candidate;
- no employer or recruiter can access candidate profiles, rankings, or matches;
- the service never submits an application;
- real user profiles are not used to train, fine-tune, benchmark, or evaluate a
  model;
- the alpha is for invited adults only;
- Article 9 special-category data and Article 10 criminal-offence data are
  prohibited;
- only reviewed providers may be enabled;
- location starts at city or postcode precision;
- every personal-data class has a finite retention rule.

## Dossier

1. [Alpha product boundaries](01-alpha-product-boundaries.md)
2. [Record of processing activities](02-record-of-processing-activities.md)
3. [Lawful-basis assessment](03-lawful-basis-assessment.md)
4. [Data protection impact assessment](04-dpia.md)
5. [Legitimate-interests assessment](05-legitimate-interests-assessment.md)
6. [Technical and organisational measures](06-technical-organisational-measures.md)
7. [Retention and deletion schedule](07-retention-deletion-schedule.md)
8. [Data-subject request procedure](08-data-subject-request-procedure.md)
9. [Incident and breach-response procedure](09-incident-breach-response.md)
10. [Processor and recipient register](10-processor-register.md)
11. [External review and launch record](11-external-review-and-launch-record.md)

The current JobsPipe, AgentX All Jobs, JSearch and web-search request/source
delta is recorded separately in the
[v0.7.2d Explore provider source review](../../engineering-history/providers/job-source-review-v0.7.2d.md). Its
open items keep scraping actors local-only and do not make the older dossier
complete.

## v0.7.2f data and automated-assessment boundary

- The ordinary Account download is now a portable profile containing account
  basics, legal-document acknowledgements, personas and each persona's current
  Compass. It deliberately omits raw conversation history, internal IDs,
  provider operations, background tasks, Explore snapshots and Match history.
- That convenience download does not narrow the application's retention,
  support or data-subject-rights obligations. The complete private account
  graph and secret-safe operational diagnostics remain available internally
  under their existing authorization, retention and deletion controls. A full
  access-request response must follow the separate DSR procedure rather than
  treating the portable profile as automatically complete.
- Explore's provider checkboxes only hide or show already returned cards. They
  do not call, disable or authorize a provider and do not change the
  payload-free operation ledger. Account permissions and deployment settings
  remain the processing controls.
- Source-readiness labels are deliberately narrow: a page checked during
  Explore is rechecked on save, a structured provider listing is verified on
  save, and an inaccessible or unextractable source can remain visible as
  manual-recovery work. None of these labels claims that BetterOption verified
  the employer, contractual terms or continued availability.
- When configured and permitted, the optional semantic Match pass receives
  only confirmed criteria left unresolved by deterministic rules and canonical
  public job facts with short evidence quotes. It cannot assign a score or
  disposition, deterministic outcomes take priority, low-confidence conflicts
  remain Unknown, and the validated evidence-bound assessment is retained with
  the Match for local reuse. The public legal notices and processor register
  must describe the actually enabled model route before hosted testing.

See the [v0.7.2f release notes](../../engineering-history/release-notes/release-notes-v0.7.2f.md) for the product
contract. These changes improve minimisation and transparency; they do not
complete the open external-review or launch gates below.

## v0.7.2h private-alpha, integrity, and preview boundary

- The Compass integrity report runs deterministically over the active persona's
  already confirmed facts. Opening Add, Explore, Matching, Apply, Archive, or
  Compass does not send those facts to a new provider or LLM. Server handlers
  apply the same action-specific gate shown by the UI.
- A blocking issue pauses Compass-based Explore, Matching, and new application
  generation. It does not prevent the candidate from adding public jobs,
  running a self-authored search, using Archive, or reviewing existing drafts.
  The notice has no dismiss control; the candidate resolves it through the
  Compass while unaffected actions remain available.
- The running Explore preview reuses the existing workspace-owned snapshot and
  stores a configurable bounded preview (nine rows by default) before completion. The task
  status response deliberately excludes job URLs, provider external IDs,
  selection controls, and action links.
- First-party published vacancies remain candidate-side evidence only. The
  `Own` badge does not expose candidate activity to the poster or create an
  employer-side ranking.
- Candidate-facing legal and workflow pages use the WorkLifeBalance name. The
  operator/package identity and the actual controller details remain launch
  items; a display-name cleanup is not a substitute for a real imprint or legal
  review.
- Public self-registration remains out of scope. Before it is considered, the
  hosted launch record must include server-verified Turnstile, registration
  rate limiting/challenges, origin restriction, monitoring, and an abuse/recovery
  process tested against the real deployment.
- Product feedback is an explicit authenticated data route with user-side
  review/deletion, account-deletion coverage, finite retention, and admin-only
  triage. Its form warns against job URLs, Compass/CV/application content,
  diagnostics, secrets, and third-party data; it is not sent to AI, analytics,
  or advertising.
- Persisted admin roles replace the mutable operator allowlist after the first
  database admin exists. Tester access is orthogonal to admin and job-poster
  capabilities. Privileged access changes require password re-confirmation and
  cannot strand non-admin accounts without an administrator.
- The deployable Compose topology publishes no origin web port. Cloudflare
  Access exact-email policy, Tunnel-only ingress, external origin-negative
  tests, backup/restore evidence, and operator confirmation remain launch gates,
  not properties inferred from a source archive.

See the [v0.7.2h release notes](../../engineering-history/release-notes/release-notes-v0.7.2h.md) for the complete
product contract. The feedback route changes the Privacy draft; no new LLM data
route or legal-readiness approval is created by this release.

## v0.7.2i source, rating, cost, and worker boundary

- Explore posting dates remain attached to a vacancy identity that retains
  meaningful query parameters. Only labelled posting/creation evidence is
  presented; generic update or page-age metadata cannot claim that an old
  vacancy is new.
- A manually recoverable import remains linked to its originating Explore
  snapshot. Its Add handoff prefills only a credential-free HTTP(S) source and
  asks the candidate to paste public advertisement text; it does not bypass
  robots.txt or fetch a prohibited source.
- Job and employer ratings are private emotional Compatibility inputs. They do
  not enter Compass integrity, create a Compass-boundary disposition, or create
  a new external provider purpose. Quickscore remains a local projection over
  already stored evidence.
- The AgentX All Jobs actor has a separate USD monetary run ceiling. Dataset
  `maxItems` is documented only as a readback/presentation bound; it is not
  represented as the pay-per-event cost control. Other providers retain their
  independent limits and permissions.
- Hosted background work uses a dedicated worker, claim fences, heartbeat,
  lease expiry, and owner/persona-scoped cancellation. Web restarts no longer
  own the task lifetime. Hard process loss remains at-least-once and can repeat
  a bounded external call, so spend caps, idempotent authoritative writes, and
  operational monitoring remain required.
- The server begins with a fresh PostgreSQL database. The release authorizes no
  transfer of local personas, Compass/CV data, job history, ratings, uploads,
  `.env`, SQLite files, or backups.

See the [v0.7.2i release notes](../../engineering-history/release-notes/release-notes-v0.7.2i.md) and
[current private-alpha deployment runbook](../../engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md).
They provide an executable engineering path, not evidence that Netcup,
Cloudflare Access, backups, legal review, or tester invitations are complete.

## v0.7.2j cancellation and private-correction boundary

- Cancellation becomes terminal immediately and fences any result returned by
  an already-started provider call. It does not claim that an HTTP request
  already accepted by an external processor can be remotely withdrawn.
- Progress from zero through 94 percent is explicitly a presentation estimate;
  persisted task status, evidence, cost events and terminal state remain the
  authoritative record.
- A manually pasted job can be matched alone under the same active-account,
  persona-grant and Compass-integrity checks as other Match actions. No new
  provider purpose or cross-persona data path is introduced.
- Employer-name and other Job Detail overrides remain private evidence. They
  alter the candidate-facing effective presentation but do not rewrite the
  extracted advertisement or disclose corrections to an employer.

See the [v0.7.2j release notes](../../engineering-history/release-notes/release-notes-v0.7.2j.md) and
[current deployment runbook](../../engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md).

## v0.7.2k test-portability boundary

- The release changes no candidate-data route, retention rule, provider
  purpose, Matching rule, account boundary, database schema, or hosted runtime
  behavior.
- Portable link-fixture coverage and explicit Windows-junction rejection retain
  the source-archive confidentiality boundary on the operator's Windows host.
- The portable SIGINT test repairs a false-negative harness; it does not create
  a new claim about remotely cancelling an already accepted provider request.

See the [v0.7.2k release notes](../../engineering-history/release-notes/release-notes-v0.7.2k.md) and
[current deployment runbook](../../engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md).

## Launch status

| Gate | Status | Evidence required |
| --- | --- | --- |
| Controller/imprint identity | Blocked | Legal operator/form, service address, public contact, and any applicable register/VAT/representative details |
| Product boundary accepted | Draft complete | Dated operator signature in the launch record |
| ROPA and lawful bases | Draft complete | Counsel/DPO review and corrections |
| DPIA | Open | Owner approval after residual-risk review; prior consultation if residual high risk cannot be reduced |
| Processor review | Open | Executed contracts, account configuration screenshots/exports, subprocessor and transfer review |
| Retention implementation | Code complete; operational evidence open | Automated job test, oldest-record sample, Caddy adapted-JSON request-filter check, resolved Compose log-rotation check, backup expiry, and provider-side deletion evidence |
| DSR procedure | Draft complete | Dry run against a staging account and backup/provider follow-through |
| Incident procedure | Draft complete | Named contacts, notification channel, tabletop exercise |
| Backup restore | Open | Encrypted off-server backup and documented restore drill |
| Public legal pages | Blocked | Real operator details, final provider/configuration inventory, external legal approval |

Do not enable invitations or put the service online for testers until every
launch-record item is truthfully complete.
