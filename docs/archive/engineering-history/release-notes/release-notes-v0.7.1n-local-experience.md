> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1n-local-experience

v0.7.1n is a localhost experience and reliability release. It preserves the
M matching contract and existing database head while making the main workflow
more legible, recoverable and predictable.

## What changed

- Explicit remote-only jobs no longer wait for address routing. Hybrid jobs and
  remote jobs with real workplace alternatives still use the normal shortest
  confirmed route comparison.
- Explore decomposes a broad Compass direction into several focused search
  bundles, keeps clear exclusions, gives Exa more focused attempts, and rejects
  parked, suspended, explicit 404 and recognised error-landing pages before
  selection. Its 150-result target and 180-result ceiling remain subject to the
  existing time, availability and ranking gates.
- Primary actions share one visual language across Home, Compass, Add, Explore,
  Match, Apply and Archive. Home chooses a useful next action from the current
  persona state instead of showing one static call to action.
- Add keeps URL verification and manual-text recovery in one form. A failed
  extraction asks for manual text without first creating a misleading archive
  record.
- Job cards use cleaned location/remote labels and aligned Job/Employer rating
  rows. Posting-age, state artwork and evidence links no longer compete for the
  same space.
- Job Detail adds previous/next match navigation, separate salary minimum and
  maximum fields, consistent work-model confidence/value presentation, and a
  quieter evidence UI with expandable provenance and help.
- Guided Setup keeps direct Compass editing available. Inline saves preserve
  the current reading position and use compact feedback rather than jumping to
  the top of the page.
- Prepare Package performs broader deterministic extraction of source-published
  contact, postal and application-process details. Those fields stay editable,
  are never invented, are not sent to OpenAI, and never trigger an application.

## Privacy and operating boundary

The supported operating mode remains password-protected localhost at
`127.0.0.1`. This release does not authorize a server deployment or external
alpha. Provider choices remain account-controlled, disabled providers are not
called, and numeric price `0` continues to mean used but unpriced—not free.

The architecture remains compatible with later hosting, but a hosted rollout
still needs the documented RoPA, lawful-basis and transparency work, DPIA
decision, processor/transfer review, retention and deletion evidence,
incident/DSR procedures, security/restore evidence and final AI Act
classification memo.

## Explicitly not implemented

Additional licensed job sources, LinkedIn or Glassdoor access, and a portal for
employers to publish vacancies are product-roadmap ideas. v0.7.1n does not
implement or claim any of them.

## Release identity

- Application: `0.7.1n-local-experience`
- Python package: `0.7.1+n.local.experience`
- Matching algorithm: `matching-v0.7.1m` (unchanged)
- ZIP: `betteroption_v0_7_1n_local_experience.zip`
- Git tag: `v0.7.1n-local-experience`

Use [the complete local install, backup, acceptance and GitHub guide](../local-guides/local-experience-v0.7.1n.md).
