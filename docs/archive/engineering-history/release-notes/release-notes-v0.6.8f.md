> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.6.8f Release Notes

v0.6.8f closes the non-transit gap in the default privacy-first route chain and
removes the repetitive confirmation stop after a user writes a Compass answer.
The warm visual design and the existing Transitous safeguards remain unchanged.

## Google-free car, bicycle, and walking routes

- Keyless Valhalla routing from the FOSSGIS OpenStreetMap service is enabled by
  default for car, bicycle, and walking when no earlier configured provider
  succeeds.
- German postcodes and recognisable cities are resolved locally. The route
  request contains only two coordinates and the selected mode; it never contains
  CV text, profile prose, salary, requirements, user ID, or match score.
- The client identifies BetterOption, observes the public service's one-request-
  per-second limit, retries only bounded temporary failures, and caches successful
  private-alpha routes for twelve hours.
- A public FOSSGIS request is Google-free but still discloses route endpoints to
  a third-party volunteer server. The UI attributes FOSSGIS and OpenStreetMap and
  links to the map-correction flow. Contact the operator or self-host Valhalla or
  openrouteservice before paid production use.
- Unresolvable endpoints, provider errors, and no-route responses remain explicit
  Unknown evidence. No straight-line duration or invented speed is substituted.
- `privacy_first` keeps Google disabled. `balanced` plus a Google key remains the
  explicit accuracy-first option. A configured openrouteservice key remains a
  Google-free provider ahead of the public Valhalla fallback.

## Immediate Compass activation

- Facts extracted from a direct guided answer or one targeted section addition
  become active immediately. The user no longer confirms the model's structured
  restatement of text they just entered.
- Every statement remains visible with its category and can be edited,
  reclassified, or removed from Compass at any time.
- The automatic activation is audited as a user-input acceptance event, and a
  later extraction cannot overwrite an already accepted or rejected decision.
- CV and reference-derived proposals remain indirect evidence and still require
  explicit Review Tray approval before they influence matching.

## Configuration

The keyless fallback is on by default:

```dotenv
BETTEROPTION_MOBILITY_PROVIDER=auto
BETTEROPTION_MOBILITY_PRIVACY_MODE=privacy_first
BETTEROPTION_VALHALLA_ENABLED=true
BETTEROPTION_VALHALLA_BASE_URL=https://valhalla1.openstreetmap.de
BETTEROPTION_VALHALLA_CLIENT_ID=betteroption.example
BETTEROPTION_VALHALLA_USER_AGENT=BetterOption/0.6.8f (+https://github.com/ILLVAN/betteroption)
```

Disable the public fallback with `BETTEROPTION_VALHALLA_ENABLED=false` when a
self-hosted or configured alternative should be the only non-transit provider.
