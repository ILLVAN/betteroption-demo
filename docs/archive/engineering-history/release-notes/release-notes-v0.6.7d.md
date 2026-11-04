> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.7d Release Notes

v0.6.7d is an evidence-quality release. It preserves the warm interface and
canonical Job Detail while adding the context needed to understand the employer,
not merely the vacancy.

## Delivered

- company product/revenue profiles with source quotes, URLs, confidence, and
  sensitive-category signals;
- employer-reputation summaries with optional independent certification links;
- a legally conservative Kununu path: employer-republished scores only,
  otherwise a manual check and explicit no-scraping notice;
- existing official Entgeltatlas salary orientation next to the new company
  context;
- job-specific “Why still apply?” copy built from saved strengths, conflicts,
  and unknowns;
- Explore ordering by visible 70% local proximity and 30% keyword relevance;
- offline GeoNames city resolution, so origin labels are not sent to another
  geocoder during discovery;
- normal-Tuesday 08:00 Europe/Berlin commute comparisons, seven Transitous
  alternatives, shortest-valid selection, and fresh cache fingerprints;
- regression tests for ranking, holiday avoidance, product/reputation evidence,
  and company-category exclusions.

## Explicit boundaries

- BetterOption does not scrape Kununu, Glassdoor, LinkedIn, or other restricted
  platforms.
- Independent employer awards are signals, not proof of an individual team's
  culture.
- Straight-line distance orders Explore only; it is not a commute claim.
- Entgeltatlas ranges are occupation benchmarks, not advertised or predicted
  offers from a particular company.
- Product classification is evidence-backed but cautious. Unknown stays unknown.
