"""Conservative consistency checks for the active Compass projection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from .geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    ResolvedPlace,
    straight_line_distance_km,
)
from .profile import CandidateProfile, ProfileFact, RequirementLevel
from .profile_mobility import mobility_limit_from_fact


@dataclass(frozen=True, slots=True)
class ProfileConsistencyIssue:
    """One high-signal tension that a user should acknowledge before matching."""

    code: str
    title: str
    explanation: str
    statements: tuple[str, ...]
    fact_ids: tuple[UUID, ...] = ()


_JUNIOR_MARKERS = {
    "entry level",
    "graduate",
    "intern",
    "internship",
    "junior",
    "trainee",
    "working student",
}
_SENIOR_MARKERS = {
    "head",
    "lead",
    "principal",
    "senior",
}
_REMOTE_ONLY_MARKERS = {
    "fully remote",
    "remote only",
    "remote-only",
    "100 remote",
    "vollstandig remote",
    "nur remote",
}
_ONSITE_ONLY_MARKERS = {
    "fully onsite",
    "fully on site",
    "on site only",
    "onsite only",
    "office only",
    "nur vor ort",
    "vollstandig vor ort",
    "nur im buro",
}
_ORIGIN_KEYS = {"location.origin", "commute.origin", "mobility.origin"}
_NEGATION_MARKERS = {
    "avoid",
    "exclude",
    "kein",
    "keine",
    "keinen",
    "nicht",
    "no",
    "not",
    "never",
    "without",
}
_UPPER_BOUND_PATTERNS = (
    re.compile(
        r"\b(?:at most|no more than|up to|maximum(?: of)?|maximal|"
        r"hochstens|hoechstens|nicht mehr als|bis zu)\s+(\d+(?:[.,]\d+)?)\b"
    ),
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s+(?:or fewer|max(?:imum)?|hochstens|hoechstens)\b"),
)
_LOWER_BOUND_PATTERNS = (
    re.compile(
        r"\b(?:at least|no fewer than|no less than|minimum(?: of)?|mindestens|"
        r"wenigstens|nicht weniger als)\s+(\d+(?:[.,]\d+)?)\b"
    ),
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s+(?:or more|min(?:imum)?|mindestens)\b"),
)


def _plain(value: object) -> str:
    material = unicodedata.normalize("NFKD", str(value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", material))


def _fact_text(fact: ProfileFact) -> str:
    # Source excerpts can contain several clauses (including negations). The
    # reviewed atomic value is the authoritative target for this check.
    return _plain(f"{fact.key} {fact.value}")


def _label(fact: ProfileFact) -> str:
    level = fact.level.value.replace("_", " ").title()
    return f"{level}: {fact.value}"


def _contains_any(text: str, markers: set[str]) -> bool:
    padded = f" {text} "
    return any(f" {marker.replace('-', ' ')} " in padded for marker in markers)


def _fact_contains_affirmative_marker(fact: ProfileFact, markers: set[str]) -> bool:
    """Ignore an explicitly negated value before consulting a canonical key."""

    value = _plain(fact.value)
    saw_marker = False
    for marker in markers:
        clean_marker = marker.replace("-", " ")
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(clean_marker)}(?![a-z0-9])", value):
            saw_marker = True
            prefix = value[: match.start()].split()[-4:]
            if _NEGATION_MARKERS.intersection(prefix):
                continue
            return True
    if saw_marker or value in {"false", "no", "not wanted", "excluded"}:
        return False
    return _contains_any(_plain(fact.key), markers)


def _bound_axis(key: str) -> str:
    parts = [
        part
        for part in re.split(r"[._-]+", key.casefold())
        if part not in {"max", "maximum", "min", "minimum", "lower", "upper"}
    ]
    return ".".join(parts)


def _numeric_bounds(fact: ProfileFact) -> tuple[float | None, float | None]:
    material = unicodedata.normalize("NFKD", str(fact.value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    material = " ".join(material.split())

    def numeric_value(token: str) -> float:
        if re.fullmatch(r"\d{1,3}[.,]\d{3}", token):
            return float(token.replace(",", "").replace(".", ""))
        return float(token.replace(",", "."))

    def values(patterns: tuple[re.Pattern[str], ...]) -> list[float]:
        return [
            numeric_value(match.group(1))
            for pattern in patterns
            for match in pattern.finditer(material)
        ]

    lower_values = values(_LOWER_BOUND_PATTERNS)
    upper_values = values(_UPPER_BOUND_PATTERNS)
    key = fact.key.casefold()
    unlabelled = [numeric_value(token) for token in re.findall(r"\d+(?:[.,]\d+)?", material)]
    if not upper_values and re.search(r"(?:^|[._-])(?:max|maximum|upper)$", key):
        upper_values = unlabelled[:1]
    if not lower_values and re.search(r"(?:^|[._-])(?:min|minimum|lower)$", key):
        lower_values = unlabelled[:1]
    return (
        max(lower_values) if lower_values else None,
        min(upper_values) if upper_values else None,
    )


def _important(facts: list[ProfileFact]) -> bool:
    return any(
        fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION} for fact in facts
    )


def inspect_profile_consistency(profile: CandidateProfile) -> list[ProfileConsistencyIssue]:
    """Return only material contradictions, not healthy breadth across roles.

    The checker intentionally avoids comparing ordinary role families or skills. A
    user may reasonably explore several adjacent directions. It only raises
    tensions where two statements cannot normally be true in the same job search.
    """

    facts = [fact for fact in profile.confirmed_search_facts if fact.level != RequirementLevel.OPEN]
    issues: list[ProfileConsistencyIssue] = []

    # Exclusions describe what the user does not want. They must not be treated
    # as positive seniority targets when checking whether the Compass conflicts
    # with itself (for example, "junior" plus "no internship" is coherent).
    positive_targets = [fact for fact in facts if fact.level != RequirementLevel.EXCLUSION]
    junior = [
        fact
        for fact in positive_targets
        if _fact_contains_affirmative_marker(fact, _JUNIOR_MARKERS)
    ]
    senior = [
        fact
        for fact in positive_targets
        if _fact_contains_affirmative_marker(fact, _SENIOR_MARKERS)
    ]
    if junior and senior and _important([*junior, *senior]):
        statements = tuple(dict.fromkeys([*map(_label, junior), *map(_label, senior)]))
        issues.append(
            ProfileConsistencyIssue(
                code="seniority-extremes",
                title="Junior and senior targets are both active",
                explanation=(
                    "These targets can produce opposite rankings. Keep both only if you "
                    "genuinely want Matching to compare both career levels."
                ),
                statements=statements,
                fact_ids=tuple(dict.fromkeys(fact.id for fact in [*junior, *senior])),
            )
        )

    remote_only = [
        fact
        for fact in positive_targets
        if _fact_contains_affirmative_marker(fact, _REMOTE_ONLY_MARKERS)
    ]
    onsite_only = [
        fact
        for fact in positive_targets
        if _fact_contains_affirmative_marker(fact, _ONSITE_ONLY_MARKERS)
    ]
    if remote_only and onsite_only and _important([*remote_only, *onsite_only]):
        statements = tuple(dict.fromkeys([*map(_label, remote_only), *map(_label, onsite_only)]))
        issues.append(
            ProfileConsistencyIssue(
                code="workplace-extremes",
                title="Remote-only and on-site-only targets are both active",
                explanation=(
                    "A single role cannot satisfy both boundaries. Edit one statement, "
                    "or explicitly continue if you want two separate search directions."
                ),
                statements=statements,
                fact_ids=tuple(dict.fromkeys(fact.id for fact in [*remote_only, *onsite_only])),
            )
        )

    bounded_by_axis: dict[str, list[tuple[ProfileFact, float | None, float | None]]] = {}
    for fact in positive_targets:
        if fact.level != RequirementLevel.MUST_HAVE:
            continue
        lower, upper = _numeric_bounds(fact)
        if lower is None and upper is None:
            continue
        bounded_by_axis.setdefault(_bound_axis(fact.key), []).append((fact, lower, upper))
    for axis, bounded in bounded_by_axis.items():
        active_lowers = [(fact, lower) for fact, lower, _upper in bounded if lower is not None]
        active_uppers = [(fact, upper) for fact, _lower, upper in bounded if upper is not None]
        if not active_lowers or not active_uppers:
            continue
        strongest_lower = max(value for _fact, value in active_lowers)
        strongest_upper = min(value for _fact, value in active_uppers)
        if strongest_lower <= strongest_upper:
            continue
        conflicting = [fact for fact, value in active_lowers if value == strongest_lower] + [
            fact for fact, value in active_uppers if value == strongest_upper
        ]
        issues.append(
            ProfileConsistencyIssue(
                code=f"incompatible-bounds:{axis}",
                title="Two numeric boundaries cannot both be satisfied",
                explanation=(
                    "The active minimum is higher than the active maximum. Choose the "
                    "boundary that should guide this persona."
                ),
                statements=tuple(dict.fromkeys(map(_label, conflicting))),
                fact_ids=tuple(dict.fromkeys(fact.id for fact in conflicting)),
            )
        )

    by_identity: dict[tuple[str, str], list[ProfileFact]] = {}
    for fact in facts:
        by_identity.setdefault((fact.key, _plain(fact.value)), []).append(fact)
    for (key, _), matching in by_identity.items():
        levels = {fact.level for fact in matching}
        if RequirementLevel.EXCLUSION not in levels or not levels.intersection(
            {RequirementLevel.MUST_HAVE, RequirementLevel.PREFERENCE}
        ):
            continue
        issues.append(
            ProfileConsistencyIssue(
                code=f"opposite-level:{key}",
                title="The same condition is both wanted and excluded",
                explanation=(
                    "Matching cannot apply this condition consistently until you edit it, "
                    "or explicitly acknowledge the tension for this run."
                ),
                statements=tuple(dict.fromkeys(map(_label, matching))),
                fact_ids=tuple(dict.fromkeys(fact.id for fact in matching)),
            )
        )

    issues.extend(_mobility_origin_issues(profile))

    return issues


def _mobility_origin_issues(profile: CandidateProfile) -> list[ProfileConsistencyIssue]:
    """Check only origins that materially affect an active commute constraint.

    A city, postcode, district, station, or street can all be legitimate routing
    benchmarks. We therefore do not demand a street address. We only pause when
    no origin exists, an active origin cannot be resolved locally, or two
    resolved origins are clearly far apart. The logic is generic and uses the
    bundled place/postcode indexes rather than a city-specific exception.
    """

    mobility_facts = [
        fact
        for fact in profile.confirmed_facts
        if fact.level != RequirementLevel.EXCLUSION and mobility_limit_from_fact(fact) is not None
    ]
    if not mobility_facts:
        return []

    origin_facts = [
        fact
        for fact in profile.confirmed_facts
        if fact.key in _ORIGIN_KEYS and str(fact.value).strip()
    ]
    if not origin_facts and profile.location is not None:
        return []
    if not origin_facts:
        return [
            ProfileConsistencyIssue(
                code="missing-mobility-origin",
                title="Commute limits need a starting point",
                explanation=(
                    "Add a city, district, postcode, station, or street address before exact "
                    "commute evidence can be calculated. A precise address is optional."
                ),
                statements=tuple(dict.fromkeys(map(_label, mobility_facts))),
                fact_ids=tuple(dict.fromkeys(fact.id for fact in mobility_facts)),
            )
        ]

    postcode_index = OfflineGermanPostalCodeIndex()
    place_index = OfflinePlaceIndex()
    resolved: list[tuple[ProfileFact, ResolvedPlace]] = []
    unresolved: list[ProfileFact] = []
    for fact in origin_facts:
        label = str(fact.value).strip()
        place = postcode_index.resolve(label) or place_index.resolve(label)
        # The bundled place index cannot validate every European street. Accept
        # address-like labels for the configured route provider, but catch a
        # bare, unresolved postcode because it is commonly a typo and can send
        # routing to the wrong region.
        if place is None and re.fullmatch(r"\s*\d{4,6}\s*", label):
            unresolved.append(fact)
        elif place is not None:
            resolved.append((fact, place))

    if unresolved:
        return [
            ProfileConsistencyIssue(
                code="unresolved-mobility-origin",
                title="A starting point needs clarification",
                explanation=(
                    "At least one active starting point cannot be resolved safely. Correct a "
                    "possible typo or use a city plus district, postcode, station, or address."
                ),
                statements=tuple(dict.fromkeys(map(_label, unresolved))),
                fact_ids=tuple(dict.fromkeys(fact.id for fact in unresolved)),
            )
        ]

    separated: list[ProfileFact] = []
    for index, (left_fact, left_place) in enumerate(resolved):
        for right_fact, right_place in resolved[index + 1 :]:
            if straight_line_distance_km(left_place, right_place) > 30:
                separated.extend((left_fact, right_fact))
    if separated:
        return [
            ProfileConsistencyIssue(
                code="conflicting-mobility-origins",
                title="Several distant starting points are active",
                explanation=(
                    "Exact commute evidence needs one primary origin. Keep several origins only "
                    "if you intentionally want separate search directions, then acknowledge this "
                    "tension for the current run."
                ),
                statements=tuple(dict.fromkeys(map(_label, separated))),
                fact_ids=tuple(dict.fromkeys(fact.id for fact in separated)),
            )
        ]
    return []
