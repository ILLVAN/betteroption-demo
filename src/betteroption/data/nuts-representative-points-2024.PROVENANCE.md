# NUTS 2024 representative points: provenance and permitted use

This file documents `nuts-representative-points-2024.csv`.

## Sources and version

- NUTS codes and region names are joined to BetterOption's official NUTS 2024
  classification (`nuts-2024.csv`), derived from Commission Delegated
  Regulation (EU) 2023/674 and the consolidated Regulation (EC) No 1059/2003.
- Place names, GeoNames IDs and WGS84 coordinates were transcribed on
  2026-08-03 from the GeoNames city snapshot redistributed by
  `geonamescache` 3.0.2. The authoritative downloadable GeoNames gazetteer and
  its data-format readme are published at
  <https://download.geonames.org/export/dump/>.
- GeoNames publishes the gazetteer under Creative Commons Attribution 4.0,
  permits commercial use with attribution, and supplies it as-is without a
  warranty of accuracy, timeliness or completeness. See
  <https://www.geonames.org/export/> and
  <https://creativecommons.org/licenses/by/4.0/>.

Attribution: **GeoNames — <https://www.geonames.org/> — CC BY 4.0**.

## What BetterOption added

The association between each NUTS region and one representative populated
place is a small BetterOption-maintained crosswalk. It is not an official
Eurostat or GeoNames relationship. A municipality that matches the region
name was selected where possible; for broader Swedish regions, the largest
regional labour-market city in the bundled city snapshot was selected.

Every row therefore carries the precision value `regional_representative`.
The coordinate is **not** a polygon centroid, workplace, postal address, or
claim that every vacancy in the NUTS region is located in that city.

## Product boundary

These points may be used only to calculate an approximate straight-line
distance for ordering Explore cards when EURES supplies a NUTS code but no
usable city or address. The UI and stored source still retain the official
NUTS region label.

They must never be used for:

- walking, cycling, car or public-transport route requests;
- commute-limit enforcement or a hard matching boundary;
- presenting a workplace address or exact distance;
- reverse geocoding, contact enrichment or user-location inference.

Unmapped NUTS codes remain readable through `nuts-2024.csv`, but their Explore
distance stays unknown until a separately reviewed representative point is
added. This is preferable to inventing a coordinate.

No GISCO boundary geometry, derived GISCO centroid or other restricted
statistical geometry is included in this crosswalk.
