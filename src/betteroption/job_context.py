"""Conservative employer and working-mode context derived from public evidence."""

from __future__ import annotations

import re
from hashlib import sha256
from datetime import datetime, timezone
from enum import StrEnum
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import Field

from .company_intelligence import (
    CompanyIntelligence,
    CompanyIntelligenceService,
    CompanyResearchProvider,
)
from .jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from .profile import StrictModel
from .url_ingestion import PublicUrlFetcher, UrlIngestionError


class EmployerKind(StrEnum):
    DIRECT_EMPLOYER = "direct_employer"
    STAFFING_AGENCY = "staffing_agency"
    RECRUITMENT_AGENCY = "recruitment_agency"
    FREELANCE = "freelance"
    CONTRACTOR = "contractor"
    INTERMEDIARY = "intermediary"
    PLATFORM = "platform"
    CONSULTANCY = "consultancy"
    OTHER = "other"
    UNKNOWN = "unknown"

    @property
    def likely_direct_contract(self) -> bool | None:
        """Express only what the relationship category actually establishes.

        The established agency categories remain explicitly indirect. The new
        categories describe nuanced commercial arrangements and therefore do
        not, by themselves, prove who signs the employment contract.
        """

        if self == EmployerKind.DIRECT_EMPLOYER:
            return True
        if self in {EmployerKind.STAFFING_AGENCY, EmployerKind.RECRUITMENT_AGENCY}:
            return False
        return None


class ContextConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EmployerAssessment(StrictModel):
    kind: EmployerKind
    confidence: ContextConfidence
    likely_direct_contract: bool | None = None
    explanation: str
    evidence_quotes: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobContext(StrictModel):
    employer: EmployerAssessment
    work_mode_facts: list[JobFact] = Field(default_factory=list)
    company_intelligence: CompanyIntelligence | None = None


AGGREGATOR_OR_ATS_HOSTS = (
    "indeed.",
    "linkedin.",
    "stepstone.",
    "xing.",
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "personio.",
)

RESTRICTED_SOURCE_HOSTS = (
    "indeed.",
    "linkedin.",
    "stepstone.",
    "xing.",
)

STAFFING_MARKERS = (
    "arbeitnehmerüberlassung",
    "arbeitnehmerueberlassung",
    "zeitarbeit",
    "personaldienstleister",
    "temporary staffing",
    "temporary agency",
    "temporary agency work",
    "employee leasing",
    "staffing company",
)

RECRUITMENT_MARKERS = (
    "personalvermittlung",
    "recruitment agency",
    "recruiting agency",
    "im auftrag unseres kunden",
    "on behalf of our client",
    "for our client",
)

DIRECT_MARKERS = (
    "direkte festanstellung",
    "festanstellung bei uns",
    "direct employment",
    "direct contract with us",
    "join our team",
    "werde teil unseres teams",
)

WORK_MODE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "work_model.remote",
        "remote",
        re.compile(r"\b(?:fully remote|remote work|100\s*% remote|remote-first)\b", re.I),
    ),
    (
        "work_model.hybrid",
        "hybrid",
        re.compile(r"\b(?:hybrid(?: work)?|mobiles arbeiten|mobile work|homeoffice)\b", re.I),
    ),
    (
        "work_model.onsite",
        "on-site",
        re.compile(r"\b(?:on[- ]site|vor ort|präsenz(?:arbeit)?|office[- ]based)\b", re.I),
    ),
    (
        "work_model.shift_work",
        "shift work",
        re.compile(r"\b(?:shift work|schichtarbeit|schichtdienst|three[- ]shift)\b", re.I),
    ),
    (
        "travel.frequency",
        "business travel",
        re.compile(r"\b(?:business travel|travel required|reisebereitschaft|dienstreisen)\b", re.I),
    ),
)

OFFICE_DAYS_PATTERN = re.compile(
    r"(?P<quote>(?P<days>[1-5])\s+(?:days?|tage)\s+(?:per|a|pro)\s+(?:week|woche)[^.\n]{0,45}(?:office|on[- ]site|vor ort|präsenz))",
    re.I,
)

WEEKLY_HOURS_PATTERN = re.compile(
    r"(?P<quote>\b(?P<hours>\d{2}(?:[.,]\d)?)\s*(?:hours?|stunden)\s*(?:per|a|pro)?\s*(?:week|woche)\b)",
    re.I,
)


def restricted_source_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    return any(marker in host for marker in AGGREGATOR_OR_ATS_HOSTS)


def source_guidance(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold()
    if "linkedin." in host:
        return (
            "LinkedIn does not permit this application to fetch the advertisement. "
            "Add the same role from the employer's careers page as its canonical source."
        )
    if any(marker in host for marker in RESTRICTED_SOURCE_HOSTS):
        return (
            "This platform may restrict automated access. Prefer the employer's public careers "
            "page so the job remains verifiable and traceable."
        )
    return None


class EmployerContextService:
    """Assess employer identity without turning absence of evidence into certainty."""

    def __init__(
        self,
        *,
        fetcher: PublicUrlFetcher | None = None,
        research_homepages: bool = True,
        company_research_provider: CompanyResearchProvider | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.research_homepages = research_homepages
        self.company_intelligence = CompanyIntelligenceService(company_research_provider)
        self._context_cache: dict[tuple[str, str, str], JobContext] = {}

    def assess(self, job: JobPosting) -> JobContext:
        source_url = str(job.source_url or job.requested_url or "")
        cache_key = (
            " ".join(job.company.casefold().split()),
            source_url,
            sha256(job.source_text.encode("utf-8")).hexdigest(),
        )
        cached = self._context_cache.get(cache_key)
        if cached is not None:
            return cached
        source_text = job.source_text
        evidence_url = source_url or None
        employer = self._classify_text(source_text, evidence_url)
        host = (urlsplit(source_url).hostname or "").casefold()
        homepage_text: str | None = None
        homepage_url: str | None = None
        source_may_be_fetched = job.source_type != JobSourceType.MANUAL_TEXT

        if source_may_be_fetched and source_url and self._company_matches_host(job.company, host):
            homepage_text, homepage_url = self._homepage(source_url)
        elif source_may_be_fetched and (
            employer_website := _employer_website_from_source_text(source_text)
        ):
            candidate_host = (urlsplit(employer_website).hostname or "").casefold()
            if self._company_matches_host(job.company, candidate_host):
                homepage_text, homepage_url = self._homepage(employer_website)

        if employer.kind == EmployerKind.UNKNOWN and source_url and source_may_be_fetched:
            if restricted_source_host(source_url):
                employer = EmployerAssessment(
                    kind=EmployerKind.UNKNOWN,
                    confidence=ContextConfidence.LOW,
                    likely_direct_contract=None,
                    explanation=(
                        "The source is a job platform or applicant-tracking system, so its domain "
                        "does not prove who the legal employer will be."
                    ),
                    evidence_urls=[source_url],
                )
            elif self._company_matches_host(job.company, host):
                researched = self._classify_text(homepage_text or "", homepage_url)
                if researched.kind != EmployerKind.UNKNOWN:
                    employer = researched
                else:
                    employer = EmployerAssessment(
                        kind=EmployerKind.DIRECT_EMPLOYER,
                        confidence=ContextConfidence.MEDIUM,
                        likely_direct_contract=True,
                        explanation=(
                            "The verified job is hosted on a domain matching the named employer. "
                            "That supports a likely direct-employer relationship, but the final "
                            "contract should still be checked."
                        ),
                        evidence_urls=[url for url in (source_url, homepage_url) if url],
                    )

        intelligence = self.company_intelligence.analyze(
            job,
            homepage_text=homepage_text,
            homepage_url=homepage_url,
        )
        employer = self._apply_company_category(employer, intelligence)
        context = JobContext(
            employer=employer,
            work_mode_facts=self._work_mode_facts(job),
            company_intelligence=intelligence,
        )
        if len(self._context_cache) >= 256:
            self._context_cache.pop(next(iter(self._context_cache)))
        self._context_cache[cache_key] = context
        return context

    @staticmethod
    def _apply_company_category(
        employer: EmployerAssessment,
        intelligence: CompanyIntelligence,
    ) -> EmployerAssessment:
        categories = set(intelligence.product.categories)
        kind = None
        if "staffing" in categories:
            kind = EmployerKind.STAFFING_AGENCY
        elif "recruitment" in categories:
            kind = EmployerKind.RECRUITMENT_AGENCY
        if kind is not None and employer.confidence != ContextConfidence.HIGH:
            return EmployerAssessment(
                kind=kind,
                confidence=ContextConfidence.MEDIUM,
                likely_direct_contract=False,
                explanation=(
                    "Attributed company research identifies staffing or recruitment as part of the "
                    "business model. Confirm the legal employer and contract before applying."
                ),
                evidence_quotes=intelligence.product.evidence_quotes,
                evidence_urls=intelligence.product.evidence_urls,
            )
        if employer.kind != EmployerKind.UNKNOWN or not categories:
            return employer
        if " ".join(intelligence.company.casefold().split()) in {
            "unknown",
            "not stated",
            "confidential",
            "confidential employer",
        }:
            return employer
        if (
            intelligence.product.confidence.value not in {"medium", "high"}
            or not intelligence.product.evidence_urls
        ):
            return employer
        return EmployerAssessment(
            kind=EmployerKind.DIRECT_EMPLOYER,
            confidence=ContextConfidence.MEDIUM,
            likely_direct_contract=True,
            explanation=(
                "Attributed public evidence identifies the named hiring organization as an "
                "operating company with its own products or services, while no staffing or "
                "recruitment business model was found. This supports a likely direct-employer "
                "relationship; confirm the legal entity in the final contract."
            ),
            evidence_quotes=intelligence.product.evidence_quotes,
            evidence_urls=intelligence.product.evidence_urls,
        )

    @staticmethod
    def _classify_text(text: str, evidence_url: str | None) -> EmployerAssessment:
        normalized = " ".join(text.casefold().split())
        for kind, markers, explanation in (
            (
                EmployerKind.STAFFING_AGENCY,
                STAFFING_MARKERS,
                "Public employer or advertisement text identifies temporary staffing or employee leasing.",
            ),
            (
                EmployerKind.RECRUITMENT_AGENCY,
                RECRUITMENT_MARKERS,
                "Public employer or advertisement text describes recruitment on behalf of a client.",
            ),
            (
                EmployerKind.DIRECT_EMPLOYER,
                DIRECT_MARKERS,
                "The advertisement explicitly describes joining or contracting directly with the hiring team.",
            ),
        ):
            marker = next((item for item in markers if item in normalized), None)
            if marker:
                quote = _source_excerpt(text, marker)
                return EmployerAssessment(
                    kind=kind,
                    confidence=ContextConfidence.HIGH,
                    likely_direct_contract=kind == EmployerKind.DIRECT_EMPLOYER,
                    explanation=explanation,
                    evidence_quotes=[quote] if quote else [marker],
                    evidence_urls=[evidence_url] if evidence_url else [],
                )
        return EmployerAssessment(
            kind=EmployerKind.UNKNOWN,
            confidence=ContextConfidence.LOW,
            likely_direct_contract=None,
            explanation="No reliable public evidence establishes the contractual employer type yet.",
            evidence_urls=[evidence_url] if evidence_url else [],
        )

    @lru_cache(maxsize=128)
    def _homepage(self, source_url: str) -> tuple[str | None, str | None]:
        if not self.research_homepages:
            return None, None
        parsed = urlsplit(source_url)
        if not parsed.hostname or parsed.hostname.endswith(
            (".example", ".test", ".invalid", "example.com", "example.org", "example.net")
        ):
            return None, None
        homepage_url = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
        try:
            fetcher = self.fetcher or PublicUrlFetcher(
                client=httpx.Client(follow_redirects=False, timeout=5.0, trust_env=False)
            )
            document = fetcher.fetch(homepage_url)
        except (UrlIngestionError, ValueError):
            return None, homepage_url
        return document.text, document.final_url

    @staticmethod
    def _company_matches_host(company: str, host: str) -> bool:
        company_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", company.casefold())
            if len(token) >= 4 and token not in {"group", "gruppe", "gmbh", "company"}
        }
        host_tokens = set(re.findall(r"[a-z0-9]+", host))
        return bool(company_tokens.intersection(host_tokens))

    @staticmethod
    def _work_mode_facts(job: JobPosting) -> list[JobFact]:
        existing = {(fact.key, fact.value.casefold()) for fact in job.facts}
        facts: list[JobFact] = []
        for key, value, pattern in WORK_MODE_PATTERNS:
            match = pattern.search(job.source_text)
            if match and (key, value.casefold()) not in existing:
                facts.append(
                    JobFact(
                        key=key,
                        value=value,
                        kind=JobFactKind.CONTEXT,
                        evidence_quote=match.group(0),
                    )
                )
        for pattern, key, value_group in (
            (OFFICE_DAYS_PATTERN, "work_model.office_days", "days"),
            (WEEKLY_HOURS_PATTERN, "work_model.weekly_hours", "hours"),
        ):
            match = pattern.search(job.source_text)
            if match:
                value = match.group(value_group).replace(",", ".")
                if (key, value.casefold()) not in existing:
                    facts.append(
                        JobFact(
                            key=key,
                            value=value,
                            kind=JobFactKind.CONTEXT,
                            evidence_quote=match.group("quote"),
                        )
                    )
        return facts


def _source_excerpt(text: str, marker: str) -> str | None:
    index = text.casefold().find(marker.casefold())
    if index < 0:
        return None
    start = max(0, index - 80)
    end = min(len(text), index + len(marker) + 120)
    return " ".join(text[start:end].split())


def _employer_website_from_source_text(text: str) -> str | None:
    """Read a traceable employer URL preserved from schema.org JobPosting data."""

    match = re.search(r"Employer website:\s*(https?://[^\s<>\"']+)", text, flags=re.I)
    if match is None:
        return None
    value = match.group(1).rstrip(".,);]")
    parsed = urlsplit(value)
    if not parsed.hostname or restricted_source_host(value):
        return None
    return value
