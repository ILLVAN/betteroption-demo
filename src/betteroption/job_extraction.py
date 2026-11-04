"""Structured extraction contract for untrusted job advertisements."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime

from pydantic import AnyHttpUrl, Field

from .application_guidance import (
    ApplicationChannel,
    ApplicationGuidance,
    ApplicationGuidanceEntry,
    extract_application_guidance,
    merge_application_guidance,
)
from .jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from .profile import StrictModel


_PUNCTUATION_EQUIVALENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "…": "...",
    }
)


@dataclass(frozen=True)
class EvidenceIssue:
    key: str
    quote: str


class UnverifiedEvidenceError(ValueError):
    """Raised when model-proposed evidence cannot be mapped to the source."""

    def __init__(self, issues: list[EvidenceIssue]) -> None:
        self.issues = tuple(issues)
        details = "; ".join(f"{issue.key}: {issue.quote!r}" for issue in issues)
        super().__init__(f"unverified model evidence: {details}")


def _normalized_with_source_map(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    source_positions: list[int] = []
    for source_index, character in enumerate(value):
        expanded = unicodedata.normalize("NFKC", character).translate(_PUNCTUATION_EQUIVALENTS)
        for result_character in expanded.casefold():
            if result_character.isspace():
                if normalized and normalized[-1] != " ":
                    normalized.append(" ")
                    source_positions.append(source_index)
                continue
            normalized.append(result_character)
            source_positions.append(source_index)
    if normalized and normalized[-1] == " ":
        normalized.pop()
        source_positions.pop()
    return "".join(normalized), source_positions


def resolve_evidence_quote(source_text: str, proposed_quote: str) -> str | None:
    """Return the exact source span for a safely normalizable model quotation."""

    normalized_source, source_positions = _normalized_with_source_map(source_text)
    normalized_quote, _ = _normalized_with_source_map(proposed_quote.strip())
    if not normalized_quote:
        return None
    normalized_start = normalized_source.find(normalized_quote)
    if normalized_start < 0:
        return None
    normalized_end = normalized_start + len(normalized_quote) - 1
    source_start = source_positions[normalized_start]
    source_end = source_positions[normalized_end] + 1
    return source_text[source_start:source_end]


class JobFactDraft(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    value: str = Field(min_length=1, max_length=1_000)
    kind: JobFactKind
    evidence_quote: str = Field(min_length=1, max_length=2_000)


class ApplicationGuidanceEntryDraft(StrictModel):
    value: str = Field(min_length=1, max_length=2_000)
    evidence_quote: str = Field(min_length=1, max_length=2_000)


class ApplicationGuidanceDraft(StrictModel):
    contact_name: ApplicationGuidanceEntryDraft | None = None
    contact_role: ApplicationGuidanceEntryDraft | None = None
    contact_email: ApplicationGuidanceEntryDraft | None = None
    contact_phone: ApplicationGuidanceEntryDraft | None = None
    postal_address: ApplicationGuidanceEntryDraft | None = None
    application_channel: ApplicationGuidanceEntryDraft | None = None
    application_url: ApplicationGuidanceEntryDraft | None = None
    requested_documents: list[ApplicationGuidanceEntryDraft] = Field(default_factory=list)
    max_file_size: ApplicationGuidanceEntryDraft | None = None
    max_pages: ApplicationGuidanceEntryDraft | None = None
    application_deadline: ApplicationGuidanceEntryDraft | None = None
    instructions: list[ApplicationGuidanceEntryDraft] = Field(default_factory=list)


class JobExtraction(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2_000)
    facts: list[JobFactDraft]
    application_guidance: ApplicationGuidanceDraft = Field(default_factory=ApplicationGuidanceDraft)

    def to_job_posting(
        self,
        *,
        source_text: str,
        source_name: str,
        source_url: AnyHttpUrl | str,
        requested_url: AnyHttpUrl | str,
        url_http_status: int,
        url_checked_at: datetime,
        drop_unverified: bool = False,
        include_application_guidance: bool = True,
    ) -> JobPosting:
        verified_facts: list[JobFact] = []
        issues: list[EvidenceIssue] = []
        for draft in self.facts:
            evidence_quote = resolve_evidence_quote(source_text, draft.evidence_quote)
            if evidence_quote is None:
                issues.append(EvidenceIssue(key=draft.key, quote=draft.evidence_quote))
                continue
            verified_facts.append(
                JobFact(
                    key=_correct_fact_key(draft.key, draft.value),
                    value=draft.value,
                    kind=draft.kind,
                    evidence_quote=evidence_quote,
                )
            )
        model_guidance = ApplicationGuidance()
        if include_application_guidance:
            model_guidance, guidance_issues = _verified_application_guidance(
                self.application_guidance,
                source_text=source_text,
                source_url=str(source_url),
            )
            issues.extend(guidance_issues)
        if issues and not drop_unverified:
            raise UnverifiedEvidenceError(issues)

        application_guidance = ApplicationGuidance()
        if include_application_guidance:
            application_guidance = merge_application_guidance(
                extract_application_guidance(source_text, source_url=str(source_url)),
                model_guidance,
            )

        return JobPosting(
            title=self.title,
            company=self.company,
            location=self.location,
            summary=self.summary,
            source_type=JobSourceType.URL_TEXT,
            source_name=source_name,
            source_url=source_url,
            requested_url=requested_url,
            url_status=JobUrlStatus.VERIFIED_REACHABLE,
            url_http_status=url_http_status,
            url_checked_at=url_checked_at,
            source_text=source_text,
            application_guidance=application_guidance,
            facts=verified_facts,
            extraction_warnings=[
                f"Omitted unverified {issue.key} evidence: {issue.quote[:160]!r}"
                for issue in issues
            ],
        )


def _private_guidance_value_is_grounded(key: str, value: str, evidence: str) -> bool:
    """Require identity/coordinate values themselves to occur in their evidence."""

    if key in {"application.contact_name", "application.contact_role"}:
        normalized_value, _ = _normalized_with_source_map(value)
        normalized_evidence, _ = _normalized_with_source_map(evidence)
        return bool(normalized_value) and normalized_value in normalized_evidence
    if key == "application.contact_email":
        return value.casefold().strip() in evidence.casefold()
    if key == "application.contact_phone":
        value_digits = "".join(character for character in value if character.isdigit())
        evidence_digits = "".join(character for character in evidence if character.isdigit())
        return len(value_digits) >= 6 and value_digits in evidence_digits
    if key == "application.postal_address":
        normalized_value, _ = _normalized_with_source_map(value)
        normalized_evidence, _ = _normalized_with_source_map(evidence)
        return bool(normalized_value) and normalized_value in normalized_evidence
    if key == "application.application_url":
        clean_value = value.casefold().strip().rstrip("/.,;:)]}")
        clean_evidence = evidence.casefold().strip().rstrip("/.,;:)]}")
        return bool(clean_value) and clean_value in clean_evidence
    return True


def _verified_application_guidance(
    draft: ApplicationGuidanceDraft,
    *,
    source_text: str,
    source_url: str,
) -> tuple[ApplicationGuidance, list[EvidenceIssue]]:
    issues: list[EvidenceIssue] = []

    def verified(
        key: str,
        item: ApplicationGuidanceEntryDraft | None,
    ) -> ApplicationGuidanceEntry | None:
        if item is None:
            return None
        evidence = resolve_evidence_quote(source_text, item.evidence_quote)
        if evidence is None:
            issues.append(EvidenceIssue(key=key, quote=item.evidence_quote))
            return None
        value = item.value.strip()
        if key == "application.application_channel":
            try:
                value = ApplicationChannel(value.casefold().replace(" ", "_")).value
            except ValueError:
                issues.append(EvidenceIssue(key=key, quote=item.evidence_quote))
                return None
        if not _private_guidance_value_is_grounded(key, value, evidence):
            issues.append(EvidenceIssue(key=key, quote=item.evidence_quote))
            return None
        return ApplicationGuidanceEntry(
            value=value,
            evidence_quote=evidence,
            source_url=source_url,
        )

    def verified_many(
        key: str,
        items: list[ApplicationGuidanceEntryDraft],
    ) -> tuple[ApplicationGuidanceEntry, ...]:
        return tuple(
            result
            for index, item in enumerate(items)
            if (result := verified(f"{key}.{index}", item)) is not None
        )

    return (
        ApplicationGuidance(
            contact_name=verified("application.contact_name", draft.contact_name),
            contact_role=verified("application.contact_role", draft.contact_role),
            contact_email=verified("application.contact_email", draft.contact_email),
            contact_phone=verified("application.contact_phone", draft.contact_phone),
            postal_address=verified("application.postal_address", draft.postal_address),
            application_channel=verified(
                "application.application_channel", draft.application_channel
            ),
            application_url=verified("application.application_url", draft.application_url),
            requested_documents=verified_many(
                "application.requested_documents", draft.requested_documents
            ),
            max_file_size=verified("application.max_file_size", draft.max_file_size),
            max_pages=verified("application.max_pages", draft.max_pages),
            application_deadline=verified(
                "application.application_deadline", draft.application_deadline
            ),
            instructions=verified_many("application.instructions", draft.instructions),
        ),
        issues,
    )


def _correct_fact_key(key: str, value: str) -> str:
    """Keep generic experience and interest statements out of skill coverage."""

    if key != "skill.name":
        return key
    normalized = " ".join(value.casefold().split())
    if any(
        marker in normalized
        for marker in (
            "experience in",
            "experience with",
            "professional experience",
            "software development experience",
            "years of experience",
        )
    ):
        return "candidate.experience"
    if any(
        marker in normalized
        for marker in (
            "interest in",
            "interested in",
            "enthusiasm for",
            "passion for",
        )
    ):
        return "candidate.interest"
    return key
