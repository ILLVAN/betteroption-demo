"""Conservative, reproducible job-posting date evidence.

Dates are accepted only when the advertisement labels them as a publication
date (or an extractor supplied an equivalently labelled fact).  This avoids
mistaking application deadlines, event dates, or arbitrary years for the
publication date.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable

from pydantic import Field

from .profile import StrictModel


class PostingDateSource(StrEnum):
    STRUCTURED = "structured"
    EXTRACTED_FACT = "extracted_fact"
    LABELED_TEXT = "labeled_text"
    RELATIVE_TEXT = "relative_text"


class PostingDateConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PostingFreshness(StrEnum):
    FRESH = "fresh"
    MEDIUM = "medium"
    OLD = "old"
    UNKNOWN = "unknown"


class PostingDateExtraction(StrictModel):
    value: date
    source: PostingDateSource
    confidence: PostingDateConfidence
    evidence_quote: str = Field(min_length=1, max_length=500)


class PostingDateAssessment(StrictModel):
    """The immutable date context stored with one match result."""

    automatic_date: date | None = None
    effective_date: date | None = None
    automatic_freshness: PostingFreshness = PostingFreshness.UNKNOWN
    freshness: PostingFreshness = PostingFreshness.UNKNOWN
    evaluated_on: date
    source: PostingDateSource | None = None
    confidence: PostingDateConfidence | None = None
    evidence_quote: str | None = Field(default=None, max_length=500)
    user_overridden: bool = False
    score_adjustment: int = Field(ge=-4, le=2)


POSTING_DATE_FACT_KEYS = {
    "date.posted",
    "job.date_posted",
    "job.posted_at",
    "posting.date",
    "posting_date",
    "publication.date",
    "published_at",
}

_LABEL = (
    r"date\s+posted|posted(?:\s+on)?|publication\s+date|published(?:\s+on)?|"
    r"ver(?:ö|oe)ffentlich(?:t|ung)(?:sdatum|\s+am)?|eingestellt(?:\s+am)?|"
    r"inseriert(?:\s+am)?|publiziert(?:\s+am)?|datum\s+der\s+ver(?:ö|oe)ffentlichung|"
    r"date\s+de\s+publication|publié(?:e)?(?:\s+le)?|mise\s+en\s+ligne(?:\s+le)?|"
    r"publicatiedatum|geplaatst(?:\s+op)?|gepubliceerd(?:\s+op)?|"
    r"fecha\s+de\s+publicaci[oó]n|publicad[oa](?:\s+el)?|"
    r"data\s+di\s+pubblicazione|pubblicat[oa](?:\s+il)?"
)
_MONTH_WORD = r"[^\W\d_]+\.?"
_DATE_TOKEN = (
    r"\d{4}-\d{1,2}-\d{1,2}(?:[T ][0-9:.+\-Zz]+)?|"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    rf"\d{{1,2}}\s+{_MONTH_WORD}\s+\d{{4}}|"
    rf"{_MONTH_WORD}\s+\d{{1,2}},?\s+\d{{4}}"
)
_LABELED_DATE = re.compile(
    rf"(?P<quote>\b(?P<label>{_LABEL})\s*(?:[:|]\s*|[-–—]\s+)?(?P<date>{_DATE_TOKEN}))",
    flags=re.IGNORECASE,
)
_JSON_DATE_POSTED = re.compile(
    rf"(?P<quote>[\"']datePosted[\"']\s*:\s*[\"'](?P<date>{_DATE_TOKEN})[\"'])",
    flags=re.IGNORECASE,
)
_RELATIVE_TOKEN = (
    r"today|yesterday|heute|gestern|"
    r"aujourd['’]hui|hier|vandaag|gisteren|hoy|ayer|oggi|ieri|"
    r"\d{1,3}\s+(?:days?|weeks?)\s+ago|"
    r"vor\s+\d{1,3}\s+(?:tage?n?|wochen?)|"
    r"il\s+y\s+a\s+(?:\d{1,3}|un|une)\s+(?:jours?|semaines?)|"
    r"(?:\d{1,3}|een)\s+(?:dag(?:en)?|we(?:e)?k(?:en)?)\s+geleden|"
    r"hace\s+(?:\d{1,3}|un|una)\s+(?:d[ií]as?|semanas?)|"
    r"(?:\d{1,3}|un|una)\s+(?:giorn[oi]|settiman[ae])\s+fa"
)
_RELATIVE_DATE = re.compile(
    rf"(?P<quote>\b(?P<label>{_LABEL})\s*(?:[:|]\s*|[-–—]\s+)?"
    rf"(?P<relative>{_RELATIVE_TOKEN}))",
    flags=re.IGNORECASE,
)
_RELATIVE_BADGE = re.compile(
    rf"(?P<quote>^[ \t]*(?P<relative>{_RELATIVE_TOKEN})[ \t]*$)",
    flags=re.IGNORECASE | re.MULTILINE,
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "januar": 1,
    "janvier": 1,
    "janv": 1,
    "januari": 1,
    "enero": 1,
    "gennaio": 1,
    "ene": 1,
    "gen": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "fevrier": 2,
    "fevr": 2,
    "februari": 2,
    "febbraio": 2,
    "mar": 3,
    "march": 3,
    "maerz": 3,
    "marz": 3,
    "mars": 3,
    "maart": 3,
    "marzo": 3,
    "mrt": 3,
    "apr": 4,
    "april": 4,
    "avril": 4,
    "abril": 4,
    "aprile": 4,
    "avr": 4,
    "abr": 4,
    "may": 5,
    "mai": 5,
    "mei": 5,
    "mayo": 5,
    "maggio": 5,
    "mag": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "juin": 6,
    "junio": 6,
    "giugno": 6,
    "giu": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "juillet": 7,
    "julio": 7,
    "luglio": 7,
    "juil": 7,
    "lug": 7,
    "aug": 8,
    "august": 8,
    "aout": 8,
    "augustus": 8,
    "agosto": 8,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "septembre": 9,
    "septiembre": 9,
    "setiembre": 9,
    "settembre": 9,
    "set": 9,
    "oct": 10,
    "october": 10,
    "okt": 10,
    "oktober": 10,
    "octobre": 10,
    "octubre": 10,
    "ottobre": 10,
    "ott": 10,
    "nov": 11,
    "november": 11,
    "novembre": 11,
    "noviembre": 11,
    "dec": 12,
    "december": 12,
    "dez": 12,
    "dezember": 12,
    "decembre": 12,
    "diciembre": 12,
    "dicembre": 12,
    "dic": 12,
}


def _month_number(value: str) -> int | None:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold().strip(". "))
        if not unicodedata.combining(character)
    )
    return _MONTHS.get(normalized)


def parse_explicit_posting_date(value: str) -> date | None:
    """Parse one full, explicit European/ISO date without guessing locale."""

    candidate = " ".join(value.strip().split())
    iso_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ][0-9:.+-Zz]+)?", candidate)
    if iso_match:
        parts = [int(part) for part in iso_match.groups()]
        try:
            return date(parts[0], parts[1], parts[2])
        except ValueError:
            return None

    numeric_match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", candidate)
    if numeric_match:
        day, month, year = (int(part) for part in numeric_match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    day_first = re.fullmatch(rf"(\d{{1,2}})\s+({_MONTH_WORD})\s+(\d{{4}})", candidate)
    if day_first and (month := _month_number(day_first.group(2))) is not None:
        try:
            return date(int(day_first.group(3)), month, int(day_first.group(1)))
        except ValueError:
            return None

    month_first = re.fullmatch(rf"({_MONTH_WORD})\s+(\d{{1,2}}),?\s+(\d{{4}})", candidate)
    if month_first and (month := _month_number(month_first.group(1))) is not None:
        try:
            return date(int(month_first.group(3)), month, int(month_first.group(2)))
        except ValueError:
            return None
    return None


def _fact_extraction(
    facts: Iterable[tuple[str, str, str]],
) -> PostingDateExtraction | None:
    for key, value, evidence_quote in facts:
        if key.casefold() not in POSTING_DATE_FACT_KEYS:
            continue
        parsed_value = parse_explicit_posting_date(value)
        evidence_match = _LABELED_DATE.search(evidence_quote)
        parsed_evidence = (
            parse_explicit_posting_date(evidence_match.group("date"))
            if evidence_match
            else parse_explicit_posting_date(evidence_quote)
        )
        # A typed fact remains attributable only when its verbatim quotation
        # supports the same date.  Do not let an extractor's free-form value
        # silently override contradictory source evidence.
        if parsed_value is not None and parsed_value == parsed_evidence:
            return PostingDateExtraction(
                value=parsed_value,
                source=PostingDateSource.EXTRACTED_FACT,
                confidence=PostingDateConfidence.HIGH,
                evidence_quote=evidence_quote[:500],
            )
    return None


def _relative_posting_date(value: str, observed_at: datetime) -> date | None:
    normalized = "".join(
        character
        for character in unicodedata.normalize(
            "NFKD",
            " ".join(value.casefold().replace("’", "'").split()),
        )
        if not unicodedata.combining(character)
    )
    observed_date = observed_at.astimezone(timezone.utc).date()
    if normalized in {"today", "heute", "aujourd'hui", "vandaag", "hoy", "oggi"}:
        return observed_date
    if normalized in {"yesterday", "gestern", "hier", "gisteren", "ayer", "ieri"}:
        return observed_date - timedelta(days=1)
    count_match = re.search(r"\d{1,3}", normalized)
    count = int(count_match.group()) if count_match is not None else 1
    if count_match is None and not re.search(r"\b(?:un|une|una|een)\b", normalized):
        return None
    if any(
        marker in normalized for marker in ("week", "wek", "woche", "semaine", "semana", "settiman")
    ):
        return observed_date - timedelta(weeks=count)
    if any(marker in normalized for marker in ("day", "tag", "jour", "dag", "dia", "giorn")):
        return observed_date - timedelta(days=count)
    return None


def extract_posting_date(
    source_text: str,
    *,
    observed_at: datetime,
    facts: Iterable[tuple[str, str, str]] = (),
) -> PostingDateExtraction | None:
    """Extract attributable posting-date evidence from one advertisement."""

    explicit_matches = list(_LABELED_DATE.finditer(source_text))
    structured_matches = [
        match
        for match in explicit_matches
        if match.group("label").casefold().strip() == "date posted"
    ]
    for match in [*_JSON_DATE_POSTED.finditer(source_text), *structured_matches]:
        parsed = parse_explicit_posting_date(match.group("date"))
        if parsed is None:
            continue
        return PostingDateExtraction(
            value=parsed,
            source=PostingDateSource.STRUCTURED,
            confidence=PostingDateConfidence.HIGH,
            evidence_quote=match.group("quote")[:500],
        )

    fact_result = _fact_extraction(facts)
    if fact_result is not None:
        return fact_result

    for match in explicit_matches:
        if match in structured_matches:
            continue
        parsed = parse_explicit_posting_date(match.group("date"))
        if parsed is None:
            continue
        return PostingDateExtraction(
            value=parsed,
            source=PostingDateSource.LABELED_TEXT,
            confidence=PostingDateConfidence.MEDIUM,
            evidence_quote=match.group("quote")[:500],
        )

    for relative_match in filter(
        None,
        (_RELATIVE_DATE.search(source_text), _RELATIVE_BADGE.search(source_text)),
    ):
        parsed = _relative_posting_date(relative_match.group("relative"), observed_at)
        if parsed is not None:
            return PostingDateExtraction(
                value=parsed,
                source=PostingDateSource.RELATIVE_TEXT,
                confidence=PostingDateConfidence.LOW,
                evidence_quote=relative_match.group("quote").strip()[:500],
            )
    return None


def subtract_calendar_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def classify_posting_date(posted_on: date | None, *, evaluated_on: date) -> PostingFreshness:
    """Classify using calendar-month boundaries, not arbitrary day counts."""

    if posted_on is None or posted_on > evaluated_on:
        return PostingFreshness.UNKNOWN
    one_month_ago = subtract_calendar_months(evaluated_on, 1)
    four_months_ago = subtract_calendar_months(evaluated_on, 4)
    if posted_on > one_month_ago:
        return PostingFreshness.FRESH
    if posted_on >= four_months_ago:
        return PostingFreshness.MEDIUM
    return PostingFreshness.OLD


def posting_date_score_adjustment(freshness: PostingFreshness) -> int:
    """Keep age a small context signal; it can never block a job."""

    return {
        PostingFreshness.FRESH: 2,
        PostingFreshness.MEDIUM: 0,
        PostingFreshness.OLD: -4,
        PostingFreshness.UNKNOWN: 0,
    }[freshness]
