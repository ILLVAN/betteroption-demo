> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# Domain decision note — v0.7.2d

Status: no product or UI rename in this release.

## Recommendation

Keep `betteroption.example` as the canonical alpha address for now. The three-year
purchase is already committed, and changing identity immediately would add
migration, recognition, email, legal-notice and redirect work before the product
has enough real users to test the name.

`LifeLife.work` is the strongest alternative in the current shortlist. It is
short, distinctive and puts life before work twice, which matches the product's
point of view unusually well. The trade-off is that repetition is harder to hear,
spell and explain than it is to understand visually. It may feel memorable to one
person and accidental to another. That is a testable branding question, not a
technical blocker.

| Candidate | Strength | Main risk | Current decision |
|---|---|---|---|
| `LifeLife.work` | Short, mission-aligned, playful without sounding childish | Spoken ambiguity and doubled-word typo risk | Test first; strongest challenger |
| `lifelife.cc` | Very short and inexpensive | `.cc` says little about the product and may inspire less trust | Do not prefer |
| `lifelifebalance.life` | Explains the balance idea | Long, repetitive and visually busy | Do not prefer |
| `betteroption.example` | Immediately understandable and already owned | Long and comparatively expensive | Keep as alpha canonical domain |

Google says new generic top-level domains are treated like other generic domains
for search ranking. The decision should therefore be driven by recall, trust and
brand fit rather than an assumed `.work` SEO penalty:
<https://developers.google.com/search/blog/2015/07/googles-handling-of-new-top-level>

## Low-risk test before any rename

1. Confirm renewal, transfer and possible premium-renewal prices rather than only
   the first-year offer.
2. Test both names with about ten people who have not seen the project.
3. Ask what each name suggests, then ask them to type it immediately and again a
   day later without showing it.
4. Record spoken recall, typed recall, trust and product meaning separately.
5. Keep the existing domain canonical through private alpha. If `LifeLife.work`
   wins clearly, use it first as a redirect and only then plan a deliberate rename.

Buying a cheap defensive domain can be reasonable, but this note is not a purchase
instruction. No application name, logo, static copy or external link changes in
`v0.7.2d`.
