> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.9g — Contextual company and seniority evidence

v0.6.9g preserves the accepted interface, discovery mesh, persistent Explore
shelf, routing providers, database schema, and 25-slot private-alpha allowance.
Existing open jobs do not need to be imported again. Run Matching once to create
a v0.6.9g snapshot with the new evidence rules.

## Sensitive company categories

- Human-surveillance exclusions now require contextual product evidence such as
  video surveillance, CCTV, facial recognition, biometric monitoring, or
  person/employee surveillance.
- Generic operational monitoring, building telemetry, energy-centre monitoring,
  and equipment supervision no longer prove a surveillance-products conflict.
- Every positive or conflict assessment keeps the public evidence quote, URL,
  and confidence. Unknown remains Unknown when no attributable company source is
  available.

## Employer relationship

- Explicit staffing, employee-leasing, and recruitment evidence still overrides
  all other signals and can block an exclusion.
- A named hiring organization with attributed evidence of its own products or
  services, and no staffing/recruitment business category, is now assessed as a
  likely direct employer with medium confidence.
- The UI continues to tell the user to confirm the legal contract entity. The
  inference is not presented as legal proof.

## Seniority

- Matching combines explicit title labels, graduate/entry signals, stated years
  of experience, leadership responsibility, and individual-contributor scope.
- Plain individual-contributor roles with no minimum years or leadership duty can
  support junior compatibility with medium confidence; the formal grade remains
  unconfirmed.
- Explicit senior, lead, manager, graduate, junior, and internship evidence takes
  priority and remains linked to the verified job source.

## Test isolation and log quality

- Settings tests no longer inherit API keys or discovery-depth overrides from a
  developer's private `.env` file.
- Schema.org values that happen to look like URLs no longer emit BeautifulSoup's
  locator warning during Explore source processing.

## Upgrade

The release contains no `.env`, API key, database, profile, CV, or local corpus.
The included installer overlays the newest downloaded release and installs the
`dev` and `extraction` dependency groups while preserving local private data.
