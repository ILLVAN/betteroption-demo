from __future__ import annotations

from pathlib import Path

from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.mobility import mobility_request_from_profile
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelMode,
)
from betteroption.profile_mobility import (
    canonicalize_mobility_fact,
    duration_minutes_from_text,
)
from betteroption.presentation import format_duration_minutes
from betteroption.session import new_session, record_section_extraction


def fact(
    key: str,
    value: str,
    *,
    source: str | None = None,
    level: RequirementLevel = RequirementLevel.MUST_HAVE,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.LOCATION_MOBILITY,
            text=source or value,
        ),
    )


def test_long_duration_labels_are_compact_and_zero_padded() -> None:
    assert format_duration_minutes(33) == "33 min"
    assert format_duration_minutes(60) == "1h"
    assert format_duration_minutes(72) == "1h 12m"
    assert format_duration_minutes(184) == "3h 04m"


def test_mobility_duration_parser_preserves_hours_and_minutes() -> None:
    assert duration_minutes_from_text("2 hours") == 120
    assert duration_minutes_from_text("1h 30m") == 90
    assert duration_minutes_from_text("1:12") == 72
    assert duration_minutes_from_text("90") == 90


def test_bare_modal_value_is_canonicalized_with_its_mode() -> None:
    commute = fact(
        "commute.bicycle.max_minutes",
        "2 hours",
        source="Up to two hours by e-bike is acceptable.",
    )

    assert canonicalize_mobility_fact(commute)
    assert commute.key == "commute.bicycle.max_minutes"
    assert commute.value == "120 minutes by bicycle one way"


def test_mode_free_limit_stays_open_and_cannot_drive_routing() -> None:
    commute = fact("commute.max_minutes", "90")

    assert canonicalize_mobility_fact(commute)
    assert commute.key == "commute.unresolved.max_minutes"
    assert commute.value == "90 minutes one way (travel mode not specified)"
    assert commute.level == RequirementLevel.OPEN

    profile = CandidateProfile(
        facts=[
            fact("location.origin", "60486 Frankfurt am Main"),
            commute,
        ]
    )
    assert mobility_request_from_profile(profile) is None


def test_location_extraction_stores_self_contained_modal_values() -> None:
    session = new_session()
    extraction = SectionExtraction(
        summary="Three commute limits were identified.",
        facts=[
            ExtractedFactDraft(
                key="commute.car.max_minutes",
                value="60",
                level="preference",
                evidence_status="explicit",
                confidence="high",
                source_quote="60 minutes by car",
            ),
            ExtractedFactDraft(
                key="commute.transit.max_minutes",
                value="80 minutes",
                level="must_have",
                evidence_status="explicit",
                confidence="high",
                source_quote="80 minutes by train",
            ),
        ],
        follow_up_question=None,
    )

    record_section_extraction(
        session,
        ProfileSection.LOCATION_MOBILITY,
        "60 minutes by car and 80 minutes by train",
        extraction,
    )

    assert [(item.key, item.value) for item in session.profile.facts] == [
        ("commute.car.max_minutes", "60 minutes by car one way"),
        ("commute.transit.max_minutes", "80 minutes by train one way"),
    ]


def test_canonical_modal_limit_produces_the_expected_route_request() -> None:
    origin = fact("location.origin", "60486 Frankfurt am Main")
    commute = fact(
        "commute.walk.max_minutes",
        "1h 15m",
        source="Walking for at most 1h 15m",
    )
    canonicalize_mobility_fact(commute)
    profile = CandidateProfile(facts=[origin, commute])

    request = mobility_request_from_profile(profile)

    assert request is not None
    assert request[0] == "60486 Frankfurt am Main"
    assert request[1][0][1:] == (TravelMode.WALK, 75)


def test_slow_workflows_have_accessible_busy_feedback() -> None:
    templates = Path(__file__).parents[1] / "src" / "betteroption" / "web" / "templates"
    static = templates.parent / "static"

    assert "data-busy-overlay" in (templates / "base.html").read_text(encoding="utf-8")
    assert "data-busy-message" in (templates / "matches.html").read_text(encoding="utf-8")
    assert "data-busy-message" in (templates / "profile_compass.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    assert 'form.addEventListener("submit"' in script
    assert 'window.addEventListener("pageshow", hideBusyOverlay)' in script
