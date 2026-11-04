"""Evidence-first salary orientation for advertisements without stated pay.

The matching core deliberately contains no occupation catalogue or salary table.
An optional research adapter may supply attributable benchmark evidence for any
occupation.  Without that evidence BetterOption abstains instead of guessing.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import geonamescache
from pydantic import Field, model_validator

from .geography import OfflineGermanPostalCodeIndex, OfflinePlaceIndex
from .jobs import JobPosting
from .profile import CandidateProfile, StrictModel


class SalaryConfidence(StrEnum):
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"


class SalaryEstimateKind(StrEnum):
    EVIDENCE = "evidence_backed"
    AI_ORIENTATION = "ai_orientation"
    USER_CORRECTION = "user_correction"


class SalaryPeriod(StrEnum):
    HOURLY = "hourly"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ANNUAL = "annual"


class SalarySourceAuthority(StrEnum):
    OFFICIAL = "official"
    SECONDARY = "secondary"


class SalaryEvidence(StrictModel):
    """One attributable, occupation-specific public benchmark observation."""

    occupation_family: str = Field(min_length=1, max_length=300)
    annual_min_eur: int = Field(ge=1, le=1_000_000)
    annual_max_eur: int = Field(ge=1, le=1_000_000)
    confidence: SalaryConfidence = SalaryConfidence.LOW
    source_label: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=2_000)
    source_quote: str = Field(min_length=1, max_length=2_000)
    mapping_explanation: str = Field(min_length=1, max_length=2_000)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    region: str = Field(min_length=1, max_length=300)
    hours_basis: str = Field(default="full-time", min_length=1, max_length=300)
    seniority_basis: str | None = Field(default=None, max_length=300)
    source_authority: SalarySourceAuthority = SalarySourceAuthority.OFFICIAL
    source_min_amount: float = Field(gt=0, le=10_000_000)
    source_max_amount: float = Field(gt=0, le=10_000_000)
    source_currency: str = Field(pattern=r"^[A-Z]{3}$")
    source_period: SalaryPeriod
    periods_per_year: float = Field(gt=0, le=366)
    annualization_basis: str = Field(min_length=1, max_length=500)
    weekly_hours_basis: float | None = Field(default=None, gt=0, le=80)
    exchange_rate_units_per_eur: float | None = Field(default=None, gt=0)
    exchange_rate_date: date | None = None
    exchange_source_url: str | None = Field(default=None, max_length=2_000)
    exchange_source_quote: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def range_is_ordered(self) -> SalaryEvidence:
        if self.annual_min_eur > self.annual_max_eur:
            raise ValueError("salary evidence minimum cannot exceed its maximum")
        if self.source_min_amount > self.source_max_amount:
            raise ValueError("source salary minimum cannot exceed its maximum")
        if self.source_period == SalaryPeriod.HOURLY and self.weekly_hours_basis is None:
            raise ValueError("hourly salary evidence requires a weekly-hours basis")
        if self.source_currency != "EUR" and not all(
            (
                self.exchange_rate_units_per_eur,
                self.exchange_rate_date,
                self.exchange_source_url,
                self.exchange_source_quote,
            )
        ):
            raise ValueError(
                "non-EUR salary evidence requires an attributable exchange rate and date"
            )
        if self.source_period == SalaryPeriod.ANNUAL and self.periods_per_year != 1:
            raise ValueError("annual salary evidence requires one period per year")
        period_multiplier = self.periods_per_year
        if self.source_period == SalaryPeriod.HOURLY:
            period_multiplier *= self.weekly_hours_basis or 0.0
        exchange_rate = self.exchange_rate_units_per_eur or 1.0
        expected_min = round(self.source_min_amount * period_multiplier / exchange_rate)
        expected_max = round(self.source_max_amount * period_multiplier / exchange_rate)
        tolerance_min = max(2, round(expected_min * 0.01))
        tolerance_max = max(2, round(expected_max * 0.01))
        if (
            abs(self.annual_min_eur - expected_min) > tolerance_min
            or abs(self.annual_max_eur - expected_max) > tolerance_max
        ):
            raise ValueError(
                "annual EUR range does not match the attributable source values, period, "
                "and exchange rate"
            )
        return self


class SalaryEstimate(StrictModel):
    # These original fields remain stable for stored match results and templates.
    occupation_family: str
    annual_min_eur: int = Field(ge=1)
    annual_max_eur: int = Field(ge=1)
    confidence: SalaryConfidence
    source_label: str
    source_url: str | None = None
    assumption: str
    estimate_kind: SalaryEstimateKind = SalaryEstimateKind.EVIDENCE
    # New results retain every benchmark item used for the displayed range.
    # The default keeps previously stored v0.7.1 results readable.
    evidence: tuple[SalaryEvidence, ...] = ()
    region: str | None = None
    hours_basis: str | None = None
    seniority_basis: str | None = None


class SalaryGuess(StrictModel):
    """A deliberately broad, unsourced AI orientation—not matching evidence."""

    occupation_family: str = Field(min_length=1, max_length=300)
    annual_min_eur: int = Field(ge=5_000, le=1_000_000)
    annual_max_eur: int = Field(ge=5_000, le=1_000_000)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    region: str = Field(min_length=1, max_length=300)
    assumption: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def broad_ordered_range(self) -> SalaryGuess:
        if self.annual_min_eur >= self.annual_max_eur:
            raise ValueError("salary orientation minimum must be below its maximum")
        if self.annual_max_eur < round(self.annual_min_eur * 1.15):
            raise ValueError("salary orientation must stay broad")
        return self


class SalaryResearchResult(StrictModel):
    evidence: dict[UUID, list[SalaryEvidence]] = Field(default_factory=dict)
    guesses: dict[UUID, SalaryGuess] = Field(default_factory=dict)

    # Keep injected and pre-v0.7.1g evidence-only callers source-compatible
    # while the richer result carries the explicitly separate guess channel.
    def __getitem__(self, job_id: UUID) -> list[SalaryEvidence]:
        return self.evidence[job_id]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return not self.guesses and self.evidence == other
        return super().__eq__(other)


class SalaryBenchmarkProvider(Protocol):
    """Research a bounded job batch without receiving any candidate profile."""

    name: str

    def research(self, jobs: list[JobPosting]) -> SalaryResearchResult: ...


OFFICIAL_WAGE_SOURCE_HOSTS = frozenset(
    {
        # Cross-European primary sources.
        "eures.europa.eu",
        "ec.europa.eu",
        # National labour-market/statistical sources. This is a source policy,
        # not an occupation or salary catalogue.
        "web.arbeitsagentur.de",
        "statistik.arbeitsagentur.de",
        "www.arbeitsagentur.de",
        "www.ams.at",
        "www.statistik.at",
        "www.bfs.admin.ch",
        "www.ons.gov.uk",
        "nationalcareers.service.gov.uk",
        "www.insee.fr",
        "www.francetravail.fr",
        "www.cbs.nl",
        "www.uwv.nl",
        "www.ssb.no",
        "www.dst.dk",
        "www.scb.se",
        "stat.fi",
        "www.ine.es",
        "www.istat.it",
        "statbel.fgov.be",
        "stat.gov.pl",
        "www.cso.ie",
    }
)

EXCHANGE_RATE_SOURCE_HOSTS = frozenset({"www.ecb.europa.eu", "ecb.europa.eu"})

# Secondary sources can be enabled deliberately after methodological review.
# An empty initial allowlist is safer than calling a popular salary site
# "reputable" without such a review. The aggregation policy below already
# requires two independent secondary domains when entries are added later.
VETTED_SECONDARY_SALARY_SOURCE_HOSTS: frozenset[str] = frozenset()

SALARY_WEB_SEARCH_HOSTS = tuple(sorted(OFFICIAL_WAGE_SOURCE_HOSTS | EXCHANGE_RATE_SOURCE_HOSTS))


def salary_source_authority(url: str) -> SalarySourceAuthority | None:
    """Classify a wage source using the explicit, reviewable host policy."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    host = (parsed.hostname or "").casefold()
    if host in OFFICIAL_WAGE_SOURCE_HOSTS:
        return SalarySourceAuthority.OFFICIAL
    if host in VETTED_SECONDARY_SALARY_SOURCE_HOSTS:
        return SalarySourceAuthority.SECONDARY
    return None


def official_exchange_rate_source(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and (parsed.hostname or "").casefold() in EXCHANGE_RATE_SOURCE_HOSTS
    )


_EUROPEAN_CURRENCY = (
    r"(?:€|eur|£|gbp|chf|nok|sek|dkk|pln|zł|czk|kč|huf|ron|lei|bgn|лв|isk|"
    r"all|bam|mkd|mdl|rsd|uah|kr)"
)
_MONEY_NUMBER = r"(?:\d{1,3}(?:[.,\s]\d{3})+|\d{4,6}|\d{1,3})(?:[.,]\d{1,2})?\s*[kK]?"
_CURRENCY_AMOUNT = re.compile(
    rf"(?:{_EUROPEAN_CURRENCY}\s*{_MONEY_NUMBER}|{_MONEY_NUMBER}\s*{_EUROPEAN_CURRENCY})"
    rf"(?:\s*(?:p\.?\s*a\.?|per\s+(?:year|month|hour)|jährlich|monatlich|stündlich|/\s*(?:y|m|h)))?",
    flags=re.IGNORECASE,
)
_SALARY_CONTEXT = re.compile(
    r"\b(?:salary|salaris|salaire|salario|gehalt|vergütung|verguetung|lohn|wage|pay|"
    r"compensation|brutto|gross|annual|yearly|monthly|hourly|jährlich|jaehrlich|monatlich|"
    r"stündlich|stuendlich|p\.?\s*a\.?)\b",
    flags=re.IGNORECASE,
)
_NON_SALARY_MONEY_CONTEXT = re.compile(
    r"\b(?:revenue|turnover|umsatz|budget|learning budget|training budget|weiterbildungsbudget|"
    r"company value|funding|investment)\b",
    flags=re.IGNORECASE,
)


def advertised_salary_present(job: JobPosting) -> bool:
    """Return true whenever the advertisement itself contains compensation."""

    if any(
        fact.key.startswith(("salary.", "pay.", "wage."))
        or fact.key
        in {
            "compensation.annual_gross",
            "compensation.salary",
            "compensation.base_salary",
            "compensation.hourly_rate",
            "compensation.wage",
            "compensation.pay",
        }
        for fact in job.facts
    ):
        return True
    for match in _CURRENCY_AMOUNT.finditer(job.source_text):
        nearby = job.source_text[max(0, match.start() - 90) : match.end() + 90]
        immediate = job.source_text[max(0, match.start() - 35) : match.end() + 35]
        if _SALARY_CONTEXT.search(nearby) and not _NON_SALARY_MONEY_CONTEXT.search(immediate):
            return True
    return False


def profile_requests_salary_research(profile: CandidateProfile) -> bool:
    """Research pay only when the candidate has an active compensation criterion."""

    return any(
        fact.key.startswith(("compensation.", "salary.", "pay."))
        for fact in profile.confirmed_search_facts
    )


def jobs_missing_advertised_salary(
    profile: CandidateProfile,
    jobs: Sequence[JobPosting],
    *,
    limit: int = 25,
    require_profile_criterion: bool = True,
) -> list[JobPosting]:
    """Return the bounded research batch, or nothing when salary is irrelevant."""

    if require_profile_criterion and not profile_requests_salary_research(profile):
        return []
    return [
        job
        for job in jobs
        if european_job_country(job) is not None and not advertised_salary_present(job)
    ][:limit]


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


_PLACE_INDEX = OfflinePlaceIndex()
_GERMAN_POSTAL_INDEX = OfflineGermanPostalCodeIndex()


def _place_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text))


_EXPLICIT_COUNTRY_ALIASES = {
    "deutschland": "DE",
    "germany": "DE",
    "austria": "AT",
    "osterreich": "AT",
    "schweiz": "CH",
    "switzerland": "CH",
    "france": "FR",
    "united kingdom": "GB",
    "great britain": "GB",
}
_COUNTRY_CODES = frozenset(geonamescache.GeonamesCache().get_countries())
EUROPEAN_COUNTRY_CODES = frozenset(
    {
        code
        for code, country in geonamescache.GeonamesCache().get_countries().items()
        if str(country.get("continentcode") or "").upper() == "EU"
    }
    | {"CY"}
)
for _country_code, _country in geonamescache.GeonamesCache().get_countries().items():
    for _country_marker in (
        str(_country.get("name") or ""),
        str(_country.get("iso3") or ""),
    ):
        _normalized_country_marker = _place_text(_country_marker)
        if len(_normalized_country_marker) >= 3:
            _EXPLICIT_COUNTRY_ALIASES.setdefault(
                _normalized_country_marker,
                _country_code,
            )


def _explicit_country_codes(label: str) -> set[str]:
    normalized = _place_text(label)
    if not normalized:
        return set()
    codes: set[str] = set()
    codes.update(
        candidate
        for candidate in re.findall(
            r"(?:^|[,;(]\s*)([A-Z]{2})(?=$|[\s,;)])",
            label,
        )
        if candidate in _COUNTRY_CODES
    )
    if re.search(r"(?<![A-Z])UK(?![A-Z])", label):
        codes.add("GB")
    for marker, code in _EXPLICIT_COUNTRY_ALIASES.items():
        if re.search(rf"(?:^|\s){re.escape(marker)}(?:$|\s)", normalized):
            codes.add(code)
    return codes


def job_country_code(job: JobPosting) -> str | None:
    """Resolve one unambiguous workplace country from public job evidence."""

    labels = [
        job.location,
        *[
            fact.value
            for fact in job.facts
            if fact.key.startswith(("location.", "workplace.location"))
        ],
    ]
    countries: set[str] = set()
    for label in labels:
        for segment in re.split(r"(?:\s*[/|;\n]\s*|\s+or\s+|\s+oder\s+)", label, flags=re.I):
            clean_segment = segment.strip()
            if not clean_segment:
                continue
            countries.update(_explicit_country_codes(clean_segment))
            if _GERMAN_POSTAL_INDEX.resolve(clean_segment) is not None:
                countries.add("DE")
            place = _PLACE_INDEX.resolve(clean_segment)
            if place is not None:
                countries.add(place.country_code)
    return next(iter(countries)) if len(countries) == 1 else None


def european_job_country(job: JobPosting) -> str | None:
    """Return a country only for an unambiguous European workplace."""

    country_code = job_country_code(job)
    if country_code is None or country_code not in EUROPEAN_COUNTRY_CODES:
        return None
    return country_code


def _region_relevance(job: JobPosting, evidence: SalaryEvidence) -> int:
    region = _normalized(evidence.region)
    location = _normalized(job.location)
    if region and region in location:
        return 2
    if region == "national":
        return 1
    return 0


def _select_consistent_evidence(
    job: JobPosting,
    evidence: Sequence[SalaryEvidence],
) -> list[SalaryEvidence]:
    country_code = european_job_country(job)
    if country_code is None:
        return []
    trustworthy = [
        item
        for item in evidence
        if item.country_code == country_code
        and salary_source_authority(item.source_url) == item.source_authority
        and (
            item.source_currency == "EUR"
            or (
                item.exchange_source_url is not None
                and official_exchange_rate_source(item.exchange_source_url)
            )
        )
    ]
    if not trustworthy:
        return []

    official = [
        item for item in trustworthy if item.source_authority == SalarySourceAuthority.OFFICIAL
    ]
    if official:
        trustworthy = official
    else:
        secondary_domains = {
            (urlsplit(item.source_url).hostname or "").casefold() for item in trustworthy
        }
        if len(secondary_domains) < 2:
            return []

    # A research provider may return alternative occupation mappings.  Never
    # blend them into a synthetic band: keep only the best-supported family.
    family_counts = Counter(_normalized(item.occupation_family) for item in trustworthy)
    family = max(
        family_counts,
        key=lambda key: (
            family_counts[key],
            max(
                _region_relevance(job, item)
                for item in trustworthy
                if _normalized(item.occupation_family) == key
            ),
        ),
    )
    same_family = [item for item in trustworthy if _normalized(item.occupation_family) == family]
    best_region_score = max(_region_relevance(job, item) for item in same_family)
    if best_region_score:
        same_family = [
            item for item in same_family if _region_relevance(job, item) == best_region_score
        ]

    unique: dict[str, SalaryEvidence] = {}
    for item in same_family:
        unique.setdefault(item.source_url, item)
    return list(unique.values())


def estimate_salary(
    job: JobPosting,
    evidence: Sequence[SalaryEvidence] | None = None,
    guess: SalaryGuess | None = None,
) -> SalaryEstimate | None:
    """Build a cautious orientation from supplied evidence or explicitly abstain.

    The function does not perform network or model calls.  This keeps deterministic
    matching cheap and makes the provenance boundary testable.  The application
    service decides whether to run the optional, budgeted research adapter.
    """

    if advertised_salary_present(job):
        return None
    if european_job_country(job) is None:
        return None
    selected = _select_consistent_evidence(job, evidence or ())
    if not selected:
        country_code = european_job_country(job)
        if guess is None or country_code is None or guess.country_code != country_code:
            return None
        return SalaryEstimate(
            occupation_family=guess.occupation_family,
            annual_min_eur=guess.annual_min_eur,
            annual_max_eur=guess.annual_max_eur,
            confidence=SalaryConfidence.VERY_LOW,
            source_label="AI market orientation (unsourced)",
            source_url=None,
            estimate_kind=SalaryEstimateKind.AI_ORIENTATION,
            assumption=(
                f"{guess.assumption} Broad orientation for {guess.region}; no attributable "
                "benchmark was available. This is not advertised compensation, verified "
                "salary evidence, or a fact used by Matching. Check current local sources "
                "before relying on it."
            ),
            region=guess.region,
        )

    annual_min = min(item.annual_min_eur for item in selected)
    annual_max = max(item.annual_max_eur for item in selected)
    primary = selected[0]
    unique_source_domains = {
        (urlsplit(item.source_url).hostname or "").casefold() for item in selected
    }
    confidence = (
        SalaryConfidence.MEDIUM
        if len(unique_source_domains) >= 2
        and all(item.confidence == SalaryConfidence.MEDIUM for item in selected)
        else SalaryConfidence.LOW
    )
    regions = list(dict.fromkeys(item.region for item in selected))
    hours_bases = list(dict.fromkeys(item.hours_basis for item in selected))
    seniority_bases = list(
        dict.fromkeys(item.seniority_basis for item in selected if item.seniority_basis)
    )
    mapping = " ".join(dict.fromkeys(item.mapping_explanation for item in selected))
    annualization = "; ".join(dict.fromkeys(item.annualization_basis for item in selected))
    basis = f"Region: {', '.join(regions)}; hours basis: {', '.join(hours_bases)}"
    if seniority_bases:
        basis += f"; requirement/seniority basis: {', '.join(seniority_bases)}"
    return SalaryEstimate(
        occupation_family=primary.occupation_family,
        annual_min_eur=annual_min,
        annual_max_eur=annual_max,
        confidence=confidence,
        source_label=primary.source_label,
        source_url=primary.source_url,
        assumption=(
            f"{mapping} {basis}. Annualisation: {annualization}. This is an attributable "
            "market orientation, "
            "not compensation advertised by this employer. Do not scale it mechanically for "
            "part-time hours; region, experience, collective agreements, bonuses, and the "
            "actual contract can materially change pay."
        ),
        evidence=tuple(selected),
        region=", ".join(regions),
        hours_basis=", ".join(hours_bases),
        seniority_basis=", ".join(seniority_bases) or None,
    )
