> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance v0.7.1b-legal

Package version: `0.7.1+b.legal`

This is a separately labelled legal/privacy hardening iteration over the tested
v0.7.1b invitation release. It does not claim that the product has passed
external legal review.

## Added

- private-alpha product-boundary decision record;
- ROPA, lawful-basis assessment, DPIA, legitimate-interests assessment, TOMs,
  retention schedule, DSR procedure, 72-hour breach procedure, processor
  register, and launch/sign-off record;
- expanded Privacy Notice and Terms drafts;
- dedicated point-of-use AI notice and cookie/storage notice;
- visible launch blockers when controller/legal/provider facts are incomplete;
- provider configuration disclosure on the Privacy Notice;
- conservative staging example with Brave, Exa, Google Routes,
  OpenRouteService, Transitous, FOSSGIS Valhalla and public Nominatim disabled;
- CV local identifier removal, apparent-sensitive-category screening, editable
  preview, and a separate one-time OpenAI action;
- new CV uploads no longer persist the original file or extracted/selected text;
- legacy saved CV text can be deleted but cannot be sent directly to OpenAI.
- an automatic retention sidecar purges expired auth artifacts, raw Compass
  content, pending/rejected facts, source excerpts, legacy CV text and
  provider telemetry on bounded schedules;
- Caddy access logs rotate daily with a 14-day cap, Uvicorn access logging is
  disabled, and daily database backups expire after 14 days;
- staging/production provider execution is runtime-blocked until the processor
  review flag has supporting evidence.

## Deliberately still blocked

- real operator identity/address/contact and any legal-form/register/VAT facts;
- external legal approval of Imprint, Privacy Notice, Terms, AI scope, lawful
  bases and DPIA;
- executed/account-specific processor contracts and transfer evidence;
- staging evidence that the retention, Caddy rotation and backup jobs run as
  designed, plus provider-side retention/deletion evidence;
- completed DSR dry run, incident tabletop and backup restore/deletion drill;
- final origin hardening and provider configuration evidence.

The four readiness flags remain `false`. The release may be tested locally and
pulled to an offline server, but it is not approval to restore public DNS or
invite users.
