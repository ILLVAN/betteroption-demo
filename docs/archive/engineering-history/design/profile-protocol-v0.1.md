> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# WorkLifeBalance Profile Protocol v0.1

## Purpose

The protocol converts a guided free-text conversation into an explicit,
editable and auditable search profile. Natural language is the input method;
structured facts are the contract used by matching.

An LLM may propose structure. It must never silently turn an inference into a
hard filter.

## Conversation design

The default onboarding has nine short stages. Each stage accepts free text,
offers examples and can be skipped. The product asks one useful follow-up at a
time rather than presenting dozens of fields.

1. **Direction — “What are you looking for?”**
   Desired roles, domains, responsibilities, seniority, career direction and
   what should change compared with the previous role.
2. **Location and mobility — “Where can work fit into your life?”**
   Starting point, acceptable regions, transport modes, maximum one-way travel
   time, peak-time relevance, relocation and second-residence openness.
3. **Working model — “How do you want the week to work?”**
   Remote/on-site rhythm, weekly hours, schedule flexibility, travel and shift
   work.
4. **Compensation — “What must the package support?”**
   Hard minimum, target, currency, bonus treatment, benefits and willingness to
   exchange salary for time, commute or stability.
5. **Non-negotiables — “What is genuinely mandatory?”**
   A deliberate list of conditions for which violation should normally remove
   a result.
6. **Preferences — “What would make a job especially attractive?”**
   Technology, tasks, industry, contract, collective bargaining, development
   opportunities and other positive signals.
7. **Exclusions — “What should we protect you from?”**
   Roles, industries, employment arrangements, responsibilities, cultures and
   working conditions to avoid.
8. **Experience and strengths — “What do you bring?”**
   Free text plus optional CV/export. Skills are separated into demonstrated,
   familiar, learning and not desired. A CV describes history, not necessarily
   future preference.
9. **Environment and trade-offs — “Where are you flexible?”**
   Culture, team size, management, autonomy, stability and explicit exchanges
   such as “€5k less is fine for a four-day week.”

Reference jobs are optional and live after the core profile so they cannot
anchor the entire interview.

## Extracted structure

Mobility limits use one canonical key per mode—`commute.transit.max_minutes`,
`commute.car.max_minutes`, `commute.bicycle.max_minutes`, or
`commute.walk.max_minutes`—and a self-contained value that repeats the duration,
mode, and one-way scope. A bare number is not an acceptable persisted mobility
statement. If the user does not identify a mode, the fact remains Open until the
mode is supplied.

Every extracted item is atomic and includes its original quote. Main groups:

- role titles, role families, domains, responsibilities and seniority range;
- required, desired and avoided skills;
- industries, company types and employment arrangements;
- origin precision, destination regions, travel modes and maximum peak travel;
- office/remote days, hours, schedule, travel and shift constraints;
- minimum and target compensation plus acceptable trade-offs;
- contract type, permanence, collective agreement and benefits;
- culture signals: autonomy, pace, hierarchy, collaboration and management;
- candidate evidence: years, projects, outcomes, qualifications and languages;
- exclusions and their scope;
- explicit flexibility and unresolved contradictions.

The system stores the raw section alongside the extracted representation. This
allows re-extraction with a newer model without losing what the user said.

## Requirement semantics

Each fact has exactly one current level:

- **Must-have:** violation normally filters the job. The UI warns users that a
  hard constraint reduces discovery.
- **Preference:** contributes positively or negatively to ranking but never
  removes a job by itself.
- **Exclusion:** a matching characteristic normally filters the job.
- **Open:** relevant information without a decided weight.

The LLM may suggest a level only when language is explicit. “At least”, “never”
and “under no circumstances” are strong signals; “ideally”, “preferably” and
"would be nice" are preferences. Ambiguous wording stays Open and can trigger a
clarifying question; it never becomes a hidden hard boundary.

Hard filters can be relaxed only in a separate Stretch result set. A Stretch
result must name the violated constraint and explain why it is shown. It never
silently enters Top Matches.

## Uncertainty model

Every fact carries both provenance and confidence:

- **Explicit:** directly stated by the user.
- **Inferred:** plausible interpretation; a direct-answer workflow may activate
  it as Open, but never as a hidden hard filter.
- **Confirmed:** active because it came from a direct user answer or was later
  accepted or edited by the user.
- **Rejected:** preserved for audit/model evaluation but excluded from matching.

Low-confidence facts prompt a clarification when they could materially change
results. High confidence is reserved for explicit facts. Confidence remains
visible after activation and is separate from the user's ability to edit or
remove the statement.

Missing information is `unknown`, never `false`. Missing salary or remote
information in a job advertisement reduces evidence confidence; it does not
prove that the job violates the preference.

Contradictions are shown together: “maximum 45 minutes by transit” and “Darmstadt
is always acceptable” may both be valid. The system asks whether the named
exception overrides the general rule.

## User correction

Direct Compass answers become active after extraction so the user is not asked
to confirm a structured restatement of text they just wrote. Compass shows:

- atomic chips grouped as Must-have, Preference, Exclusion and Open;
- source quote available on demand;
- edit, move, delete and “ask me later” actions;
- undo for every change;
- a plain-language summary before the first search.

Edits are authoritative user data. A later extraction must not overwrite them.
The system keeps the source and current authoritative value separately for
evaluation. A model-inferred Must-have or Exclusion is downgraded to Open before
automatic activation. Indirect CV and reference-derived facts still use the
Review Tray and explicit confirmation.

## Reference jobs

A reference consists of a job URL plus free-text positives and negatives.
Copied advertisement text is not accepted. The URL is resolved and verified
before the reference can influence proposals. Learning is **off by default**.

When enabled, the user chooses the permitted learning scope: role, skills,
culture, location, working model or pay. The model proposes profile changes;
the changes still enter the review tray and do not become confirmed facts
automatically.

Rules:

1. Liking a job does not imply liking every property of that job.
2. Advertisement claims are untrusted and cannot establish candidate facts.
3. Negative aspects must not contaminate positive preference learning.
4. One reference cannot create a hard constraint without explicit confirmation.
5. Deleting a reference stops future learning but does not silently delete
   changes the user previously confirmed.
6. An unavailable or unverified reference URL cannot influence the profile.

## Matching contract

Only confirmed hard constraints may filter. Preferences influence ranking.
Open and inferred facts may be used for exploration but must not materially
penalize a job. Every result explanation cites job evidence and identifies
unknowns. Profile facts and job-advertisement instructions are treated as data,
not executable prompts.

## Privacy minimum for the alpha

- Ask only for data required for matching.
- Default location precision is city or postal code, not a home address.
- Do not train external models on user data.
- Do not persist raw CVs longer than required for extraction.
- Let users inspect and delete profile data.
- Log structured event metadata without CV or free-text contents.
