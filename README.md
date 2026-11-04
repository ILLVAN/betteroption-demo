# BetterOption

**Job discovery and matching with traceable evidence — a discontinued POC/MVP.**

BetterOption explores an end-to-end job-search workflow: turn natural-language
preferences into an editable profile, discover vacancies, inspect why they match,
compare commute evidence, and prepare application material. The interface uses
the name **WorkLifeBalance**.

Development is discontinued. This repository preserves the technical prototype
for code review and local evaluation. No supported hosted demo or active product
roadmap is offered.

## What the prototype demonstrates

- **Structured AI workflows:** model-proposed facts retain source quotes and
  uncertainty; user corrections and confirmed boundaries remain authoritative.
- **Explainable matching:** Python computes scores from versioned evidence,
  with optional bounded semantic checks for unresolved criteria.
- **Multi-source discovery:** independent provider adapters, deduplication,
  source attribution, deadlines, and partial-failure handling.
- **Durable background work:** database-backed tasks with leases, heartbeats,
  cancellation, retry limits, and commit fencing.
- **Practical data engineering:** SQLAlchemy repositories, Alembic migrations,
  source revisions, result snapshots, and account/persona isolation.
- **Operational visibility:** provider permissions, persistent budget
  reservations, cost estimates, diagnostics, and an operations interface.

## Explore the implementation

| Area | Source entry points |
| --- | --- |
| Application composition and HTTP interface | [container.py](src/betteroption/container.py), [web/app.py](src/betteroption/web/app.py) |
| Profile extraction and user review | [profile_workflow.py](src/betteroption/profile_workflow.py), [profile_integrity.py](src/betteroption/profile_integrity.py) |
| Matching and persisted results | [matching.py](src/betteroption/matching.py), [results.py](src/betteroption/results.py) |
| Discovery and provider adapters | [discovery_sources.py](src/betteroption/discovery_sources.py), [providers](src/betteroption/providers) |
| Task execution and provider budgets | [background.py](src/betteroption/background.py), [operations.py](src/betteroption/operations.py) |
| Commute evidence | [mobility.py](src/betteroption/mobility.py), [geography.py](src/betteroption/geography.py) |
| Server-rendered UI | [templates](src/betteroption/web/templates), [static assets](src/betteroption/web/static) |
| Regression coverage | [tests](tests) |

The stack is **Python 3.12, FastAPI, Jinja2, Pydantic, SQLAlchemy, and Alembic**.
Local development uses SQLite; the retained container configuration also
supports PostgreSQL and a separate worker. The UI uses plain JavaScript and CSS.

## Workflow and UI

**Compass → Explore → Match → Job Detail → Apply / Archive**

Compass makes preferences editable; Explore presents source-attributed
candidates; Match exposes evidence and trade-offs. Job Detail supports private
corrections and ratings. Apply prepares material and tracks progress; the
prototype does not submit applications automatically.

See the [UI walkthrough](docs/ui-walkthrough.md) and
[architecture guide](docs/architecture.md) for routes, data flow, and limitations.

## Run locally

On Windows 11, install Python 3.12 and Git, then run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_web.ps1
```

Open <http://127.0.0.1:8000>. Bootstrap creates a local virtual environment and
copies `.env.example` only when `.env` does not exist. Provider-dependent
features require your own configuration; keyless public sources may still make
network requests. Use the [local development guide](docs/local-development.md)
for manual setup, tests, and offline inspection.

## Provider integration

External services are optional and configured through environment variables.
Adapters cover structured extraction, web/ATS discovery, and routing. Provider
availability and pricing can change; integration code is retained as prototype
work rather than a guarantee that every external service remains compatible.

The All Jobs adapter distinguishes a **120-item readback/presentation guard**
from its **USD 0.40 pay-per-event charge ceiling**. These are retained
configuration defaults, not a statement of current vendor prices. See
[provider boundaries](docs/provider-integration.md).

## Verification and release identity

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_release.ps1
```

The script runs formatting checks, lint, tests, and bytecode compilation.
See [local development](docs/local-development.md#verification) for individual checks.

| Identifier | Preserved value |
| --- | --- |
| Application | `0.7.2k` |
| Python package | `0.7.2+k` |
| Matching algorithm | `matching-v0.7.2i` |
| Database head | `0033_background_task_leases` |

For a historical source-ZIP overlay, verify its trusted SHA-256 with
`Get-FileHash` before invoking `install_latest_release.ps1`; the installer
requires `-ExpectedSha256`. Full commands are in the
[local development guide](docs/local-development.md#historical-source-zip-overlays).

## Documentation and data

- [Technical documentation](docs/README.md)
- [Architecture and engineering trade-offs](docs/architecture.md)
- [Local setup and verification](docs/local-development.md)
- [UI walkthrough](docs/ui-walkthrough.md)
- [Provider integration](docs/provider-integration.md)
- [Dataset provenance](src/betteroption/data/nuts-2024.PROVENANCE.md)

Historical engineering records and discontinued product-planning drafts are
separated under [docs/archive](docs/archive/README.md). They describe earlier
checkpoints and are retained for traceability.
