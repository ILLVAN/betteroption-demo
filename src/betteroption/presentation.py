"""Small deterministic formatting helpers for delivery adapters."""

from __future__ import annotations

import re

from .jobs import JobPosting
from .mobility import CommuteAssessment, CommuteStatus


_REMOTE_ONLY_RE = re.compile(
    r"\b(?:fully\s+remote|remote[\s-]+only|100\s*%\s*remote|"
    r"work\s+from\s+anywhere|location\s*[:\-]\s*remote)\b",
    re.IGNORECASE,
)
_REMOTE_GENERIC_RE = re.compile(r"^\s*(?:remote|home\s*office|homeoffice)\s*$", re.I)
_POSTAL_ADDRESS_RE = re.compile(
    r"PostalAddress\s+(?:Deutschland|Germany|DE)\s+(.+?)\s+(\d{5})\s+"
    r"(?:Nicht\s+vorhanden|Not\s+available)",
    re.IGNORECASE,
)
_COMPANY_SEAT_KEYS = {
    "company.headquarters",
    "company.location",
    "employer.address",
    "employer.headquarters",
    "employer.location",
}
_GERMAN_REGIONS = {
    "baden-württemberg",
    "bayern",
    "berlin",
    "brandenburg",
    "bremen",
    "hamburg",
    "hessen",
    "mecklenburg-vorpommern",
    "niedersachsen",
    "nordrhein-westfalen",
    "rheinland-pfalz",
    "saarland",
    "sachsen",
    "sachsen-anhalt",
    "schleswig-holstein",
    "thüringen",
}


def job_is_remote_only(job: JobPosting) -> bool:
    """Return true only for explicit remote-only evidence, not ordinary hybrid work."""

    material = " ".join(
        [job.location, job.title]
        + [f"{fact.key} {fact.value} {fact.evidence_quote}" for fact in job.facts]
    )
    if _REMOTE_ONLY_RE.search(material):
        return True
    remote_facts = [
        fact.value.casefold()
        for fact in job.facts
        if fact.key
        in {
            "job.work_model.remote",
            "location.remote",
            "work_model.remote",
            "workplace.remote",
        }
    ]
    if not remote_facts:
        return _REMOTE_GENERIC_RE.fullmatch(job.location) is not None
    combined = " ".join(remote_facts)
    return "remote" in combined and not any(
        marker in combined for marker in ("hybrid", "optional", "possible", "days")
    )


def format_location_text(location: object, *, remote_only: bool = False) -> str:
    """Turn common schema/ATS location leaks into a compact user-facing label."""

    raw = " ".join(str(location or "").split())
    if not raw:
        return "Remote" if remote_only else "Location unknown"

    postal_matches = _POSTAL_ADDRESS_RE.findall(raw)
    if postal_matches:
        labels: list[str] = []
        for place, postal_code in postal_matches:
            clean_place = " ".join(place.split()).strip(" ,;·-")
            parts = clean_place.rsplit(" ", 1)
            if len(parts) == 2 and parts[-1].casefold() in _GERMAN_REGIONS:
                clean_place = f"{parts[0]}, {parts[1]}"
            label = f"{postal_code} {clean_place}".strip()
            if label.casefold() not in {item.casefold() for item in labels}:
                labels.append(label)
        clean = " / ".join(labels)
    else:
        clean = re.sub(r"\bPostalAddress\b", "", raw, flags=re.IGNORECASE)
        clean = re.sub(
            r"\b(?:Nicht\s+vorhanden|Not\s+available|Location\s+to\s+verify)\b",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"\s*[,;·|/]\s*[,;·|/]+\s*", " · ", clean)
        clean = " ".join(clean.split()).strip(" ,;·-/")

    if remote_only:
        if not clean or _REMOTE_GENERIC_RE.fullmatch(clean):
            return "Remote"
        if "remote" not in clean.casefold():
            return f"{clean} · Remote"
    return clean or ("Remote" if remote_only else "Location unknown")


def format_job_location(job: JobPosting) -> str:
    """Render one job location with explicit remote-only context."""

    remote_only = job_is_remote_only(job)
    location = job.location
    if remote_only and (_REMOTE_ONLY_RE.search(location) or _REMOTE_GENERIC_RE.fullmatch(location)):
        company_seats = [
            fact.value
            for fact in job.facts
            if fact.key in _COMPANY_SEAT_KEYS and not _REMOTE_ONLY_RE.search(fact.value)
        ]
        if company_seats:
            location = company_seats[0]
    return format_location_text(location, remote_only=remote_only)


def format_duration_minutes(value: object) -> str:
    """Render minutes compactly while keeping long journeys easy to scan."""

    try:
        minutes = max(0, int(value))
    except (TypeError, ValueError):
        return "Unknown"
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h" if remainder == 0 else f"{hours}h {remainder:02d}m"


def commute_visual_state(assessment: CommuteAssessment) -> str:
    """Classify route evidence for the four accessible UI states."""

    estimate = assessment.estimate
    duration = estimate.duration_minutes
    within_limit = assessment.within_limit
    if estimate.status != CommuteStatus.AVAILABLE or duration is None or within_limit is None:
        return "unavailable"
    if within_limit:
        return "within"
    if duration <= assessment.maximum_minutes * 1.15:
        return "stretch"
    return "conflict"
