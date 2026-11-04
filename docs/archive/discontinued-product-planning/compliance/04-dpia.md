> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Data protection impact assessment

Status: **open — not approved for external users**  
Assessment owner: **[operator]**  
Reviewers: **[privacy/legal]**, **[security]**  
Review date: 2026-08-05

## 1. Processing assessed

BetterOption receives free-text work preferences and optional selected CV text,
uses an external general-purpose model API to propose structured facts, and
compares user-confirmed facts with public job information. At the candidate's
explicit request it may use minimised confirmed facts and public job evidence to
prepare an editable cover-letter draft. Every output is visible only to the
candidate and is never submitted automatically. Where configured, where a
candidate has an active compensation criterion and where an advertisement
states no pay, the service may send a bounded public-job-only payload to OpenAI
web search for attributable country-aware salary evidence. It does not send the
candidate's salary target or any profile data to that research adapter. For a
bounded number of jobs, a separate semantic relation pass may send only confirmed
criteria that deterministic matching left unresolved for that job together with
canonical public job facts and short quotes. The model cannot score or classify
the job; the validated assessment is one evidence input to deterministic matching.
The service also processes account/security data, provider telemetry, coarse
location/routing inputs, and user feedback.

The assessment is performed because the service evaluates personal aspects,
matches data, uses innovative AI technology, and may receive highly personal or
unexpected sensitive free text. Candidate-only recommendations reduce, but do
not remove, the privacy risk.

## 2. Necessity and proportionality

- The user initiates each purpose and can use manual Compass input without a CV.
- Only user-confirmed facts affect matching.
- No employer receives the profile or output.
- No application is automated.
- External requests use the minimum relevant text or coarse location.
- Semantic match-evidence requests exclude deterministically resolved criteria,
  raw Compass answers, CV text, account/persona metadata, private ratings, home
  location, source URLs and full advertisements. Low-confidence contradictions
  remain unknown and stored evidence fingerprints prevent reuse after correction.
- Salary research uses only bounded public job fields, keeps the candidate's
  criterion/target local, records attributable country/currency/period/source
  evidence, and abstains rather than importing another country's benchmark.
- Raw/transient data has short retention; confirmed data is editable/exportable
  and subject to inactivity deletion.
- No real user data is used for training/evaluation.
- Unreviewed providers stay disabled.

Alternatives considered:

1. local-only model: preferred if quality and maintenance become sufficient;
2. deterministic form without free text: lower risk but materially less usable;
3. full CV upload to model: rejected;
4. recruiter-facing ranking: rejected and outside alpha boundary;
5. static occupation-specific salary tables: rejected because coverage and
   freshness would be poor and a developer-centric catalogue would not serve a
   general candidate population;
6. cross-country salary extrapolation: rejected;
7. indefinite raw-data retention: rejected.
8. sending every criterion or the full advertisement for semantic matching:
   rejected in favour of per-job unresolved criteria and canonical fact quotes.

## 3. Risk assessment

Scale: likelihood and severity are Low/Medium/High before and after controls.

| Risk to person | Initial | Controls | Residual | Owner/action |
| --- | --- | --- | --- | --- |
| Special-category or criminal data reaches a provider | H/H | Prohibition, local CV screening, preview, Compass warning, no log content, rapid deletion path | M/H | Block launch until adversarial screening tests and incident drill pass |
| Identity/contact data unnecessarily included in CV prompt | H/H | Local redaction, user-edited preview, no binary/filename transfer | L/H | Verify with test CV corpus; document limitations |
| Provider reuses or retains content unexpectedly | M/H | DPA, no training opt-in, endpoint/region/retention review, ZDR if available, provider change watch | L/H | Archive account settings and contract evidence |
| Cross-account disclosure | M/H | Account-scoped repository queries, deletion cascades, tenant-isolation tests, operator access restrictions | L/H | Full auth/isolation regression gate |
| Candidate over-relies on inaccurate ranking | H/M | Explainable evidence, visible unknowns, corrections, no employer output, no employment guarantee | M/M | Usability test notices and evidence |
| Semantic relation incorrectly turns one hard criterion into a blocker | H/M | Only unresolved pairs sent; supplied evidence-ID validation; deterministic results win; low-confidence contradictions become unknown; medium-confidence AI reason labelled; user correction and full rematch available | M/M | Adversarial arbitrary-topic relation tests and sampled acceptance review |
| Semantic relation prompt discloses excessive candidate or job data | M/H | Strict minimized schema; no account/persona/raw answer/CV/private rating/home location/URL/full ad; default 25-job cap and batches of five; `store=false` | L/H | Capture and inspect prompt-boundary tests before external launch |
| Draft invents or overstates candidate claims | H/M | Confirmed facts only, grounded prompt, visible editing, explicit review warning, no automatic submission | M/M | Adversarial provider tests and manual acceptance |
| Draft prompt discloses unnecessary persona data | M/H | Task-specific minimisation, no raw/pending/rejected/contact/exact-home data, special-category screen | L/H | Prompt-boundary regression tests and provider review |
| Employer/recruiter gains profile access | M/H | No such role/API/UI, invitation policy, access review | L/H | Treat any new employer feature as new DPIA |
| Exact home location exposed | M/H | City/postcode default, exact address prohibited, no account ID in routing request | L/M | Remove exact-address guidance from UI and tests |
| Raw/rejected data retained indefinitely | H/M | Finite schedule, automated purge, backup expiry, no evaluation reuse | L/M | Block launch until deletion jobs and tests exist |
| Account takeover or credential stuffing | M/H | Argon/password hashing, verified accounts, HttpOnly/Secure cookies, CSRF, rate limit, session revocation | L/H | Monitoring/tabletop; origin hardening |
| Token leakage in logs/referrers | M/H | Hashed single-use tokens, short expiry, URL fragment delivery | L/M | Verify reverse-proxy logs and referrer policy |
| Provider query reveals sensitive career situation | M/M | Coarse generic query, no raw profile/contact/CV, reviewed provider only | L/M | Query inspection tests |
| Salary research reveals a candidate's target or profile | M/H | Separate public-job-only adapter; no candidate criterion/target, Compass/profile, account/persona or home-location fields; payload-boundary tests | L/H | Inspect structured request schema and captured provider calls before launch |
| Salary range is wrong, stale or mapped to the wrong country/occupation | H/M | Country-aware source policy, attributable country/currency/period/source URLs, no cross-country extrapolation, visible uncertainty, abstention, never a hard match blocker | M/M | Multi-country adversarial tests; source-freshness and mapping review |
| Salary query or source retrieval discloses unnecessary public personal/contact data | M/M | Bounded title/location/summary and limited role/employment facts; no raw advertisement/contact text and no candidate data; reviewed source policy | L/M | Inspect request samples without retaining prompt content |
| Salary-source site or citation is untrustworthy | M/M | Current explicit allowlist accepts official EU/national employment/statistics sources and ECB conversion evidence; no secondary source is enabled; retain clickable provenance | L/M | Approve source policy and verify tool-reported sources against stored URLs |
| Backup loss or stale deletion | M/H | Encryption, separate access, 14-day rotation, restore/deletion drill | L/H | Evidence required before launch |
| User cannot exercise rights across providers/backups | M/H | Data map, DSR checklist, provider contacts, scoped backup expiry | L/M | Complete staging DSR dry run |
| Direct origin bypass weakens Cloudflare controls | M/H | Restrict origin to Cloudflare IPs/tunnel; trust proxy headers only after restriction | L/H | Infrastructure change and verification |

## 4. Rights and safeguards

The user receives point-of-use AI information before first processing, versioned
privacy information, access to editable facts, export and account deletion.
Consent is used only for the optional CV-to-OpenAI action and can be withheld
without losing ordinary service access. Objection/restriction requests suspend
non-essential processing while assessed.

## 5. Residual-risk decision

Residual risk is not accepted yet. Launch remains blocked until:

- the real operator and privacy contact are recorded;
- CV preview/redaction/screening and deletion are implemented and tested;
- raw/rejected-data purges and backup expiry are implemented and tested;
- processor evidence is archived for the exact enabled configuration;
- semantic match evidence remains unavailable to external users until the exact
  endpoint/model, minimized request schema, retention, transfers, confidence/
  blocker validation and prompt-boundary tests are approved;
- salary research remains disabled for external users until the exact OpenAI
  web-search configuration, public-job payload, source policy, transfer and
  retention evidence, citations and country-abstention tests are approved;
- the origin is hardened or Cloudflare trust remains disabled;
- the DSR dry run, incident tabletop, and restore drill pass;
- qualified counsel reviews the assessment and determines whether Article 36
  prior consultation is required.

Approval: **[name/date/signature — blank means not approved]**
