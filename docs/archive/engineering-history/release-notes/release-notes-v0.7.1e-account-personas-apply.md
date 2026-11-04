> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.7.1e-account-personas-apply

`v0.7.1e-account-personas-apply` turns the local persona experiment into a
normal account-owned workspace model and adds a candidate-controlled drafting
step. It is intended to remain useful on one Windows computer while preserving
the boundaries needed for a later, separately reviewed private alpha.

Application version: `0.7.1e-account-personas-apply`  
Python package version: `0.7.1+e.account.personas.apply`  
Release archive: `betteroption_v0_7_1e_account_personas_apply.zip`  
Database head: `0019_application_drafts`

## Account-owned personas

- An email/password account is now the authentication and ownership boundary.
- Each account can create up to five named, passwordless personas and switch
  between only its own personas after signing in.
- A persona owns its own current and historical Compass workspaces, saved-job
  access, matching history, application state and cover-letter drafts.
- Persona names are unique case-insensitively inside one account. The same name
  may be used by a different account.
- Creating a separate email registration creates a separate account; it no
  longer exposes that account as a switchable persona.
- Existing sessions remember their active persona. Deleting a persona also
  removes its private workspace aggregate through database foreign-key
  cascades; deleting the final persona is refused.

The database keeps three deliberately separate levels:

```text
Account (email/password)
└── Persona (up to 5, no separate password)
    └── Profile workspaces (Compass history/checkpoints)
```

## Migration and existing local data

Migration `0018_account_owned_personas` creates one `Main` persona for every
existing account, attaches that account's existing workspaces to it, and makes
it active in existing sessions. It does not merge accounts.

This matters for databases created with v0.7.1d: if `legacy-one` and `legacy-two` were
registered with different email addresses, they remain two independent
accounts, each with its own `Main` persona. That is the safe, deterministic
migration. If several test perspectives should live under one account, create
new personas in that account; automatic cross-account data merging is not
supported.

Migration `0019_application_drafts` adds editable, persona-scoped application
drafts. The installer preserves `.env` and `local-data`; schema migrations run
when the upgraded application first opens the database. Back up the SQLite file
before that first start.

## Add and Match are separate

- `Add` appears after Explore and owns the public-job URL/reference workflow.
- `Match` opens directly on matching results and controls instead of placing a
  large reference form above them.
- Existing reference records remain available. This is a route and layout
  change, not a destructive data conversion.

## Candidate-controlled Apply workspace

- `Apply` appears before Archive and can also be opened for an eligible job from
  its detail page.
- The user can select one or more current, non-blocked matched jobs and request
  a concise cover-letter draft.
- Provider input is minimised to relevant public job facts/evidence and
  confirmed Compass facts needed for the selected role. Raw Compass answers,
  rejected/pending facts, the original CV and unrelated persona data are not
  drafting input.
- Drafts can be edited and saved, recreated, lengthened, shortened or deleted.
- The model is instructed to stay grounded and not invent qualifications, but
  every result still requires human review.
- BetterOption does not submit applications, contact employers or expose
  profiles, personas, rankings or drafts to employers/recruiters.
- Saved drafts expire 180 days after their last update through the retention
  policy (`BETTEROPTION_RETENTION_APPLICATION_DRAFT_DAYS=180`) and can be
  deleted earlier by the user.

Cover-letter generation is an explicit paid provider action. The default batch
limit is five jobs. `BETTEROPTION_APPLICATION_DRAFT_MODEL` can select a
task-specific model; otherwise the configured OpenAI model is used.

## Local operating boundary

For local multi-account testing, bind only to loopback and use account auth:

```dotenv
BETTEROPTION_APP_ENVIRONMENT=local
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=open
BETTEROPTION_ACCOUNT_PERSONAS_ENABLED=true
BETTEROPTION_PERSONA_LIMIT=5
BETTEROPTION_LOCAL_PERSONAS_ENABLED=false
BETTEROPTION_AUTH_SECURE_COOKIE=false
BETTEROPTION_WEB_HOST=127.0.0.1
BETTEROPTION_WEB_PORT=8000
BETTEROPTION_APPLICATION_BATCH_LIMIT=5
BETTEROPTION_RETENTION_APPLICATION_DRAFT_DAYS=180
```

Use `open` only while creating local test accounts. It can be changed to
`disabled` afterwards without removing accounts or personas. Never publish the
loopback configuration through a tunnel, router or public bind.

Unknown provider prices must remain explicit numeric `0` values in `.env`, not
blank strings. `0` means unknown/unpriced, never free.

## Legal and alpha status

The Privacy Notice, AI notice, Terms and compliance records in this repository
are engineering drafts. They now describe the application-drafting data flow,
stored drafts, candidate-only use and absence of automatic submission, but this
release does not assert that counsel, DPIA, processor, transfer, retention,
incident, backup or launch review is complete. External private-alpha access
remains gated on those reviews and the normal secure deployment boundary.

## Install, verify and preserve

Use the complete Windows and GitHub cycle in
[Local accounts, personas and Apply for v0.7.1e](../local-guides/local-account-personas-apply-v0.7.1e.md).
It includes a pre-migration backup, exact archive/version checks, the full test
gate, manual acceptance and the commit/tag/push commands for the private
repository.
