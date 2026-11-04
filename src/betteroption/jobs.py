"""Canonical, evidence-backed job advertisement models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, Field, model_validator

from .application_guidance import ApplicationGuidance, GuidanceProvenance
from .profile import StrictModel
from .posting_date import (
    PostingDateConfidence,
    PostingDateSource,
    extract_posting_date,
)


class JobSourceType(StrEnum):
    URL_TEXT = "url_text"
    MANUAL_TEXT = "manual_text"
    SAMPLE = "sample"


class JobUrlStatus(StrEnum):
    VERIFIED_REACHABLE = "verified_reachable"


class JobFactKind(StrEnum):
    REQUIREMENT = "requirement"
    PREFERENCE = "preference"
    OFFER = "offer"
    CONTEXT = "context"


class JobFact(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    value: str = Field(min_length=1, max_length=1_000)
    kind: JobFactKind
    evidence_quote: str = Field(min_length=1, max_length=2_000)


class JobPosting(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2_000)
    source_type: JobSourceType
    source_name: str = Field(min_length=1, max_length=1_000)
    source_url: AnyHttpUrl | None = None
    requested_url: AnyHttpUrl | None = None
    url_status: JobUrlStatus | None = None
    url_http_status: int | None = Field(default=None, ge=100, le=599)
    url_checked_at: datetime | None = None
    source_text: str = Field(min_length=1, max_length=150_000)
    content_hash: str = Field(default="", pattern=r"^$|^[a-f0-9]{64}$")
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    posting_date: date | None = None
    posting_date_source: PostingDateSource | None = None
    posting_date_confidence: PostingDateConfidence | None = None
    posting_date_evidence_quote: str | None = Field(default=None, max_length=500)
    application_guidance: ApplicationGuidance = Field(default_factory=ApplicationGuidance)
    facts: list[JobFact] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_is_verbatim_and_hash_is_valid(self) -> JobPosting:
        source = self.source_text.casefold()
        for fact in self.facts:
            if fact.evidence_quote.casefold() not in source:
                raise ValueError(
                    f"evidence quote for {fact.key} does not occur verbatim in source_text"
                )
        for entry in self.application_guidance.entries():
            if (
                entry.provenance == GuidanceProvenance.ADVERTISEMENT
                and (entry.evidence_quote or "").casefold() not in source
            ):
                raise ValueError(
                    "application-guidance evidence does not occur verbatim in source_text"
                )

        expected_hash = sha256(self.source_text.encode("utf-8")).hexdigest()
        if self.content_hash and self.content_hash != expected_hash:
            raise ValueError("content_hash does not match source_text")
        object.__setattr__(self, "content_hash", expected_hash)

        # Re-derive this field from attributable source evidence even when an
        # extractor/provider supplied the optional output fields.  This keeps a
        # free-form model value from becoming a posting date without a matching
        # verbatim label in the advertisement.
        extracted_date = extract_posting_date(
            self.source_text,
            observed_at=self.observed_at,
            facts=((fact.key, fact.value, fact.evidence_quote) for fact in self.facts),
        )
        object.__setattr__(
            self,
            "posting_date",
            extracted_date.value if extracted_date is not None else None,
        )
        object.__setattr__(
            self,
            "posting_date_source",
            extracted_date.source if extracted_date is not None else None,
        )
        object.__setattr__(
            self,
            "posting_date_confidence",
            extracted_date.confidence if extracted_date is not None else None,
        )
        object.__setattr__(
            self,
            "posting_date_evidence_quote",
            extracted_date.evidence_quote if extracted_date is not None else None,
        )

        if self.source_type == JobSourceType.URL_TEXT:
            if not self.source_url or not self.requested_url:
                raise ValueError("URL jobs require requested_url and source_url")
            if self.url_status != JobUrlStatus.VERIFIED_REACHABLE:
                raise ValueError("URL jobs must be verified reachable before matching")
            if self.url_http_status is None or not 200 <= self.url_http_status < 300:
                raise ValueError("URL jobs require a successful HTTP status")
            if self.url_checked_at is None:
                raise ValueError("URL jobs require a reachability timestamp")
        elif self.source_type == JobSourceType.MANUAL_TEXT:
            if (self.source_url is None) != (self.requested_url is None):
                raise ValueError(
                    "manual jobs must provide both source_url and requested_url or neither"
                )
            if any(
                value is not None
                for value in (
                    self.url_status,
                    self.url_http_status,
                    self.url_checked_at,
                )
            ):
                raise ValueError("manual job text cannot claim live URL verification")
        elif any(
            value is not None
            for value in (
                self.source_url,
                self.requested_url,
                self.url_status,
                self.url_http_status,
                self.url_checked_at,
            )
        ):
            raise ValueError("fictional sample jobs cannot claim live URL verification")
        return self


def save_job(job: JobPosting, directory: Path = Path("local-data") / "jobs") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"job-{job.id}.json"
    path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_job(path: Path) -> JobPosting:
    return JobPosting.model_validate_json(path.read_text(encoding="utf-8"))


KNOWN_DEMO_EMPLOYERS = {
    "the demo data gmbh",
    "the demo daten gmbh",
}


_GENERIC_EMPLOYER_NAMES = frozenset(
    {
        "company not stated",
        "employer not stated",
        "external source",
        "manual input",
        "none",
        "not stated",
        "portal source",
        "public source",
        "source website",
        "traceable company",
        "unknown",
        "unknown company",
        "unavailable",
    }
)

_UNTRUSTED_EMPLOYER_IDENTITY_HOSTS = (
    "greenhouse.io",
    "indeed.",
    "jobijoba.",
    "lever.co",
    "linkedin.",
    "myworkdayjobs.com",
    "personio.",
    "smartrecruiters.com",
    "stepstone.",
    "xing.",
)

_COMMON_COUNTRY_SECOND_LEVEL_DOMAINS = frozenset({"ac", "co", "com", "edu", "gov", "net", "org"})


def _generic_employer_name(value: str) -> bool:
    normalized = " ".join(value.casefold().split()).strip(" .,:;!?-/")
    return (
        normalized in _GENERIC_EMPLOYER_NAMES
        or normalized.startswith("unknown ")
        or normalized.endswith(" not stated")
    )


def _first_party_host_brand(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    if not host or any(marker in host for marker in _UNTRUSTED_EMPLOYER_IDENTITY_HOSTS):
        return None
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return None
    label_index = -2
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and labels[-2] in _COMMON_COUNTRY_SECOND_LEVEL_DOMAINS
    ):
        label_index = -3
    brand = labels[label_index].strip("-_")
    if brand in {"apply", "career", "careers", "job", "jobs", "recruiting"}:
        return None
    return brand if len(brand) >= 3 else None


def _source_backed_host_employer(
    job: JobPosting,
    *,
    homepage_text: str | None = None,
) -> str | None:
    source_url = str(job.source_url or job.requested_url or "")
    brand = _first_party_host_brand(source_url)
    if brand is None:
        return None

    # A domain label is only a candidate. Require the same brand to be visibly
    # named by the advertisement or an explicitly fetched first-party homepage;
    # the URL by itself never becomes a rateable employer identity.
    tokens = [token for token in re.split(r"[-_]+", brand) if token]
    pattern = re.compile(
        rf"(?<![\w]){'[\\s._-]*'.join(re.escape(token) for token in tokens)}(?![\w])",
        flags=re.IGNORECASE,
    )
    evidence_texts = [job.source_text]
    if homepage_text:
        evidence_texts.append(homepage_text)
    matches = [match for evidence in evidence_texts for match in pattern.finditer(evidence)]
    if not matches:
        return None

    combined = "\n".join(evidence_texts)
    folded = combined.casefold()
    brand_pattern = pattern.pattern
    identity_pattern = re.compile(
        rf"(?:welcome\s+to|willkommen\s+bei|about|über\s+uns|join|karriere\s+bei|"
        rf"employer|arbeitgeber).{{0,100}}{brand_pattern}|"
        rf"{brand_pattern}.{{0,100}}(?:employer|arbeitgeber|is\s+(?:a|an)|ist\s+(?:ein|eine))",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(matches) < 2 and identity_pattern.search(folded) is None:
        return None
    return matches[0].group(0).strip(" .,:;!?-/")


def normalize_placeholder_employer(
    job: JobPosting,
    *,
    homepage_text: str | None = None,
) -> JobPosting:
    """Resolve only source-backed placeholders, never an arbitrary domain tenant.

    Personio's public demo tenant can leak into otherwise real JobPosting
    metadata. This narrow correction does not guess arbitrary employer names:
    it applies only to a documented placeholder and requires a repeated,
    explicit ``Why <employer>?`` / ``Warum <employer>?`` identity in the job
    body. Generic names can additionally be resolved from a first-party URL
    only when the same brand is named in the job source or fetched homepage.
    ATS, aggregator, and unproved host labels remain unresolved so unrelated
    employer ratings can never be merged.
    """

    normalized_company = " ".join(job.company.casefold().split())
    if normalized_company in KNOWN_DEMO_EMPLOYERS:
        candidates = re.findall(
            r"(?:warum|why)\s+([a-zA-Z0-9ÄÖÜäöüß&.+-]{2,80}(?:\s+(?:GmbH|AG|SE|UG|Ltd\.?|Inc\.?))?)\s*[?!]",
            job.source_text,
            flags=re.IGNORECASE,
        )
        for candidate in candidates:
            clean = " ".join(candidate.split()).strip(" .,:;!?")
            if clean.casefold() in KNOWN_DEMO_EMPLOYERS:
                continue
            occurrences = len(
                re.findall(
                    rf"(?<![\w]){re.escape(clean)}(?![\w])",
                    job.source_text,
                    flags=re.IGNORECASE,
                )
            )
            if occurrences < 2:
                continue
            warning = (
                f"Replaced known ATS demo employer placeholder {job.company!r} with "
                f"the repeatedly named employer {clean!r}."
            )
            return job.model_copy(
                update={
                    "company": clean,
                    "extraction_warnings": [*job.extraction_warnings, warning],
                }
            )

    if not _generic_employer_name(job.company):
        return job
    resolved = _source_backed_host_employer(job, homepage_text=homepage_text)
    if resolved is None:
        return job
    warning = (
        f"Resolved generic employer placeholder {job.company!r} as {resolved!r} only after "
        "the first-party host brand was also found in public source evidence."
    )
    return job.model_copy(
        update={
            "company": resolved,
            "extraction_warnings": [*job.extraction_warnings, warning],
        }
    )
