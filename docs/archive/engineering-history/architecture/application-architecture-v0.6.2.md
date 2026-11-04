> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.2

## Purpose

v0.6.2 combines the planned provider foundation and first dashboard increment.
It keeps the current single OpenAI workflow while making provider and model
selection an application policy instead of a domain dependency.

## Boundaries

- Domain models and deterministic matching do not import FastAPI or OpenAI.
- `ModelPolicy` maps a task to a provider, model, and prompt version.
- `ProviderRegistry` constructs task-specific adapters at the composition root.
- `ApplicationContainer` is the shared composition root for CLI and web entry
  points.
- `DashboardService` returns view models and uses `JobRepository`; FastAPI routes
  never query SQLAlchemy rows directly.
- The v0.6.2 dashboard exposes only `GET` routes. Profile, job, and feedback
  mutations remain in proven application workflows until their web contracts
  are implemented and tested.

The current registry contains one OpenAI adapter. Adding another provider later
requires an adapter registration and a policy route, not changes to profile,
corpus, matching, or dashboard code.

## Model invocation telemetry

Every provider request records operational metadata:

- task, provider, model, and prompt version;
- attempt number and success/failure outcome;
- start/end time and latency;
- input, output, and total token counts when the provider reports them;
- optional estimated cost when explicit pricing configuration exists;
- exception type on failure.

Prompt text, response text, profile answers, CV content, and advertisement text
are deliberately excluded. Telemetry writes are fail-open: an observability
failure cannot block the user workflow.

No model price is hard-coded. Price metadata changes over time and must be an
explicit operator configuration before cost estimates are shown as money.

## Schema migration policy

Alembic migrations ship inside the Python package. A new local database is
upgraded to the current head automatically. An intact v0.6.0 corpus without an
Alembic marker is stamped at the v0.6.0 baseline and upgraded additively. A
partial legacy schema is rejected instead of being guessed or overwritten.

The v0.6.2 migration adds `model_invocations` and does not modify corpus data.
Downgrades exist for development, but application startup only moves forward.

## Dashboard experience contract

The home screen should feel like a personal place, not an operations console.
Its vocabulary is intentionally human:

- **Your compass** for the confirmed profile;
- **Open now**, **Closed**, and **Needs a recheck** for URL lifecycle;
- **Strong fit**, **Worth a look**, and **Outside your boundaries** for matching;
- **Technical history** only inside a collapsed disclosure.

The interface uses semantic landmarks, visible keyboard focus, a skip link,
responsive layouts, reduced-motion support, and no external visual assets or
tracking. Every opportunity links to its timestamped, reachability-verified
source URL.

