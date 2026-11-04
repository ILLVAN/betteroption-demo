> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Invited-alpha legal and privacy readiness

This document is an engineering checklist, not legal advice. The actual
operator, legal form, deployment, target markets, enabled providers, and data
flows determine the final obligations. Qualified German/EU counsel and a
security review should complete the release decision.

## What v0.7.1a establishes

1. **Transparency is versioned.** Registration and Account can record the exact
   Terms and Privacy Notice versions shown to an account.
2. **Acknowledgement is narrow.** The implementation does not describe a
   Privacy Notice acknowledgement as blanket consent to every processing
   activity. Each purpose still needs its documented lawful basis.
3. **Data minimization applies to operations.** Provider accounting stores
   metadata such as provider, purpose, timing, units, outcome, and cost estimate,
   rather than search text, locations, prompts, CV/job content, URLs, keys, or
   provider responses.
4. **Readiness is fail-visible.** Missing operator information, reviews,
   incident planning, and backup testing remain visible operator blockers.

## Required decisions before invitations

| Area | Required operator decision or evidence |
| --- | --- |
| Controller | Final legal name, postal address, contact details, legal form, representatives, registers, tax/VAT information where applicable |
| Purposes and legal bases | A purpose-by-purpose record for account security, profile and CV processing, matching, discovery, routing, communications, logs, support, and fraud/abuse prevention |
| Providers | Controller/processor role, contract, subprocessor list, hosting region, international-transfer mechanism, retention, deletion, and incident contact for every enabled provider |
| Retention | Concrete periods for accounts, sessions, CV text, profiles, matches, job access, operational metadata, support records, logs, and backups |
| Rights | A verified process for access, correction, export, deletion, restriction, objection, portability where applicable, and supervisory-authority complaints |
| Security | Threat model, HTTPS, secure cookies, CSRF and rate limits, PostgreSQL, secret rotation, least privilege, dependency scanning, encrypted backups, restore testing, monitoring, and incident response |
| Product claims | Reviewed language for search completeness, route and salary estimates, employer evidence, AI uncertainty, ranking, availability, and experimental alpha status |
| User eligibility | Invitation rules, minimum age and capacity, prohibited data, acceptable use, territorial availability, and support expectations |

## Provider cost calibration

For each provider:

1. Choose a non-overlapping billing period in the provider dashboard.
2. Enter the exact UTC start and exclusive end in Operations.
3. Use the ledger provider name shown in the provider breakdown.
4. Enter the invoice or dashboard amount and its original currency.
5. Compare correlated calls and units with the provider's own usage count.
6. Investigate gaps before using the effective rate as an environment estimate.

Do not combine currencies without an explicit exchange-rate record. A zero
configured estimate means unknown cost, not free use. Calibrate repeatedly
before choosing free allowances or subscription pricing.

## Authoritative starting points

- [General Data Protection Regulation](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02016R0679-20160504)
- [European Data Protection Board: process personal data lawfully](https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en)
- [European Data Protection Board: data-protection basics](https://www.edpb.europa.eu/sme/learn-the-basics/data-protection-basics_en)
- [BfDI: generative AI and data protection guidance (German PDF)](https://www.bfdi.bund.de/SharedDocs/Downloads/DE/DokumenteBfDI/Dokumente-allg/2025/Handreichung-KI.pdf?__blob=publicationFile&v=3)
- [German Digital Services Act, section 5](https://www.gesetze-im-internet.de/ddg/__5.html)
- [EDPB personal-data-breach notification guidelines (PDF)](https://www.edpb.europa.eu/system/files/2023-04/edpb_guidelines_202209_personal_data_breach_notification_v2.0_en.pdf)
- [EU Artificial Intelligence Act (official PDF)](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ%3AL_202401689)

The sources above are starting points, not a determination that every listed
rule applies in the same way to the eventual service.
