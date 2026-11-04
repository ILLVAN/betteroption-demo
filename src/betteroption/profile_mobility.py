"""Canonical mobility facts derived from user-authored Compass answers."""

from __future__ import annotations

import re

from pydantic import Field

from .profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    StrictModel,
    TravelConstraint,
    TravelMode,
)


_MODE_KEY_PARTS = {
    "transit": TravelMode.TRANSIT,
    "train": TravelMode.TRANSIT,
    "rail": TravelMode.TRANSIT,
    "car": TravelMode.CAR,
    "drive": TravelMode.CAR,
    "bicycle": TravelMode.BICYCLE,
    "bike": TravelMode.BICYCLE,
    "cycling": TravelMode.BICYCLE,
    "walk": TravelMode.WALK,
    "walking": TravelMode.WALK,
    "foot": TravelMode.WALK,
}

_MODE_TEXT_PATTERNS = {
    TravelMode.TRANSIT: (
        r"\btransit\b",
        r"\btrain\b",
        r"\brail\b",
        r"\bpublic transport\b",
        r"\bpublic transportation\b",
        r"\bbahn\b",
        r"\bzug\b",
        r"\böffentliche[nrsm]* verkehr(?:smittel)?\b",
    ),
    TravelMode.CAR: (
        r"\bcar\b",
        r"\bdriv(?:e|ing)\b",
        r"\bauto\b",
        r"\bpkw\b",
    ),
    TravelMode.BICYCLE: (
        r"\bbicycle\b",
        r"\bbike\b",
        r"\bcycling\b",
        r"\be[- ]?bike\b",
        r"\bfahrrad\b",
        r"\brad\b",
    ),
    TravelMode.WALK: (
        r"\bwalk(?:ing)?\b",
        r"\bon foot\b",
        r"\bzu fuß\b",
        r"\bzu fuss\b",
    ),
}

_MODE_VALUE_LABELS = {
    TravelMode.TRANSIT: "train",
    TravelMode.CAR: "car",
    TravelMode.BICYCLE: "bicycle",
    TravelMode.WALK: "walking",
}

_ORIGIN_FACT_KEYS = {"location.origin", "commute.origin", "mobility.origin"}


class MobilityWidgetPreferences(StrictModel):
    """Compact, editable projection of the active Compass mobility facts."""

    origin_label: str = Field(default="", max_length=200)
    car_minutes: int = Field(default=0, ge=0, le=360)
    transit_minutes: int = Field(default=0, ge=0, le=360)
    bicycle_minutes: int = Field(default=0, ge=0, le=360)

    @property
    def is_active(self) -> bool:
        return bool(
            self.origin_label or self.car_minutes or self.transit_minutes or self.bicycle_minutes
        )


def mobility_widget_preferences(profile: CandidateProfile) -> MobilityWidgetPreferences:
    """Project guided answers and typed legacy values into one neutral editor.

    Confirmed facts take precedence because they are the user's newest visible
    Compass decisions. The typed ``LocationPreference`` remains a compatibility
    fallback for profiles saved before the guided workflow emitted atomic facts.
    """

    origin = profile.location.origin_label if profile.location is not None else ""
    limits = {
        TravelMode.CAR: 0,
        TravelMode.TRANSIT: 0,
        TravelMode.BICYCLE: 0,
    }
    if profile.location is not None:
        for constraint in profile.location.travel_constraints:
            if constraint.mode in limits:
                limits[constraint.mode] = constraint.maximum_minutes_one_way

    for fact in sorted(profile.confirmed_facts, key=lambda item: item.created_at):
        if fact.key in _ORIGIN_FACT_KEYS:
            candidate = " ".join(str(fact.value).split())
            if candidate:
                origin = candidate[:200]
            continue
        limit = mobility_limit_from_fact(fact)
        if limit is not None and limit[0] in limits:
            limits[limit[0]] = limit[1]

    return MobilityWidgetPreferences(
        origin_label=origin,
        car_minutes=limits[TravelMode.CAR],
        transit_minutes=limits[TravelMode.TRANSIT],
        bicycle_minutes=limits[TravelMode.BICYCLE],
    )


def sync_location_projection_from_facts(profile: CandidateProfile) -> None:
    """Rebuild the typed mobility cache from current confirmed facts.

    Atomic facts are the editable source of truth.  ``profile.location`` is kept
    for legacy checkpoints and exports, but must never retain an origin or limit
    a user has replaced in guided setup or the Compass widgets.
    """

    origin = ""
    limits: dict[TravelMode, tuple[int, RequirementLevel]] = {}
    for fact in sorted(profile.confirmed_facts, key=lambda item: item.created_at):
        if fact.key in _ORIGIN_FACT_KEYS:
            candidate = " ".join(str(fact.value).split())
            if candidate:
                origin = candidate[:200]
            continue
        parsed = mobility_limit_from_fact(fact)
        if parsed is not None:
            mode, minutes = parsed
            limits[mode] = (minutes, fact.level)

    previous = profile.location
    if not origin:
        profile.location = None
        return

    profile.location = LocationPreference(
        origin_label=origin,
        origin_precision=origin_precision_from_label(origin),
        acceptable_destinations=(
            list(previous.acceptable_destinations) if previous is not None else []
        ),
        travel_constraints=[
            TravelConstraint(
                mode=mode,
                maximum_minutes_one_way=minutes,
                level=level,
            )
            for mode, (minutes, level) in limits.items()
        ],
        relocation=(previous.relocation if previous is not None else RequirementLevel.OPEN),
        second_residence_allowed=(
            previous.second_residence_allowed if previous is not None else None
        ),
    )


def mobility_mode_label(mode: TravelMode) -> str:
    """Return the candidate-facing name while preserving stable internal enums."""

    return _MODE_VALUE_LABELS[mode]


def origin_precision_from_label(label: str) -> str:
    """Classify only the precision of a user-chosen, non-home starting point."""

    clean = " ".join(label.split())
    if re.search(r"(?<!\d)\d{5}(?!\d)", clean):
        return "postal_code"
    if re.search(
        r"\b(?:bahnhof|hauptbahnhof|hbf|station|parking|parkplatz|garage|straße|strasse|street)\b",
        clean,
        flags=re.IGNORECASE,
    ) or re.search(r"\b\d{1,5}[a-z]?\b", clean, flags=re.IGNORECASE):
        return "address"
    return "city"


_DURATION_EXPRESSION = re.compile(
    r"\b(?:"
    r"\d{1,2}:\d{2}"
    r"|\d+(?:[.,]\d+)?\s*(?:hours?|hrs?|h|stunden?|std\.?)"
    r"(?:\s*(?:and\s+)?\d{1,2}\s*(?:minutes?|mins?|min\.?|m))?"
    r"|\d+(?:[.,]\d+)?\s*(?:minutes?|mins?|min\.?|m)"
    r")\b",
    flags=re.IGNORECASE,
)


def duration_minutes_from_text(value: object) -> int | None:
    """Parse a user-facing duration while preserving its unit."""

    text = " ".join(str(value).casefold().split())
    if not text:
        return None

    clock = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if clock:
        return _bounded_minutes(int(clock.group(1)) * 60 + int(clock.group(2)))

    hours = re.search(
        r"(?P<value>\d+(?:[.,]\d+)?)\s*(?:hours?|hrs?|h|stunden?|std\.?)",
        text,
    )
    if hours:
        hour_value = float(hours.group("value").replace(",", "."))
        trailing = text[hours.end() :]
        extra_minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|min\.?|m)\b", trailing)
        if extra_minutes is None:
            extra_minutes = re.match(r"\s*(\d{1,2})\b", trailing)
        total = round(hour_value * 60)
        if extra_minutes and hour_value.is_integer():
            total += int(extra_minutes.group(1))
        return _bounded_minutes(total)

    minutes = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:minutes?|mins?|min\.?|m)\b", text)
    if minutes:
        return _bounded_minutes(round(float(minutes.group(1).replace(",", "."))))

    bare_number = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", text)
    if bare_number:
        return _bounded_minutes(round(float(bare_number.group(1).replace(",", "."))))
    return None


def mobility_mode_from_fact(fact: ProfileFact) -> TravelMode | None:
    """Resolve the stated mode, preferring quoted user language over a model key."""

    quoted_modes = _modes_in_text(f"{fact.source.text} {fact.value}")
    key_mode = _mode_from_key(fact.key)
    if len(quoted_modes) == 1:
        return next(iter(quoted_modes))
    if key_mode in quoted_modes:
        return key_mode
    return key_mode


def mobility_limit_from_fact(fact: ProfileFact) -> tuple[TravelMode, int] | None:
    """Return one safe modal limit or leave an ambiguous fact out of routing."""

    if not _is_mobility_limit_key(fact.key):
        return None
    mode = mobility_mode_from_fact(fact)
    minutes = duration_minutes_from_text(fact.value)
    if minutes is None:
        minutes = duration_minutes_from_text(fact.source.text)
    if mode is None or minutes is None:
        return None
    return mode, minutes


def canonicalize_mobility_fact(fact: ProfileFact) -> bool:
    """Keep the mode and the minute limit visible together in a stored fact."""

    if not _is_mobility_limit_key(fact.key):
        return False
    previous = (fact.key, fact.value, fact.level)
    mode = mobility_mode_from_fact(fact)
    minutes = duration_minutes_from_text(fact.value)
    if minutes is None:
        minutes = duration_minutes_from_text(fact.source.text)

    if mode is None:
        fact.key = "commute.unresolved.max_minutes"
        if minutes is not None:
            fact.value = f"{minutes} minutes one way (travel mode not specified)"
        fact.level = RequirementLevel.OPEN
    elif minutes is not None:
        fact.key = f"commute.{mode.value}.max_minutes"
        fact.value = f"{minutes} minutes by {_MODE_VALUE_LABELS[mode]} one way"
    return previous != (fact.key, fact.value, fact.level)


def canonicalize_profile_mobility_facts(profile: CandidateProfile) -> bool:
    """Repair legacy and new modal limits without touching unrelated facts."""

    changed = False
    for fact in profile.facts:
        changed = canonicalize_mobility_fact(fact) or changed
    return changed


def explicit_mobility_facts_from_text(text: str) -> list[ProfileFact]:
    """Recover only explicit mode-plus-duration limits from the user's own text.

    This is a narrow deterministic guardrail for cases where an LLM omits one
    atomic proposal. It does not infer locations, requirement strength, or a
    mode that the user did not write.
    """

    clean = " ".join(text.split())
    if not clean:
        return []
    durations = [
        (match.start(), match.end(), duration_minutes_from_text(match.group(0)))
        for match in _DURATION_EXPRESSION.finditer(clean)
    ]
    valid_durations = [item for item in durations if item[2] is not None]
    if not valid_durations:
        return []

    facts: list[ProfileFact] = []
    for mode, patterns in _MODE_TEXT_PATTERNS.items():
        mode_matches = [
            match
            for pattern in patterns
            for match in re.finditer(pattern, clean, flags=re.IGNORECASE)
        ]
        if not mode_matches:
            continue
        mode_match = min(mode_matches, key=lambda item: item.start())
        duration = min(
            valid_durations,
            key=lambda item: _span_distance(
                (mode_match.start(), mode_match.end()),
                (item[0], item[1]),
            ),
        )
        minutes = duration[2]
        if minutes is None:  # pragma: no cover - filtered above
            continue
        excerpt_start = min(mode_match.start(), duration[0])
        excerpt_end = max(mode_match.end(), duration[1])
        facts.append(
            ProfileFact(
                key=f"commute.{mode.value}.max_minutes",
                value=f"{minutes} minutes by {_MODE_VALUE_LABELS[mode]} one way",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.EXPLICIT,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.LOCATION_MOBILITY,
                    text=clean[excerpt_start:excerpt_end],
                    start_offset=excerpt_start,
                    end_offset=excerpt_end,
                ),
            )
        )
    return facts


def _is_mobility_limit_key(key: str) -> bool:
    parts = set(key.casefold().replace("-", "_").split("."))
    return bool(parts.intersection({"commute", "mobility"})) and bool(
        parts.intersection({"max", "maximum", "limit", "max_minutes"})
        or "max_minutes" in key.casefold()
    )


def _mode_from_key(key: str) -> TravelMode | None:
    for part in key.casefold().replace("-", "_").split("."):
        if part in _MODE_KEY_PARTS:
            return _MODE_KEY_PARTS[part]
    return None


def _modes_in_text(value: object) -> set[TravelMode]:
    text = " ".join(str(value).casefold().split())
    return {
        mode
        for mode, patterns in _MODE_TEXT_PATTERNS.items()
        if any(re.search(pattern, text) for pattern in patterns)
    }


def _bounded_minutes(value: int) -> int | None:
    return value if 1 <= value <= 1_440 else None


def _span_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    if left[1] < right[0]:
        return right[0] - left[1]
    if right[1] < left[0]:
        return left[0] - right[1]
    return 0
