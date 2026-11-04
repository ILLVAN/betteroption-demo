> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1o-local-quality

v0.7.1o is a localhost quality and control release. It keeps the candidate in
control, verifies discovery results before they can be selected, and makes
single-job review usable without treating a local development build as a
public-alpha approval.

## What changed

- Explore now performs a bounded, fail-closed availability and page-plausibility
  pass before showing web results. Recognised phishing/suspended-domain,
  404/error, category/search, editorial/listicle and non-vacancy pages are
  rejected rather than deferred until Matching. Focused query bundles and a
  longer background budget favour verified individual vacancies over a fixed
  result count.
- Exa remains preferred and Brave remains a secondary source. You.com Search is
  available as an optional direct REST provider, using the same account-level
  permission, operation ledger, timeout and cost rails as the existing sources.
- Primary actions use one continuous pink-to-teal treatment across Home,
  Compass, Add, Explore, Match, Apply and Archive. The Home recommendation no
  longer renders a Python method representation, Apply highlights the explicit
  provider permission and create action, and Match cannot start without both a
  usable Compass and jobs.
- Background workflows explain that careful retrieval or matching normally
  takes several minutes and remains safe to leave while it continues. The
  230-second default is the Explore source-mesh stage budget, not a hard
  end-to-end SLA: queue time, a retry, final persistence and already-running
  network requests can extend the stored task beyond four minutes.
- The per-persona “update Compass from skill changes” choice persists. Effective
  evidence tiles distinguish good, check, blocker and unresolved outcomes after
  rematching, while the “in Compass” marker follows the current Persona Compass
  instead of becoming stale.
- Explicit remote-only roles skip address-routing waits. Their compact,
  traceable mobility result receives partial positive credit when remote work is
  allowed; an explicit remote exclusion can still block the role.
- Job Detail keeps Cover Letter and asynchronous single-job Match actions
  visible. A single-job refresh returns to that job, and the main Match view
  warns when its results contain different refresh ages.
- Prepare Package extracts broader source-published application details,
  including a published postal address where available. Contact/process fields
  remain local, editable and attributable; they are not included in the OpenAI
  job-analysis payload and never contact or apply to an employer.
- The changed provider-minimisation boundary is traceable as `job-v0.7.1o`,
  `application-draft-v0.7.1o` and `salary-research-v0.7.1o` in the local
  invocation ledger.
- Database migration `0029_job_detail_preferences` stores the new per-persona
  Job Detail preference.

## Provider and cost boundary

You.com Search is optional. Configure `YDC_API_KEY` only for a key you intend to
use, then allow or disable the provider on the Account page. Its configured
per-call price must be a number. A numeric `0` means **used but
unpriced/unknown**—never free. Empty numeric provider-price values remain
invalid.

For a later hosted rollout, You.com and every other enabled provider still need
the project’s processor/DPA, subprocessor, processing-location, transfer,
retention, deletion and incident-contact review. A configured key is technical
availability, not completion of that review.

## Why O does not add a general MCP search stack

SearXNG, MCPHub and general-purpose search MCP servers can be useful research
tools, but they do not by themselves verify that a URL is a live individual
vacancy, provide licensed access to restricted job boards, or fit
BetterOption’s per-account provider permission and per-request cost ledger.
v0.7.1o therefore extends the existing typed REST discovery boundary instead of
adding another local orchestration layer.

The release also does not scrape LinkedIn, Indeed, Stepstone or Glassdoor, and
does not claim access to their restricted data. Such sources require an
official/licensed integration and a separate contractual, technical and privacy
review. A user can still add a public URL or paste job text manually through the
existing candidate-controlled flow.

## Operating and legal boundary

The supported operating mode remains password-protected localhost at
`127.0.0.1`. This release is architecturally compatible with later hosting, but
does not authorize a server deployment or external alpha. A hosted rollout
still requires completed and current RoPA/lawful-basis/transparency work, DPIA
decision, processor and international-transfer review, retention/deletion
evidence, data-subject and incident procedures, security/restore evidence and a
final AI Act classification and transparency memo.

Warnings identify incomplete launch evidence without disabling legitimate
local product testing. Provider choices remain account-controlled, disabled
providers are not called, and no action automatically submits a job
application.

## Release identity

- Application: `0.7.1o-local-quality`
- Python package: `0.7.1+o.local.quality`
- Matching algorithm: `matching-v0.7.1o`
- Database head: `0029_job_detail_preferences`
- ZIP: `betteroption_v0_7_1o_local_quality.zip`
- Git tag: `v0.7.1o-local-quality`

Use [the complete local backup, install, acceptance and GitHub guide](../local-guides/local-quality-v0.7.1o.md).
