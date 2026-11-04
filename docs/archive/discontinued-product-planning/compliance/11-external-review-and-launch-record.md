> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# External review and launch record

Release: v0.7.1b-legal  
Environment: staging.betteroption.example\
Launch decision: **BLOCKED**

## Operator facts

- Legal name/form: **[required]**
- Authorised representative: **[if applicable]**
- Complete service address: **[required]**
- Public legal/privacy email: **[required]**
- Register/number: **[if applicable]**
- VAT ID: **[if applicable]**
- Competent data-protection authority: **[derive from real establishment]**
- DPO/EU representative: **[decision and details]**

## Review sign-off

| Item | Reviewer | Date/version | Findings closed | Evidence |
| --- | --- | --- | --- | --- |
| Imprint/DDG/consumer information |  |  | No |  |
| Privacy Notice and lawful bases |  |  | No |  |
| Terms and alpha limitations |  |  | No |  |
| AI Act scope/transparency |  |  | No |  |
| DPIA/Article 36 decision |  |  | No |  |
| Legitimate-interests assessment |  |  | No |  |
| TOM/security review |  |  | No |  |
| Processor/TIA review |  |  | No |  |

## Provider evidence

For every enabled provider attach:

- executed DPA/terms and account/legal entity;
- dated subprocessor list;
- data categories, purpose, endpoint/model/product and region;
- for web search, the exact public-job request schema, allowed source domains,
  citation validation, source-site recipients and country-abstention rules;
- processing/storage locations and transfer mechanism/TIA;
- retention/deletion configuration and test;
- security/TOM evidence and incident/security contacts;
- approval signature and re-review date.

## Operational tests

| Test | Required result | Date/evidence |
| --- | --- | --- |
| Registration/invitation | Direct registration closed; one-time invitation only |  |
| Tenant isolation | Cross-account profile, job, match, export and deletion denied |  |
| CV minimisation | Identifiers redacted; sensitive categories blocked; displayed text equals provider request |  |
| Salary-research boundary | Only bounded public job fields leave the app; candidate target/profile stay local; country/currency/period/source evidence is attributable; cross-country and unsupported cases abstain |  |
| Raw/rejected retention | Automated purge meets schedule |  |
| Account deletion | Live aggregate gone; provider actions initiated; backup ageing explained |  |
| DSR dry run | Access, correction, export, restriction, deletion completed |  |
| Incident tabletop | 72-hour decision and communications exercised |  |
| Backup restore | Encrypted backup restored and expired backup deleted |  |
| Edge security | Origin cannot bypass Cloudflare or proxy trust remains off |  |
| Public pages | No placeholders; exact enabled providers/retention disclosed |  |

## Final decision

The following four application flags remain `false` until the corresponding
evidence above is complete:

```dotenv
BETTEROPTION_LEGAL_REVIEW_COMPLETED=false
BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=false
BETTEROPTION_INCIDENT_PLAN_READY=false
BETTEROPTION_BACKUP_RESTORE_TESTED=false
```

Approved to invite external users: **No**

Operator signature/date: **[blank]**  
Legal/privacy reviewer: **[blank]**  
Security reviewer: **[blank]**
