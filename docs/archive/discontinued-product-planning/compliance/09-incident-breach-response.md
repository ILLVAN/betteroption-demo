> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Incident and 72-hour breach-response procedure

Emergency privacy/security contact: **[name, phone, monitored email]**  
Deputy: **[name/contact]**  
Counsel/DPO: **[contact]**  
Competent authority: **[confirm after operator address is known]**

## First response

1. Record detection time, reporter, affected system, and an incident ID.
2. Contain safely: revoke keys/sessions, disable provider/feature, isolate host,
   preserve volatile evidence, and keep the service offline where necessary.
3. Do not destroy evidence, notify attackers, or paste personal data into an
   unreviewed collaboration/AI tool.
4. Start a decision log in UTC and assign incident commander, technical lead,
   privacy lead, and communications owner.

## Breach assessment

Determine:

- what happened and whether confidentiality, integrity, or availability of
  personal data was affected;
- people, records, data categories, special sensitivity, duration, geography,
  encryption/pseudonymisation, and likely consequences;
- recipients/providers/subprocessors involved and their notification time;
- whether the event is likely to risk people's rights and freedoms;
- whether high risk requires direct communication to affected people.

The 72-hour clock runs from controller awareness, not completion of the
investigation. Record the awareness decision and deadline.

## Notification

- Notify the competent supervisory authority without undue delay and, where
  feasible, within 72 hours if the breach is likely to result in risk. If late,
  explain why. Provide information in phases if necessary.
- Notify affected people without undue delay when high risk is likely, using
  clear language, consequences, mitigation, and a contact point, unless a
  documented statutory exception applies.
- Coordinate provider, insurer, counsel, police, and contractual notices without
  delaying required GDPR notices.

## Documentation and recovery

Document every personal-data breach, including non-notified events, facts,
effects, risk reasoning, decisions, communications, and remediation. Rotate
secrets, patch root cause, validate tenant boundaries, restore from verified
backup if needed, monitor recurrence, and conduct a post-incident review.

## Exercises

Before launch, run a tabletop scenario involving an exposed database backup and
an OpenAI prompt containing prohibited data. Repeat at least annually and after
material architecture/provider changes.

Exercise record: **[date, participants, findings, closed actions]**

