> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.2h

`v0.7.2h` turns the local `g` experience into a private-alpha-ready build while
keeping the candidate-facing name, design, colour system, and storyline
unchanged. WorkLifeBalance remains the product name and `betteroption.example`
remains the ship-now domain.

## Ratings that cannot lie about being saved

- Job and employer ratings are committed before any Quickscore or layout
  projection. A later rescore, repository, or browser-layout problem can warn
  that ranking refresh is pending, but it can no longer undo the visible stars
  or report that a durable rating failed.
- Home, Matching, Archive, and job detail use server-authoritative score,
  disposition, and order data. Home and Archive now have the same reordering
  hooks as Matching; same-employer controls stay synchronized while a request
  is active.
- Every ranked/rating surface uses `no-store` and reloads a browser back/forward
  cache restoration. A Home card whose new disposition no longer belongs on
  Home is removed by a safe reload; Archive keeps the blocked job in its fresh
  server order.
- Browser animation remains short and respects reduced-motion preferences.

## A clearer pre-application lifecycle

- A job actually evaluated in a full or single-job Match run moves from
  `Discovered` to the new `Matched` stage in the same transaction that stores
  the run. It receives one idempotent `Match` history event.
- Cached or merely reused rows are not advanced, and every later manual state
  remains untouched.
- The legacy stored value `saved` remains compatible but is now presented as
  `Shortlisted`. The progression reads `Discovered → Matched → Shortlisted →
  Preparing → Applied`, followed by the existing outcome states.

## Private-alpha ownership and access

- Migration `0031_private_alpha_roles_feedback` adds persisted account role and
  access-tier fields, one transactional owner-bootstrap row, and product
  feedback storage.
- The first account in `first_user` mode claims the owner slot atomically and is
  an admin. In staging or production that account's normalized email must be in
  `BETTEROPTION_OPERATOR_EMAILS`; local setup remains convenient.
- A migrated installation with no database admin may use an already existing
  allowlisted account as a one-time Operations bridge. As soon as any persisted
  admin exists, database roles are the sole authority.
- Operations shows expandable account details. A current admin can assign the
  independent `tester` access tier or admin role only after re-entering the
  current admin password. Job-poster approval stays a separate capability.
- The only remaining admin cannot be demoted or deleted while other accounts
  would be stranded. A sole owner may still delete the final account and leave
  a genuinely empty workspace that can be bootstrapped again.
- Deployment preflight now inspects only aggregate account state. A fresh
  `invite_only` database, a non-empty `first_user` database, or an existing
  database with neither admin nor allowlisted bridge is blocked.

## Private tester feedback

- Authenticated testers and members receive a polished WorkLifeBalance feedback
  form with category, product area, optional 1–5 rating, message, and optional
  follow-up permission. The form explicitly asks for no job URLs, Compass/CV or
  application text, diagnostics, secrets, or information about another person.
- A user can review and delete their own feedback. Operations can triage it as
  new, reviewed, planned, or resolved, add an operator note, and export a
  spreadsheet-safe CSV.
- Feedback is included in the private complete account graph, removed with the
  account, and covered by a default 180-day retention rule. It is never routed
  to AI, analytics, or advertising.
- The Privacy draft becomes `2026-08-05-feedback-draft`. This release adds a
  deliberate feedback data route, not a new LLM data route.

## Explore and Compass details

- Progressive Explore now displays up to nine current leaders by default. The
  limit is configurable with `BETTEROPTION_EXPLORE_PREVIEW_LIMIT` and validated
  between 3 and 12; preview cards remain non-clickable and evidence-neutral
  until the final result exists.
- The manual-readiness badge is shortened to `Needs pasted text`, with the
  fuller explanation retained in its tooltip.
- The non-dialog Compass integrity notice no longer offers or explains `Ask me
  later`. The useful option remains inside Guided Setup, where it actually
  defers a guided question.

## Tunnel-only private staging boundary

- Compose no longer publishes Caddy on host ports 80/443. `cloudflared` is
  pinned, uses an outbound remotely managed Tunnel, and receives its connector
  token only through an ignored mode-`600` Docker-secret source file.
- Caddy serves internal HTTP only, behind the Tunnel, and the app keeps its own
  account authentication behind Cloudflare Access.
- The executable runbook requires the exact-email Access application before the
  hostname route, `Protect with Access`, the route `http://caddy:80`, direct
  origin 80/443 negative tests, and an Access-authenticated health monitor.
- The delivered stack is deployment-ready, not deployed. Cloudflare policy,
  DNS/Tunnel route, Netcup server order, secrets, and live negative tests remain
  explicit operator actions.

See the
[Netcup + Cloudflare private-alpha runbook](../deployment/netcup-cloudflare-private-alpha-v0.7.2h.md)
and the [hosting/public roadmap](../../discontinued-product-planning/hosting-and-public-roadmap-v0.7.2h.md).

## Naming, hosting, and business gates

- All 23 current domain candidates are compared without changing product UI or
  deployment names. The current top six are `betteroption.example`,
  `suiting.work`, `lifelife.work`, `balancedwork.life`, `movingon.work`, and
  `geta.life`.
- `suiting.work` is the only new candidate worth a defensive purchase and blind
  test if its renewal price is confirmed. The `.jobs` options are clearer as a
  category but materially more expensive and narrower as a product identity.
- Netcup VPS 500 G12 remains the default host. OVH VPS-1 is the only meaningful
  low-cost fallback found; migration has no present advantage over the tested
  Netcup path.
- One owner admin is enough for the owner-only rehearsal. Before inviting a
  friend, use exactly two named human admins and test recovery; creating five
  admins would add attack surface without useful resilience.
- Business-owned provider accounts/mailboxes and billing, transactional email
  verification, measured usage ledgers, configurable plans/quotas, notification
  consent, and billing remain public-launch gates. Private testers retain the
  full experience under hard provider and global spend ceilings rather than
  speculative product limits.

See the [complete naming decision](../../discontinued-product-planning/domain-name-decision-v0.7.2h.md) and
[cost/business plan](../../discontinued-product-planning/cost-and-business-plan.md).

## Release identity and migration

- Application/source release: `0.7.2h`
- Python distribution: `0.7.2+h`
- Matching algorithm: `matching-v0.7.2h`
- Match-evidence prompt: `match-evidence-v0.7.2h`
- Archive: `betteroption_v0_7_2h.zip`
- Git tag: `v0.7.2h`
- Database migration head: `0031_private_alpha_roles_feedback`
- Privacy draft: `2026-08-05-feedback-draft`

Existing accounts receive `member` and `standard` defaults. No legacy account
is silently guessed to be an admin; the documented zero-admin allowlist bridge
exists for that one upgrade case. Existing jobs, personas, Compass facts,
ratings, applications, provider diagnostics, and historical lifecycle values
remain compatible.
