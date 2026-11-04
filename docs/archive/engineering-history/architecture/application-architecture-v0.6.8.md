> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.8

## Product boundary

v0.6.8 separates discovery cost from decision quality:

1. Explore discovers and orders public candidates with role evidence, seniority,
   exclusions, and offline straight-line city distance.
2. Saving a job verifies its canonical source and uses one of 25 archive slots.
3. Only an explicit Matching run invokes route providers and applies the complete
   confirmed Compass.
4. All 25 valid slots receive the same deterministic matching and route policy.

Explore has no dependency on `MobilityService`. `ProductAccessPolicy` keeps
`explore_exact_routing_enabled` false and caps exact Match routing at 25 jobs.

## Endpoint resolution

The route label hierarchy is address, postal code/city, district, city. Profile
and job extraction prompts preserve the most precise explicitly stated label and
never infer a private address. Matching chooses the most precise verified job
location fact. Each result records requested/resolved labels and precision for
both endpoints.

City-only public-transport pairs use validated city-centre benchmarks. v0.6.8d
does not invent station names from city labels. A geocoder candidate must retain
the requested locality identity and, when the bundled city index can resolve the
label, remain within 25 km of that locality. Explicit station labels remain
station routes. Same-city city-only pairs remain Unknown because identical city
centres cannot represent a door-to-door commute. The UI asks for a district,
postcode, station, or street.

v0.6.8e resolves German postcode-only endpoints locally from the bundled
GeoNames DE postal-code file. The complete five-digit postcode becomes a
locality and centroid before route planning, and only coordinates are sent to
Transitous. Explicit street addresses remain provider-resolved and are never
degraded to a postcode centroid.

v0.6.8f reuses the same offline postcode and city indexes for keyless Valhalla
routes. Car, bicycle, and walking therefore do not require Google or a runtime
geocoder when both endpoints contain a resolvable German postcode or city.
Street-level labels without a locally resolvable locality remain Unknown instead
of being sent to an unrelated geocoder or silently reduced to straight-line
distance.

v0.6.8g normalizes every Compass commute limit into a self-contained semantic
fact such as `commute.bicycle.max_minutes = 120 minutes by bicycle one way`.
Hours are converted before matching. A bare legacy value is repaired from its
modal key when that key is unambiguous; a limit without any identifiable mode is
kept Open and excluded from routing rather than assigned to a guessed mode.

The destination resolver keeps three levels distinct: an explicit workplace
address from the advertisement; an employer-plus-location POI hint available to
Google when only a city is known; and a validated city centre for Transitous.
The POI hint never overwrites the evidence-backed destination.

## Time-window evidence

Providers designed for repeated time-window calls can be sampled at 07:30,
08:00, and 08:30 on the next non-holiday Tuesday. The keyless Transitous adapter
uses one 08:00 plan call with seven requested alternatives instead. This avoids
the 54-request burst that six jobs previously caused through repeated geocoding
and planning. Transitous geocodes are reused for the lifetime of the provider.

Calls to the public endpoint are paced. HTTP 429, 408, temporary 5xx responses,
and transient transport errors receive up to two retries with a maximum
two-second delay. Persistent failures remain Unknown and disclose their status;
they are not cached as evidence.

Conservative distance/time bounds reject extreme provider outliers. Rejection is
visible in diagnostics and never becomes negative match evidence. A configured
fallback is tried before the route becomes Unknown.

## Privacy modes

`privacy_first` is the default. Auto mode omits Google, uses Transitous for
public transport, uses openrouteservice for supported modes when configured,
and then uses the keyless FOSSGIS Valhalla service for car, bicycle, and walking.
`balanced` explicitly enables Google-first routing when a Google key exists.

The public FOSSGIS service is Google-free, not endpoint-private: it receives two
coordinates and a route mode. The adapter sends an identifying User-Agent and
`X-Client-Id`, performs at most one request per second, does not claim live
traffic, and caches a successful private-alpha result for twelve hours. FOSSGIS
and OpenStreetMap attribution is visible in the product. A paid release must
obtain operator approval or use a self-hosted Valhalla/openrouteservice instance.

The route boundary receives only origin, destination, mode, and departure time.
It never receives CV text, salary, profile prose, requirement lists, user ID, or
job-match score. Provider clients ignore environment proxies and keys stay in the
server-side `.env`. Google responses are not persistently cached.

## Persistence

Migration `0007_route_evidence` adds range, samples, precision, confidence,
resolved endpoint, and route-scope fields to `commute_estimates`. The cache stays
scoped by workspace and job. Cache fingerprint `mobility-v0.6.8f` prevents an old
single-sample estimate from masquerading as new range evidence.

## Compass authority

A direct answer in the guided or targeted Compass flow is user-authored intent.
Its newly extracted facts are activated immediately and recorded with a review
event, source excerpt, confidence, and an editability note. The user can inspect,
edit, reclassify, or remove each fact later. Existing confirmed or rejected
decisions remain protected from later extraction.

Indirect evidence is different. CV and reference-derived proposals continue to
enter the Review Tray and do not affect Matching until the user accepts them.
