> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# Roadmap to closed alpha and public release

Status for `v0.7.2k` · 5 August 2026

This is the current evidence-gated roadmap. The near-term deployment goal is to
put the product online behind login with public registration closed. That first
online state is an **owner-only rehearsal**, not yet the friend alpha. Exact-
email invitations for a very small group of trusted friends begin only after
both cost/business and restricted-deployment gates pass. The directional public
release window is October–November 2026, roughly two to three months away, but
an exit gate wins over a calendar date.

## Exposure stages

| Stage | Who can enter | Purpose |
| --- | --- | --- |
| Owner-only online rehearsal | Operator account only; invitations disabled | Deploy, measure cost, restore and roll back without tester data |
| Closed friend alpha | 5–10 named invitees | Observe real end-to-end use and relevance failures under a hard spend cap |
| Expanded private alpha | Up to 30 named invitees | Confirm fixes, support load, retention and unit economics |
| Public release | Publicly available product with deliberate registration and pricing | Operate a supportable, scalable service rather than an experiment |

Friend participation and low visibility reduce exposure; they do not make
security, privacy, provider contracts or source rights disappear. Provider
choices therefore remain independently switchable, and hosted activation is an
explicit operator decision. Paying an intermediary for scraped data does not by
itself transfer every responsibility to that intermediary.

## Version sequence

| Target | Product outcome | Exit evidence | Exposure |
| --- | --- | --- | --- |
| **0.7.2d** | Interaction and ranking closeout: instant local Quickscore, provider-neutral Explore order, nonlinear distance control, exclusion warnings, calmer progress/footer copy and restart-safe local background tasks | Product regression gate passed, but the handed-off archive was withdrawn because its Python distribution version was not PEP-440-valid | Not released |
| **0.7.2e** | Installable packaging hotfix containing the unchanged `0.7.2d` product behavior | Canonical PEP-440 metadata; editable install from the source archive; full regression and archive gates | Localhost |
| **0.7.2f** | Candidate-facing data minimisation and handoff quality: compact profile export, clearer Compass actions, local provider filters with merged provenance, individual-vacancy/readiness gates, recoverable import failures and evidence-bound semantic relations for unresolved Match criteria; naming reviewed without a UI rename | Portable export omits operational histories while internal diagnostics remain intact; all sources use the same structural gate; filters spend no requests; deterministic Matching wins and only a validated medium-confidence hard contradiction can block; package, regression and archive gates | Localhost |
| **0.7.2g** | Live ranking and search guidance: authoritative animated Match reordering, action-specific Compass integrity, synchronized guided/widget projections, progressive Explore Top 7, first-party `Own` jobs and calmer candidate copy; naming reviewed again without a UI rename | Score/group invariant and multi-job employer rescoring; no stale back-navigation layout; server-enforced high-signal contradiction gates without a per-page LLM call; incomplete preview evidence stays neutral; no preview links/IDs; own published jobs enter the same ranking; package, regression and archive gates | Localhost |
| **0.7.2h** | Private-alpha and lifecycle closeout: rating-driven reranking is consistent across candidate surfaces, Match creates an explicit `Matched` lifecycle state, preview depth is configurable, and database-backed admin/tester roles plus private product feedback prepare controlled trials; the Netcup/Cloudflare, naming and business boundary is documented without a UI rename | Confirmed ratings are never rolled back by a later projection failure; only the evaluated jobs move to `Matched` and later application states remain intact; first-user ownership is claimed atomically, the last admin cannot be removed, tester entitlement is separate from authority, feedback remains account-owned, and the tunnel-only deployment contract has no public Caddy ports | Localhost; deployment-ready owner rehearsal only |
| **0.7.2i** | First-server reliability and cost closeout: vacancy-bound posting dates, source-specific manual recovery, score-only emotional ratings, honest conflict-safe Quickscore, leased/cancellable durable work, a dedicated hosted worker, and a real All Jobs monetary cap | Date/URL association and multilingual parser contracts; ratings never alter Compass integrity or boundary disposition; concurrent local projections preserve the newest confirmed rating; fresh leases cannot be stolen; expired work is recoverable; web restarts do not stop the separate worker; no fake 94%; All Jobs provider-only caps; clean-server deploy/restore runbook | Localhost plus deployment-ready clean owner rehearsal; live acceptance still open |
| **0.7.2j** | Final local task/manual-input hardening before the first server rehearsal: reload-stable slow Explore progress, immediate fenced cancellation, bounded local shutdown, durable cross-process provider reservations, effective override headers, and one-job Matching directly from a pasted Job Detail | Only success reaches 100%; cancellation is terminal and late writes lose their claim; one Ctrl+C is not held by provider threads; restart/concurrent processes cannot bypass daily/action budgets; URL-free and URL-backed manual jobs can create or merge a one-job current-algorithm run; persona access is enforced; every overridden comparison preserves but greys/strikes only the automatic value; SHA-first/symlink-free packaging and complete noob-level Netcup/Cloudflare/GitHub runbook | Localhost; final clean-owner deploy candidate, live infrastructure acceptance still open |
| **0.7.2k** | Windows test-portability hotfix over the accepted `j` product: exercise link rejection without requiring symlink privilege, reject Windows directory junctions, and trigger the registered SIGINT handler portably | The two formerly red Windows nodes pass without weakening archive protection; no app, Matching, prompt, provider, schema, or deployment behavior changes; no full-suite claim is made by the handoff | Localhost; same clean-owner deploy candidate as `j`, live infrastructure acceptance still open |
| **0.7.3** | Cost truth and rough business decision | Ten-run calibration; every paid source priced; median/p90 workflow cost; marginal provider yield; baseline/expanded bundle; closed-alpha cap; EUR 4/EUR 8 hypotheses accepted, changed or rejected; three demand scenarios | Localhost plus owner-only hosted probes |
| **0.7.4** | Reproducible restricted deployment | Tagged EU-host deploy; HTTPS-only origin boundary; invite-only registration; PostgreSQL migration; durable worker; monitoring; encrypted off-server backup; timed restore and rollback rehearsal | Online, operator only |
| **0.7.5** | First closed friend alpha | `0.7.3` and `0.7.4` gates both complete; five named users invited in a small first batch; onboarding, known limitations, support contact, deletion path and spend/security stop conditions ready | Online, 5–10 friends |
| **0.7.6** | Product and economics iteration | At least two weeks of observed relevance, source yield, latency, failures, support and per-user cost; highest-impact problems fixed; no cross-account exposure; provider bundle retuned from evidence | Online, up to 10 friends |
| **0.7.7** | Expanded private-alpha candidate | Fresh-server restore; dependency/container/security review; retention/export/deletion/incident exercises; reviewed provider register and real operator/legal text; stable unit economics and support load | Online, up to 30 invitees |
| **0.7.8** | Public-release candidate | Public pricing and registration decision; payment/refund/tax flow if paid; mobile/desktop end-to-end smoke; load and budget-exhaustion drills; immutable deploy/rollback; no unresolved critical/high issue | Controlled dress rehearsal |
| **0.8.0** | Public release | Signed go/no-go record; staged traffic increase; daily operations review in launch week; rollback owner and public support channel active | Public |

`0.7.3` and `0.7.4` may be developed in parallel, but no friend invitation is
sent until both are complete. Returning online this or next week can therefore
promise only the owner-only rehearsal unless both gates actually finish; the
calendar does not silently convert that deployment into a tester launch.
`0.7.2k` carries the final `j` worker/cancellation and clean-server boundary,
but does not waive either later evidence gate.

## Closed-alpha gate

- [ ] Every tester enters through an expiring exact-email invitation.
- [ ] Public self-registration is disabled and direct origin access restricted.
- [ ] Exactly two named human admins exist before the first friend is invited;
      recovery is tested and no shared or duplicate admin identity is counted.
- [ ] Every enabled vendor is owned through a controlled business-domain
      mailbox, has real billing details, MFA/recovery, scoped credentials and a
      current spend alert.
- [ ] Provider daily and per-workflow operation/cost caps are non-zero and tested.
- [ ] Invited testers use the full test/max entitlement while server-side
      per-workflow, per-account, daily and deployment-wide safety budgets remain
      active.
- [ ] A complete Explore → Match run has a measured median and p90 cost.
- [ ] The payload-free provider-operation ledger reconciles every paid action;
      product quotas and billing are not inferred from raw result counts.
- [ ] Account/persona isolation and session revocation pass.
- [ ] The compact profile download and the separate complete DSR procedure are
      both exercised against a staging account.
- [ ] Backup, empty-server restore and one-release rollback are timed successfully.
- [ ] Logs and alerts contain no Compass/CV text, job bodies, URLs, queries,
      responses or keys.
- [ ] A human support/deletion/security contact and known-limitations note exist.
- [ ] Stop conditions name the operator who disables invitations and providers.

## Public-release gate

- [ ] The provider bundle is based on unique relevant yield and contribution
      margin, not raw result count.
- [ ] Pricing covers median and p90 repeat use in the agreed demand scenarios.
- [ ] Current provider prices, terms, DPA/subprocessors/transfers and source-use
      decisions are recorded for the exact enabled configuration.
- [ ] Real Privacy Notice, Terms and imprint/operator details are reviewed.
- [ ] Registration, verification, abuse/rate controls and account recovery are
      ready for unknown users.
- [ ] Transactional verification and recovery email uses a verified sender,
      authenticated domain, bounce/complaint handling and tested single-use,
      expiring token flows.
- [ ] A durable, retry-safe usage ledger can reserve, consume, release and
      reconcile every advertised plan unit before quotas or billing are enabled.
- [ ] Public registration uses server-verified Cloudflare Turnstile and a
      narrowly tested registration rate-limit/challenge rule; direct-origin
      access cannot bypass either control.
- [ ] Retention, export, deletion, incident response and provider disable drills
      have evidence.
- [ ] Monitoring, support response and backup/restore capacity match the launch
      scenario.
- [ ] There is no unresolved critical/high security, privacy or reliability issue.

The detailed measurement model is in
[`cost-and-business-plan.md`](cost-and-business-plan.md). The concrete private-
alpha topology, administrator count, vendor ownership and public-mail/billing
sequence are in
[`hosting-and-public-roadmap-v0.7.2i.md`](hosting-and-public-roadmap-v0.7.2i.md).
The compliance dossier remains the source of truth for hosted provider and
privacy decisions.

This roadmap is an engineering and operating plan, not legal, tax or accounting
advice.
