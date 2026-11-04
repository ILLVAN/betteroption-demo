> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Purpose-by-purpose lawful-basis assessment

Status: internal assessment requiring German/EU legal review

The Privacy Notice acknowledgement records delivery of information. It is not
consent. The Terms acceptance forms the alpha service relationship; it does not
legalise unrelated processing.

| Purpose | Proposed GDPR basis | Necessity and boundary |
| --- | --- | --- |
| Create and administer invited account | Art. 6(1)(b) | Necessary to provide the requested private workspace |
| Verify email through exact-address invitation | Art. 6(1)(b) | Necessary to restrict access and bind the account to the invited address |
| Compass extraction and candidate-side matching | Art. 6(1)(b) | Core requested service; only the user's inputs and candidate-visible outputs |
| Configured public-job salary research | Art. 6(1)(b), subject to counsel review | Runs only to assess an active compensation criterion where an ad states no pay; sends bounded public job fields but never the candidate's criterion/target or profile data; country/source coverage and recipients remain separately reviewed |
| Save confirmed profile, jobs, matches, and user decisions | Art. 6(1)(b) | Necessary for persistence and the user's requested workflow, subject to finite retention |
| User-requested cover-letter drafting | Art. 6(1)(b), subject to counsel review | Optional service action initiated by the candidate; minimised confirmed facts and public job evidence only; no submission or employer disclosure |
| User-submitted private-alpha product feedback and human triage | Art. 6(1)(b) for the requested alpha feedback channel; Art. 6(1)(f) for proportionate product-quality triage, subject to counsel review | Voluntary product-only message and optional rating; no job/Compass/CV/application/diagnostic content requested; no AI, model-evaluation, analytics, advertising or unrelated reuse; follow-up by email only when separately permitted |
| Optional CV-text transfer to OpenAI | Art. 6(1)(a), explicit separate action | CV upload is optional and not required for ordinary Compass use; user sees and edits the exact text and can proceed without it |
| Public job retrieval | Art. 6(1)(b) for the user's request; Art. 6(1)(f) for corpus integrity where applicable | Only public professional information; source terms and rights remain separately reviewed |
| Coarse route/geocode request | Art. 6(1)(b) when requested | City/postcode only; optional providers disabled until reviewed |
| Authentication security, rate limiting, abuse prevention, minimal logs | Art. 6(1)(f) | Legitimate interest assessed separately; no raw password/token/profile in logs |
| Legal records and regulator cooperation | Art. 6(1)(c) where a concrete obligation applies | Retain only the evidence required by the specific obligation |
| Support | Art. 6(1)(b) for service support; Art. 6(1)(f) for general security/defence | Do not repurpose support messages for training |
| Product analytics/model evaluation using real profiles | **Not permitted** | No lawful basis selected; feature is outside alpha scope |
| Marketing/analytics cookies | **Not enabled** | Would require separate review and, where required, consent under GDPR/ePrivacy/TDDDG |

## Article 9 and Article 10

The service has no purpose that requires special-category or criminal-offence
data and selects no Article 9(2) or Article 10 condition. Users are instructed
not to provide it. Apparent sensitive content in a CV is screened locally and
rejected before persistence/provider transfer. Apparent sensitive content in a
Compass answer must be removed rather than extracted into a profile.

Because free text can contain unexpected sensitive data, prohibition alone is
not a complete safeguard. The launch requires the point-of-use warning,
screening, incident/deletion path, and DPIA controls.

## Consent standard for optional CV processing

The CV action must be:

- separate from Terms acceptance and Privacy acknowledgement;
- specific to the displayed, edited text and OpenAI transfer;
- optional, with an equivalent manual Compass route;
- recorded by notice/consent version and time without storing the CV text;
- withdrawable for future processing, with a clear statement that an already
  completed request cannot be undone but retained data can be deleted where
  applicable.

## Review questions

Counsel must confirm the contract/consent split, the correct German consumer-law
classification of the free alpha, whether a DPO or EU representative is
required, the competent supervisory authority, and whether any processing
requires prior consultation under Article 36.
