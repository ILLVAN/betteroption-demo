> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8e Release Notes

v0.6.8e fixes the remaining all-job `Transit unavailable` regression. The
provider was failing on the shared Compass origin before evaluating any job:
Transitous treated postcode `60486` as fuzzy text and returned unrelated
truncated `6048` candidates. The locality safeguard correctly rejected those
candidates, but every job inherited the same origin failure.

## Postcode-safe routing

- The complete GeoNames Germany postal-code dataset is bundled under CC BY 4.0.
- A postcode-only German endpoint is resolved locally to its locality and
  centroid. `60486` resolves to Frankfurt am Main.
- The postcode is not sent to GeoNames, Transitous geocoding, or another new
  geocoder at runtime. Transitous receives coordinates for planning.
- Postcode-plus-city labels use the same deterministic lookup. Explicit street
  addresses remain untouched.
- The mobility cache fingerprint and matching algorithm version are advanced so
  saved v0.6.8c/v0.6.8d failures cannot be reused as current evidence.

## Verification

Regression coverage proves that the `60486` origin produces no Transitous
geocoding request, resolves to Frankfurt am Main, and can route to Alzenau. The
existing locality safeguards still reject the unrelated “Zum Alten Bahnhof”
candidate.

GeoNames postal data is available from
[download.geonames.org](https://download.geonames.org/export/zip/) and is
provided under CC BY 4.0 without warranty.
