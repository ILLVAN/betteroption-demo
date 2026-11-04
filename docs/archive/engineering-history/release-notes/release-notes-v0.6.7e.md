> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.7e Release Notes

v0.6.7e fixes four quality failures observed in real local testing without
changing the warm interface.

## Delivered

- same-city city-level commute pairs now request a district, postcode, station,
  or street instead of displaying a misleading exact duration;
- different city-only Transitous routes are explicitly labelled rail-hub
  benchmarks and receive a fresh cache fingerprint;
- Kununu is presented as a current manual review-profile link, not an unreliable
  score placeholder; Glassdoor is linked as a second manual review source;
- keyless attributed Wikimedia company summaries plus optional Brave company
  research feed product and sector classification;
- researched staffing and recruitment activity also informs the contractual
  employer assessment;
- one proven exclusion is enough for a deterministic Blocked result;
- Compass search transports structured seniority and exclusion intent into
  Explore;
- title-weighted role fit and seniority evidence prevent explicit senior, lead,
  principal, or manager jobs from crowding a junior search;
- Explore cards disclose role-fit, seniority, proximity, and possible exclusion
  signals;
- regression coverage for route precision, Wikimedia attribution, researched
  staffing, hard exclusions, and junior-role ordering.

## Explicit boundaries

- City-level routing is a benchmark, not door-to-door evidence.
- Wikimedia and Brave results remain attributed public evidence; absence of a
  result does not prove a company is safe or unsafe.
- BetterOption does not scrape Kununu, Glassdoor, LinkedIn, Indeed, or other
  restricted sites.
- Explore ranking is preliminary. Final exclusions use verified job and company
  evidence after the job has been selected and archived.
