> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1c-local-quality

`v0.7.1c-local-quality` revives the later `v0.7.1b-legal` source line as a
useful local job-search tool while preserving the account, invitation, legal,
retention, PostgreSQL, and deployment foundations for a possible private alpha.
It does not start a public listener, require a server, or claim that the online
legal and operational readiness gates are complete.

Python package version: `0.7.1+c.local.quality`  
Application version: `0.7.1c-local-quality`  
Database head: `0017_invitation_onboarding` (unchanged)

## Product-quality corrections

### Explore source quality

- `absolventa.de` and its subdomains are excluded because their search results
  repeatedly resolve to category/search pages rather than individual vacancies.
- The exclusion applies at Brave and Exa ingress, in Exa's upstream domain
  filter, centrally before coverage/ranking, and when an older saved Explore
  snapshot is read.
- Removing an excluded saved result also recomputes the visible regional count;
  an excluded primary result cannot suppress the conditional Exa fallback.
- Malformed Exa URLs are rejected per result without discarding valid results
  returned in the same provider response.

### Reference-job learning

- Enabling learning now produces visible Compass Review Tray suggestions
  immediately after a reference job is saved.
- Suggestions remain inactive until the user confirms them. Reference learning
  cannot silently create a must-have or exclusion.
- Only positive user notes can create suggestions. Negative notes remain attached
  to the reference for human use; turning one into an exclusion requires a
  separate deliberate Compass action.
- Suggestions use the selected scope and evidence-backed job facts. Model-written
  top-level title or location fields are not mislabeled as verified evidence.
- Re-saving a reference is idempotent, reviewed decisions are protected, and a
  pending suggestion supported by two references survives removal of either one.

### Matching semantics

- `international`, `internal`, and `internet` no longer match the standalone
  seniority marker `intern`; real internship markers remain supported.
- Generic building, equipment, cloud-security, and operational monitoring do not
  imply people surveillance.
- German compounds for explicit video/person surveillance remain sensitive.
- Generic cyber defence does not imply military products; explicit armed-forces,
  weapons, military-customer, or defence-product context still does.
- Negation is evaluated near the relevant phrase instead of suppressing an
  unrelated affirmative category elsewhere in the sentence.

### Multi-location routing

- Matching derives every evidence-backed advertised workplace instead of routing
  one opaque multi-location label.
- Each travel mode compares the available workplaces and selects its shortest
  confirmed route; two precise offices in the same city remain distinct.
- Generic city placeholders are superseded only when a more precise candidate for
  that same city is available.
- `Frankfurt an der Oder` is preserved as a place name rather than split on
  `oder`.
- A failed or deliberately capped alternative makes an otherwise over-limit
  result unknown rather than a false hard blocker.
- Partial failures have the same neutral state in match logic and presentation,
  and provider messages remain within the persisted model limit.

## Local revival

- `.env.example` explicitly selects the local environment, SQLite, local auth,
  insecure localhost cookies, and `127.0.0.1` only.
- `scripts/bootstrap_local.ps1` creates a Python 3.12 virtual environment,
  preserves or creates `.env`, installs dependencies, validates configuration,
  and creates or migrates the local SQLite database without making the app public.
- The overlay installer accepts an exact archive path and can verify the expected
  installed version. It rejects runtime `.env` files, databases, keys,
  certificates, uploads, backups, and local profile data.
- The release builder and Git push helper apply the same secret/private-data
  boundary. The push helper also includes `pyproject.toml` in the release commit.

See [Local revival and provider setup](../local-guides/local-revival-v0.7.1c.md) for the full
fresh/upgrade path, provider-key setup, diagnostics, tests, and later private-alpha
handoff.

## Release validation

- 379 automated tests passed.
- Ruff formatting and lint checks passed.
- Python bytecode compilation passed.
- A fresh SQLite database passed local application, home-page, liveness, and
  readiness smoke tests without calling an external provider.
- The packaged source is scanned for runtime environment files, databases,
  private-data directories, API keys, and certificates.

The PowerShell helpers are covered by package-safety tests and static review.
They could not be executed natively in the Linux release environment, so the
first Windows run remains an explicit acceptance step in the revival guide.

## Explicit non-goals

The earlier roadmap used the short name `v0.7.1c` for monitoring, alerts,
encrypted off-server backups, and a restore drill. This distinctly named
`v0.7.1c-local-quality` release does not claim those operational gates. They
remain required before a real private alpha, together with truthful legal and
processor review.

The existing legal pages and compliance dossier remain engineering drafts, not
legal advice or completed approval.
