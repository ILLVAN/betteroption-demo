> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.7 Release Notes

## Outcome

v0.6.7 turns evidence into one coherent user story without changing the warm
visual language accepted in earlier testing.

## Delivered

- Bulk Review Tray controls with safe default selection and atomic persistence.
- One canonical Job Detail for unmatched and matched states.
- Full Compass reasons, quotes, evidence URLs, commute details, employer
  context, working-mode evidence, feedback, and application history on that
  page.
- Canonical employer-source replacement for LinkedIn and other restricted job
  platforms; no access-control bypass.
- Conservative direct-employer, staffing, and recruitment reasoning.
- Deterministic working-mode enrichment from verbatim advertisements.
- Google-first mobility chain with openrouteservice road/bicycle/walk fallback,
  provider diagnostics, attribution, and cache-policy enforcement.
- Clickable Home Compass counters.
- Local PDF/DOCX/TXT CV text extraction, explicit retention/deletion, no stored
  binary, and optional evidence proposals through the normal Review Tray.
- Alembic revision `0006_cv_documents`.
- Matching algorithm snapshot version `matching-v0.6.7`.

## Configuration

```dotenv
BETTEROPTION_MOBILITY_PROVIDER=auto
GOOGLE_ROUTES_API_KEY=
OPENROUTESERVICE_API_KEY=
BETTEROPTION_EMPLOYER_HOMEPAGE_RESEARCH=true
```

With no mobility key, matching still completes and commute evidence stays
unknown. A Google key can be added later without a database change.

## Privacy and legal-operational notes

- Google results are deliberately not persisted by the application.
- openrouteservice attribution is shown with every returned or cached result.
- Transitous is not called until its routing/commercial-use expectations have
  been agreed with the project.
- LinkedIn pages blocked by robots remain unreadable; users can replace them
  with the employer's public canonical source.
- Employer classification is evidence and confidence, not a legal guarantee.

## Upgrade

Back up `local-data/betteroption.db`, overlay the profile-free source archive,
activate the virtual environment, install `.[dev]`, and run the complete pytest
verification. Application startup upgrades the database automatically.
