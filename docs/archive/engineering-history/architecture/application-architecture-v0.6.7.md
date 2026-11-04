> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Application Architecture v0.6.7

## Product navigation

- **Compass** owns free-text profile input, targeted edits, Review Tray
  decisions, and private CV evidence.
- **Matching** owns reference settings, match runs, and the Top / Stretch /
  Blocked result story.
- **Archive** owns the durable job corpus, current source state, revisions,
  retry, and deletion.
- `/jobs/{record_id}` is the canonical Job Detail for both unmatched and
  matched states. Legacy match-detail URLs validate access and redirect there.

## Evidence flow

1. A public job URL is fetched under the existing SSRF, redirect, robots, size,
   content-type, and expiration rules.
2. The LLM produces typed advertisement facts with verbatim source excerpts.
3. A deterministic context pass adds only verbatim working-mode facts and a
   confidence-labelled employer assessment.
4. Confirmed Compass facts, route assessments, and job evidence enter the
   deterministic matching algorithm.
5. One immutable result snapshot stores reasons, employer context, working-mode
   facts, commute diagnostics, score, group, and algorithm version.
6. The canonical Job Detail combines that snapshot with current source state
   and explicit user feedback/application records.

## Employer relationship assessment

The assessment order is conservative:

1. Explicit staffing, employee-leasing, recruitment, or direct-employment
   language in the advertisement wins.
2. Job-platform and applicant-tracking domains never prove employer identity.
3. A company-name/domain match can support **likely direct employer** with
   medium confidence.
4. When enabled, the same public company homepage is checked for explicit
   staffing/recruitment markers. Fetch failures return unknown, not a guess.
5. The final legal employer must still be confirmed in the employment contract.

No search-engine scraping or hidden account access is used.

## Mobility provider chain

`TravelTimeProvider` remains the application boundary.

- Google Routes is first choice when `GOOGLE_ROUTES_API_KEY` is present.
- openrouteservice can provide car, bicycle, and walking fallback when
  `OPENROUTESERVICE_API_KEY` is present.
- Public transit has no automatic third-party fallback in v0.6.7. Transitous
  asks routing and commercial consumers to contact the project, so it remains
  disabled until permission and operating expectations are agreed.
- Every result records provider attempts, source attribution, route time,
  optional distance, and failure reason.
- Google route duration/distance is not persisted under the applicable EEA
  service terms. Permitted openrouteservice results may use the private
  seven-day cache.

## CV privacy boundary

- Accepted formats: text-based PDF, DOCX, and UTF-8 TXT; maximum 5 MB.
- Parsing happens inside the application process.
- Uploaded binary bytes are never written to disk or a database.
- Extracted text can be retained until user deletion or deleted immediately
  after evidence extraction.
- Full CV text is never written to conversation history or profile raw-section
  answers.
- Only atomic model proposals enter the Review Tray, and no proposal affects
  matching until the user confirms it.
- Cascade deletion removes retained CV text when its Compass workspace is
  deleted.

## Persistence

Alembic revision `0006_cv_documents` adds `cv_documents`. Match snapshots remain
JSON-based and backward-compatible because new employer, work-mode, mobility,
and diagnostic fields have defaults.

## Known boundaries

- Scanned PDFs require OCR before upload.
- Homepage employer assessment is synchronous and intentionally bounded; a
  background research queue is a later scaling improvement.
- CV rewriting and cover-letter generation are not part of this release.
- Authentication, cross-user isolation, payments, and subscriptions remain
  later release gates.
