> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Alpha product boundaries

Status: operator decision draft for signature  
Applies to: invited private alpha in the EU/EEA

## Permitted purpose

BetterOption is a candidate-side decision-support workspace. An invited adult
may describe work preferences and experience, find public job advertisements,
compare those advertisements against their own criteria, and track their own
decisions. They may also explicitly request and edit a grounded cover-letter
draft for their own use.

Matches are recommendations exclusively for the candidate. They are not
employment decisions and are not shared with an employer, recruiter, staffing
agency, prospective employer, or advertising audience.

## Non-negotiable boundaries

The alpha:

1. has no employer or recruiter accounts;
2. exposes no candidate profile, score, ranking, or match to an employer;
3. does not filter, rank, reject, shortlist, or recommend candidates for an
   employer;
4. may prepare an editable candidate-side cover-letter draft but does not send
   applications, messages, forms, emails, CVs, or drafts to employers;
5. requires the user to verify a job and submit any application themselves;
6. is invitation-only and available only to people aged 18 or older;
7. does not intentionally collect Article 9 special-category data;
8. does not intentionally collect criminal convictions, offences, allegations,
   background checks, or security-clearance information;
9. does not train, fine-tune, benchmark, evaluate, or improve any model using a
   real user's profile, raw answers, CV text, prompts, outputs, or feedback;
10. permits testing only with synthetic fixtures or data that has been
    demonstrably anonymised so that re-identification is not reasonably likely;
11. uses city or postcode location by default; an exact home address is neither
    requested nor sent to a route provider;
12. enables an external provider only after the provider-register gate is
    complete for that exact service, account, plan, endpoint, region, and
    configuration;
13. never sends a candidate's compensation criterion, salary target, Compass,
    profile, persona/account details, home location, or other personal data to
    the salary-research adapter;
14. never substitutes a German or other country's salary benchmark for a job
    in a different country, and shows no estimate when country-aware evidence
    is not adequately supported.

Any proposal to cross one of these boundaries is a new product decision and
requires an updated DPIA, ROPA, legal pages, tests, and launch approval before
implementation.

## Compass flow

- Before the first answer, the user sees that their text will be sent to the
  configured OpenAI API for structured extraction.
- The user is told not to enter health, disability, ethnicity, religion,
  political views, trade-union membership, sexual-life/orientation, genetic,
  biometric, criminal-offence, or similarly sensitive data.
- OpenAI proposes structured statements. The user can inspect, correct, remove,
  export, and delete them.
- The matching engine uses confirmed user-controlled statements. It does not
  make a decision for an employer.
- Raw Compass answers are not model-evaluation material and follow the finite
  retention schedule.

## CV flow required before reopening

1. Parse PDF, DOCX, or TXT on BetterOption's own server. Do not upload the
   original binary to a model provider and do not retain the binary.
2. Locally remove email addresses, phone numbers, URLs, exact addresses, date of
   birth, identifiers, and likely name/header lines.
3. Locally screen for apparent Article 9 and Article 10 content. If detected,
   stop before persistence or provider transfer, identify only the category,
   and ask the user to remove the content. Do not log the matched words.
4. Show the resulting text to the user in an editable preview. Explain exactly
   that this selected text will be sent to OpenAI, why, and the provider's
   applicable retention.
5. Require a separate affirmative action for the optional CV-to-OpenAI
   operation. A general Privacy Notice acknowledgement is not consent.
6. Send only the edited experience, education, skills, tools, responsibilities,
   and work-result text. Do not send filename, contact details, exact address,
   full date of birth, or the original file.
7. Delete BetterOption's transient extracted/selected CV text immediately after
   extraction. The only retained output is the structured proposal that the
   user can confirm, edit, or remove.
8. Do not offer indefinite CV-text retention in the alpha. A future retention
   feature requires a separate deliberate request, a defined purpose, a maximum
   period, and automated deletion.

Local screening is a minimisation safeguard, not a guarantee. Users remain
instructed not to upload prohibited content.

## Application-draft flow

1. Offer drafting only for a current, non-blocked Top or Stretch match.
2. Require a separate user action for every create, recreate, longer or shorter
   request; never submit, email or upload a result to an employer.
3. Send only relevant public job evidence and minimised confirmed Compass facts.
   Exclude raw, pending, rejected, contact, exact-home-location and unrelated
   persona data.
4. Locally reject apparent special-category content before the provider call.
5. Keep the result editable and visibly experimental; require the candidate to
   verify every statement.
6. Delete a saved draft 180 days after its last update or earlier on user request.

## Optional salary-orientation flow

1. Run only when the feature is configured, the active persona has an active
   compensation criterion, and the advertisement states no compensation.
2. Bound each research batch. Send only public job fields needed to identify a
   suitable benchmark: title, country/coarse job location, summary, and limited
   role, experience, employment or weekly-hours facts. Do not send raw source
   text, public contact details or unrelated facts.
3. Keep the candidate boundary absolute. The research provider receives no
   candidate compensation criterion or target and no Compass/profile, persona,
   account, home-location, CV, feedback, or application data.
4. Research country-aware evidence. The current allowlist accepts attributable
   official EU and national employment/statistics sources and an attributable
   European Central Bank source when currency conversion is necessary. No
   secondary salary source is currently enabled; adding one later requires
   prior methodological/provider review and independent corroboration.
5. Store the benchmark's country, currency, pay period, mapped occupation,
   source URLs and cautious provenance explanation with the match result. Do
   not describe an estimate as employer-advertised compensation.
6. Do not extrapolate one country's benchmark to another country, mechanically
   scale a full-time figure to part-time work, or claim coverage for every
   country or occupation. Abstain when the country, mapping, period, currency
   or evidence is unsupported.
7. Keep estimated pay as unknown evidence for matching, never a hard pass,
   fail, block or employer decision.
8. Treat source sites reached through OpenAI web search as independent web
   recipients that may receive ordinary search/retrieval request data. Approve
   the exact OpenAI search configuration, source policy, transfers, retention
   and notices before external-alpha use. Local development enablement is not
   launch approval.

## Provider minimum

The smallest acceptable provider set is preferred:

- Netcup for the selected EU server, after executing its Article 28 agreement;
- Cloudflare for DNS, proxy, TLS, and abuse protection, after accepting/reviewing
  the account DPA and transfer configuration;
- OpenAI API for structured extraction, configured public-job salary research,
  and explicit candidate-requested drafting, after executing the DPA, disabling
  data sharing, confirming each endpoint/tool/model's retention and region, and
  completing the transfer and source-recipient assessments.

Brave, Exa, You.com Search, Google Routes, Transitous, FOSSGIS Valhalla,
OpenRouteService, and the public Nominatim endpoint remain disabled until their
individual row in the processor register is approved. Public job pages and ATS feeds are recipients
of technical requests rather than processors; they still require source terms,
minimisation, and security review. Official and vetted salary-source sites
reached through OpenAI web search are also independent web recipients and need
an approved source policy before the external alpha.

## Decision owner

Operator: **[insert legal operator]**  
Decision date: **[insert date]**  
Signature/approval record: **[insert reference]**
