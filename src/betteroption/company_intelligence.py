"""Evidence-backed company product and employer-reputation context."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from urllib.parse import quote_plus, urlsplit

import httpx
from pydantic import Field

from .brave_search import BRAVE_WEB_SEARCH_ENDPOINT, request_brave_web_results
from .jobs import JobPosting
from .profile import StrictModel


class IntelligenceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompanyEvidence(StrictModel):
    label: str
    summary: str
    source_url: str


class CompanyResearchHit(StrictModel):
    title: str
    description: str = ""
    url: str
    purpose: "ResearchPurpose" = Field(default_factory=lambda: ResearchPurpose.REPUTATION)


class ResearchPurpose(StrEnum):
    BUSINESS = "business"
    REPUTATION = "reputation"


class CompanyResearchProvider(Protocol):
    def research(self, company: str) -> list[CompanyResearchHit]:
        """Return attributed business or reputation evidence, never scraped reviews."""


class CompanyProductProfile(StrictModel):
    summary: str
    revenue_model: str
    categories: list[str] = Field(default_factory=list)
    sensitive_categories: list[str] = Field(default_factory=list)
    confidence: IntelligenceConfidence
    evidence_quotes: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)


class EmployerReputationSummary(StrictModel):
    kununu_score: float | None = Field(default=None, ge=1, le=5)
    kununu_review_count: int | None = Field(default=None, ge=1)
    kununu_source_url: str | None = None
    kununu_manual_url: str
    summary: str
    signals: list[CompanyEvidence] = Field(default_factory=list)
    review_links: list["ReviewProfileLink"] = Field(default_factory=list)
    caveat: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewProfileLink(StrictModel):
    label: str
    url: str


class CompanyIntelligence(StrictModel):
    company: str
    product: CompanyProductProfile
    reputation: EmployerReputationSummary


class WikimediaCompanyResearchProvider:
    """Use the public MediaWiki API for keyless, attributed company summaries."""

    name = "wikimedia"

    endpoints = (
        "https://de.wikipedia.org/w/api.php",
        "https://en.wikipedia.org/w/api.php",
    )

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        headers = {
            "Accept": "application/json",
            "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)

    def research(self, company: str) -> list[CompanyResearchHit]:
        for endpoint in self.endpoints:
            hit = self._search(endpoint, company)
            if hit is not None:
                return [hit]
        return []

    def _search(self, endpoint: str, company: str) -> CompanyResearchHit | None:
        try:
            response = self.client.get(
                endpoint,
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": f'intitle:"{company}"',
                    "gsrnamespace": 0,
                    "gsrlimit": 5,
                    "prop": "extracts|info",
                    "exintro": 1,
                    "explaintext": 1,
                    "exchars": 1_500,
                    "inprop": "url",
                    "redirects": 1,
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
        except (httpx.HTTPError, AttributeError, TypeError, ValueError):
            return None
        candidates = (
            [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []
        )
        for page in sorted(
            candidates,
            key=lambda candidate: _company_title_score(company, str(candidate.get("title") or "")),
            reverse=True,
        ):
            title = " ".join(str(page.get("title") or "").split())
            extract = " ".join(str(page.get("extract") or "").split())
            url = str(page.get("fullurl") or "")
            if (
                _company_title_score(company, title) < 0.6
                or len(extract) < 80
                or not url.startswith("https://")
                or _looks_like_disambiguation(extract)
            ):
                continue
            return CompanyResearchHit(
                title=f"Wikimedia company profile: {title}",
                description=extract[:1_500],
                url=url,
                purpose=ResearchPurpose.BUSINESS,
            )
        return None


class CompositeCompanyResearchProvider:
    """Merge bounded company research sources without making one mandatory."""

    def __init__(self, providers: list[CompanyResearchProvider]) -> None:
        self.providers = providers

    def research(self, company: str) -> list[CompanyResearchHit]:
        hits: list[CompanyResearchHit] = []
        for provider in self.providers:
            try:
                hits.extend(provider.research(company))
            except (RuntimeError, TypeError, ValueError):
                continue
        unique: dict[str, CompanyResearchHit] = {}
        for hit in hits:
            unique.setdefault(hit.url, hit)
        return list(unique.values())[:10]


class BraveCompanyResearchProvider:
    """Find company context and employer certifications through Brave's API."""

    name = "brave-search"

    endpoint = BRAVE_WEB_SEARCH_ENDPOINT
    allowed_hosts = (
        "greatplacetowork.de",
        "greatplacetowork.com",
        "top-employers.com",
        "top100.de",
    )

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Brave company research requires a non-empty API key")
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key.strip(),
            "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)

    def research(self, company: str) -> list[CompanyResearchHit]:
        return [*self._business_context(company), *self._employer_signals(company)]

    def _business_context(self, company: str) -> list[CompanyResearchHit]:
        rows = self._search(f'"{company}" company products business official')
        hits: list[CompanyResearchHit] = []
        for row in rows:
            url = str(row.get("url") or "")
            title = " ".join(str(row.get("title") or "").split())
            description = " ".join(str(row.get("description") or "").split())
            if (
                not url.startswith("https://")
                or _company_title_score(company, f"{title} {description}") < 0.35
                or not description
            ):
                continue
            hits.append(
                CompanyResearchHit(
                    title=title[:500] or "Company context",
                    description=description[:1_500],
                    url=url,
                    purpose=ResearchPurpose.BUSINESS,
                )
            )
        return hits[:4]

    def _employer_signals(self, company: str) -> list[CompanyResearchHit]:
        rows = self._search(
            f'"{company}" employer certification "Great Place to Work" OR "Top Employer"'
        )
        hits: list[CompanyResearchHit] = []
        for row in rows:
            url = str(row.get("url") or "")
            host = (urlsplit(url).hostname or "").casefold()
            if not any(
                host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts
            ):
                continue
            hits.append(
                CompanyResearchHit(
                    title=" ".join(str(row.get("title") or "Employer signal").split())[:500],
                    description=" ".join(str(row.get("description") or "").split())[:1_000],
                    url=url,
                    purpose=ResearchPurpose.REPUTATION,
                )
            )
        return hits[:5]

    def _search(self, query: str) -> list[dict[str, object]]:
        return request_brave_web_results(
            self.client,
            params={
                "q": query,
                "country": "DE",
                "search_lang": "en",
                "count": 10,
                "safesearch": "strict",
                "text_decorations": False,
                "result_filter": "web",
            },
        )


BUSINESS_RULES: tuple[
    tuple[str, str, str, tuple[str, ...], bool],
    ...,
] = (
    (
        "staffing",
        "staffing and recruiting services",
        "The company appears to earn revenue by placing, recruiting, or supplying workers to clients.",
        (
            "arbeitnehmerüberlassung",
            "arbeitnehmerueberlassung",
            "zeitarbeit",
            "personaldienstleister",
            "temporary staffing",
            "staffing company",
        ),
        True,
    ),
    (
        "recruitment",
        "recruitment and placement services",
        "The company appears to earn revenue by recruiting or placing candidates for clients.",
        ("personalvermittlung", "recruitment agency", "recruiting agency"),
        True,
    ),
    (
        "defence",
        "defence products, systems, or services",
        "The available text connects the company to defence or military customers, products, or services.",
        (
            "defence",
            "defense",
            "military",
            "armed forces",
            "bundeswehr",
            "wehrtechnik",
            "rüstung",
            "ruestung",
        ),
        True,
    ),
    (
        "surveillance",
        "human-surveillance or biometric-analysis products and services",
        "The available text connects the company to surveillance of people, facial recognition, or biometric products.",
        (
            "video surveillance",
            "facial recognition",
            "biometric monitoring",
            "cctv",
            "surveillance camera",
            "surveillance cameras",
            "person surveillance",
            "people surveillance",
            "employee surveillance",
            "workplace surveillance",
            "police surveillance",
            "intelligence surveillance",
            "videoüberwachung",
            "videoueberwachung",
            "gesichtserkennung",
            "biometrische überwachung",
            "biometrische ueberwachung",
            "überwachungskamera",
            "ueberwachungskamera",
            "personenüberwachung",
            "personenueberwachung",
            "mitarbeiterüberwachung",
            "mitarbeiterueberwachung",
        ),
        True,
    ),
    (
        "consulting",
        "consulting and project-delivery services",
        "The company appears to earn revenue through consulting or project delivery for clients.",
        ("consulting", "consultancy", "unternehmensberatung", "kundenprojekte"),
        True,
    ),
    (
        "software",
        "software products, licences, subscriptions, or related services",
        "The available text points to software products or software-enabled services as part of the business.",
        ("software platform", "saas", "software product", "softwarelösungen", "software solutions"),
        False,
    ),
    (
        "manufacturing",
        "engineered products, equipment, systems, and related services",
        "The available text points to revenue from designed or manufactured physical products and systems.",
        (
            "manufacturer",
            "manufacture",
            "manufacturing",
            "produces",
            "production",
            "industrialize",
            "anlagenbau",
            "maschinenbau",
        ),
        False,
    ),
    (
        "energy",
        "energy technology, equipment, projects, or services",
        "The available text connects the company to energy technology, equipment, projects, or services.",
        ("energy", "battery systems", "renewable", "solar", "wind power", "energietechnik"),
        False,
    ),
)


class CompanyIntelligenceService:
    """Build cautious company context from employer-controlled and licensed sources."""

    def __init__(self, research_provider: CompanyResearchProvider | None = None) -> None:
        self.research_provider = research_provider
        self._research_cache: dict[str, list[CompanyResearchHit]] = {}

    def analyze(
        self,
        job: JobPosting,
        *,
        homepage_text: str | None = None,
        homepage_url: str | None = None,
    ) -> CompanyIntelligence:
        source_url = str(job.source_url or job.requested_url or "")
        parts = [(job.source_text, source_url)]
        if homepage_text and homepage_url:
            parts.insert(0, (homepage_text, homepage_url))
        research = self._research(job.company)
        business_parts = [
            (hit.description, hit.url)
            for hit in research
            if hit.purpose == ResearchPurpose.BUSINESS and hit.description
        ]
        product = _product_profile(job.company, [*parts, *business_parts])
        reputation = _reputation(
            job.company,
            parts,
            [hit for hit in research if hit.purpose == ResearchPurpose.REPUTATION],
        )
        return CompanyIntelligence(company=job.company, product=product, reputation=reputation)

    def _research(self, company: str) -> list[CompanyResearchHit]:
        key = " ".join(company.casefold().split())
        if key not in self._research_cache:
            if self.research_provider is None:
                hits: list[CompanyResearchHit] = []
            elif hasattr(self.research_provider, "research"):
                hits = self.research_provider.research(company)
            else:
                # Temporary compatibility for local v0.6.7d test adapters.
                hits = self.research_provider.employer_signals(company)  # type: ignore[attr-defined]
            self._research_cache[key] = hits
        return self._research_cache[key]


def _product_profile(
    company: str,
    parts: list[tuple[str, str]],
) -> CompanyProductProfile:
    matches: list[tuple[str, str, str, str, str, bool]] = []
    for text, url in parts:
        normalized = " ".join(text.casefold().split())
        for category, revenue_model, explanation, markers, sensitive in BUSINESS_RULES:
            marker = _affirmative_category_marker(normalized, category, markers)
            if marker:
                matches.append(
                    (
                        category,
                        revenue_model,
                        explanation,
                        _excerpt(text, marker),
                        url,
                        sensitive,
                    )
                )
    unique: dict[str, tuple[str, str, str, str, str, bool]] = {}
    for match in matches:
        unique.setdefault(match[0], match)
    if not unique:
        return CompanyProductProfile(
            summary=(
                f"The available job and employer text does not yet establish how {company} "
                "makes money. Treat the company category as unknown until an official source is available."
            ),
            revenue_model="Not established from available public evidence",
            confidence=IntelligenceConfidence.LOW,
        )
    primary = next(iter(unique.values()))
    categories = list(unique)
    return CompanyProductProfile(
        summary=" ".join(item[2] for item in unique.values()),
        revenue_model=primary[1],
        categories=categories,
        sensitive_categories=[item[0] for item in unique.values() if item[5]],
        confidence=(
            IntelligenceConfidence.HIGH
            if any(item[4] and item[4] != str(parts[-1][1]) for item in unique.values())
            else IntelligenceConfidence.MEDIUM
        ),
        evidence_quotes=list(dict.fromkeys(item[3] for item in matches if item[3]))[:8],
        evidence_urls=list(dict.fromkeys(item[4] for item in matches if item[4]))[:8],
    )


_NEGATION_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht|ohne|no|not|never|without)\b",
    re.IGNORECASE,
)

_SURVEILLANCE_PATTERNS = (
    r"\bvideo[- ]?surveillance\w*\b",
    r"\bhuman surveillance\w*\b",
    r"\bcctv\b",
    r"\bfacial recognition\b",
    r"\bbiometric (?:monitoring|identification|recognition)\b",
    r"\bsurveillance cameras?\b",
    r"\b(?:person|people|employee|workplace|police|intelligence) surveillance\w*\b",
    r"\bvideo(?:über|ueber)wach\w*\b",
    r"\b(?:über|ueber)wachungskamera\w*\b",
    r"\bpersonen(?:über|ueber)wach\w*\b",
    r"\bmitarbeiter(?:über|ueber)wach\w*\b",
    r"\bgesichtserkenn\w*\b",
    r"\bbiometrisch\w*\s+(?:über|ueber)wach\w*\b",
)

_UNAMBIGUOUS_DEFENCE_PATTERNS = (
    r"\bmilitary\b",
    r"\barmed forces\b",
    r"\bbundeswehr\b",
    r"\bwehrtechnik\w*\b",
    r"\brüstung\w*\b",
    r"\bruestung\w*\b",
    r"\bmilitär\w*\b",
    r"\bmilitaer\w*\b",
)

_DEFENCE_CONTEXT_PATTERN = re.compile(
    r"\b(?:weapons?|missiles?|armed forces|army|naval|air force|soldiers?|radar|combat|"
    r"defen[cs]e (?:industry|sector|products?|systems?|customers?|contractors?|technology|services?))\b",
    re.IGNORECASE,
)

_CYBER_DEFENCE_PATTERN = re.compile(
    r"\b(?:cyber|network|malware|information|cloud)\s+(?:security|defen[cs]e)\b|"
    r"\b(?:cybersecurity|network security|cloud security)\b",
    re.IGNORECASE,
)


def _affirmative_category_marker(
    normalized_text: str,
    category: str,
    markers: tuple[str, ...],
) -> str | None:
    if category == "surveillance":
        return _first_affirmative_pattern(normalized_text, _SURVEILLANCE_PATTERNS)
    if category == "defence":
        return _affirmative_defence_marker(normalized_text)
    return next(
        (candidate for candidate in markers if _affirmative_marker(normalized_text, candidate)),
        None,
    )


def _affirmative_defence_marker(normalized_text: str) -> str | None:
    marker = _first_affirmative_pattern(normalized_text, _UNAMBIGUOUS_DEFENCE_PATTERNS)
    if marker is not None:
        return marker
    for match in re.finditer(r"\bdefen[cs]e\b", normalized_text, re.IGNORECASE):
        if _match_is_negated(normalized_text, match.start()):
            continue
        context = normalized_text[max(0, match.start() - 80) : match.end() + 100]
        if _CYBER_DEFENCE_PATTERN.search(context):
            continue
        if _DEFENCE_CONTEXT_PATTERN.search(context):
            return match.group(0)
    return None


def _first_affirmative_pattern(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not _match_is_negated(text, match.start()):
                return match.group(0)
    return None


def _match_is_negated(text: str, marker_start: int) -> bool:
    """Use a short, clause-local window instead of negating an entire sentence."""

    prefix = text[:marker_start]
    clause_start = max(prefix.rfind(separator) for separator in (".", "!", "?", ";", ":", ","))
    contrast_matches = list(re.finditer(r"\b(?:but|however|aber|sondern|doch)\b", prefix))
    if contrast_matches:
        clause_start = max(clause_start, contrast_matches[-1].end() - 1)
    tokens = re.findall(r"[a-zäöüß0-9]+", prefix[clause_start + 1 :], re.IGNORECASE)[-5:]
    for index, token in enumerate(tokens):
        if not _NEGATION_PATTERN.fullmatch(token):
            continue
        if token.casefold() == "not" and index + 1 < len(tokens) and tokens[index + 1] == "only":
            continue
        return True
    return False


def _affirmative_marker(normalized_text: str, marker: str) -> bool:
    """Reject negated category mentions and require a complete marker boundary.

    Sensitive product categories are launch-impacting evidence. A statement such
    as ``keine Personenüberwachung`` therefore cannot be treated like an
    affirmative product claim. Boundaries also keep short category markers from
    matching unrelated longer words.
    """

    pattern = re.compile(
        rf"(?<![a-z0-9]){re.escape(marker.casefold())}(?![a-z0-9])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(normalized_text):
        if _match_is_negated(normalized_text, match.start()):
            continue
        return True
    return False


def _reputation(
    company: str,
    parts: list[tuple[str, str]],
    research_hits: list[CompanyResearchHit],
) -> EmployerReputationSummary:
    signals: list[CompanyEvidence] = []
    award_markers = (
        "great place to work",
        "top employer",
        "top company",
        "bester arbeitgeber",
    )
    for text, url in parts:
        normalized = text.casefold()
        marker = next((candidate for candidate in award_markers if candidate in normalized), None)
        if marker and url:
            signals.append(
                CompanyEvidence(
                    label="Employer-published award claim",
                    summary=_excerpt(text, marker),
                    source_url=url,
                )
            )
    signals.extend(
        [
            CompanyEvidence(
                label=hit.title,
                summary=hit.description or "Independent employer certification result.",
                source_url=hit.url,
            )
            for hit in research_hits
        ]
    )
    if signals:
        summary = (
            "Attributed employer-award signals are linked below. They can add context, but they are "
            "not a substitute for reading employee reviews and checking the review count and date."
        )
    else:
        summary = (
            "No attributed employer certification was available from the configured sources. Use the "
            "review-profile links below for a manual, current check."
        )
    return EmployerReputationSummary(
        kununu_score=None,
        kununu_review_count=None,
        kununu_source_url=None,
        kununu_manual_url=kununu_manual_search_url(company),
        summary=summary,
        signals=signals,
        review_links=employer_review_links(company),
        caveat=(
            "WorkLifeBalance does not collect employee-review platforms or present a stale score as live. "
            "Open the linked profile and verify its score, review count, recency, and role mix yourself."
        ),
    )


def kununu_manual_search_url(company: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(f'site:kununu.com {company}')}"


def employer_review_links(company: str) -> list[ReviewProfileLink]:
    return [
        ReviewProfileLink(
            label="Find this employer on Kununu", url=kununu_manual_search_url(company)
        ),
        ReviewProfileLink(
            label="Find this employer on Glassdoor",
            url=f"https://www.google.com/search?q={quote_plus(f'site:glassdoor.de {company} reviews')}",
        ),
    ]


def _company_title_score(company: str, material: str) -> float:
    company_tokens = _company_tokens(company)
    if not company_tokens:
        return 0.0
    material_tokens = set(re.findall(r"[a-z0-9]+", material.casefold()))
    return len(company_tokens.intersection(material_tokens)) / len(company_tokens)


def _company_tokens(company: str) -> set[str]:
    ignored = {"ag", "gmbh", "kg", "se", "inc", "ltd", "group", "gruppe", "holding"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", company.casefold())
        if len(token) >= 2 and token not in ignored
    }


def _looks_like_disambiguation(extract: str) -> bool:
    normalized = extract.casefold()
    return any(
        marker in normalized
        for marker in (
            "begriffsklärung",
            "may refer to:",
            "can refer to:",
            "steht für:",
        )
    )


def _excerpt(text: str, marker: str) -> str:
    index = text.casefold().find(marker.casefold())
    start = max(0, index - 80)
    end = min(len(text), index + len(marker) + 160)
    return " ".join(text[start:end].split())[:500]
