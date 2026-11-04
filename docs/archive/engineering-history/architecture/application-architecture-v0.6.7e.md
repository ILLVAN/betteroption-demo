> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.7e

## Scope

v0.6.7e is an evidence-reliability release. It preserves the accepted page story
and visual design while tightening mobility precision, company research,
exclusion enforcement, and Compass-driven Explore ranking.

## Mobility precision contract

A route duration is useful only when its endpoints have enough precision.

- When origin and destination resolve to the same city and both labels are only
  city-level, Matching returns `needs_precise_location`. It does not call the
  route provider or invent a local commute.
- The user can make the route meaningful by adding a district, postcode,
  station, or street.
- When two different cities are supplied without addresses, Transitous uses a
  rail-hub benchmark and labels it `rail_hub`. It is not presented as
  door-to-door time.
- Google Routes remains the preferred production provider once configured.
  Transitous remains a best-effort private-alpha fallback.

The cache fingerprint prefix is `mobility-v0.6.7e`, so older city-centroid
estimates cannot silently survive this contract change.

## Company-research boundary

`CompanyIntelligenceService` merges three inspectable evidence classes:

1. the verified advertisement;
2. an employer-controlled homepage when the source domain identifies the
   employer;
3. attributed company-research hits.

The keyless research adapter uses the documented MediaWiki Action API and keeps
the source article URL. Optional Brave Search adds bounded business-context and
independent employer-certification results. Search snippets and encyclopedia
summaries remain attributed evidence, not hidden model knowledge.

Sensitive product categories can resolve explicit Compass exclusions. A proven
defence, staffing, recruitment, or consulting exclusion is Blocked even when it
is the only conflict. Unknown company activity stays unknown.

Employee-review platforms are not scraped. Job Detail offers manual Kununu and
Glassdoor profile searches and shows attributed certification signals when
available. It does not claim that a missing or old score is current.

## Compass-aware Explore ranking

Compass search carries structured desired terms, exclusions, and target
seniority in addition to the human-readable search text.

For resolvable places:

`Explore rank = 55% proximity + 45% Compass role fit`

Role fit is 70% title-weighted keyword evidence and 30% seniority evidence when
a seniority target exists. Possible exclusion phrases reduce the preliminary
role-fit score. Explicit title-level conflicts such as a Senior, Lead, or Manager
role against a Junior target are placed after compatible results, with at most
two retained as transparent stretches.

Explore remains discovery rather than final matching. Salary, exact commute,
company activity, and complete job evidence are verified only after selection.

## Persistence and privacy

No migration is required. Company intelligence, route precision, and search
ranking metadata use existing JSON snapshots or transient discovery models.
Wikimedia and Brave receive only the public company name. Local GeoNames
resolution keeps Compass origin labels out of Explore geocoding requests.
