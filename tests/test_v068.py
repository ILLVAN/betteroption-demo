from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from betteroption.access import ProductAccessPolicy
from betteroption.container import ApplicationContainer
from betteroption.geography import OfflinePlaceIndex
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.mobility import (
    CommuteStatus,
    FallbackTravelTimeProvider,
    RouteConfidence,
    RoutePrecision,
    TravelEstimate,
    TravelQuery,
    _aggregate_confidence,
    _complete_route_metadata,
    _label_precision,
    _minimum_cache_ttl,
    _plausibility_issue,
    _provider_attribution,
    _query_precision,
    _route_scope,
    _stored_confidence,
    _stored_endpoint_precision,
    _stored_precision,
    _stored_samples,
    _window_message,
    routing_destination_from_job,
)
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
from betteroption.settings import Settings


NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


class WindowProvider:
    name = "window-test"
    persistent_cache_allowed = False
    peak_window_sampling = True

    def __init__(self, durations: list[int]) -> None:
        self.durations = iter(durations)
        self.calls: list[TravelQuery] = []

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        self.calls.append(query)
        duration = next(self.durations)
        return TravelEstimate(
            status=CommuteStatus.AVAILABLE,
            provider=self.name,
            duration_minutes=duration,
            distance_km=30,
            checked_at=NOW,
            confidence=RouteConfidence.HIGH,
            cache_permitted=False,
        )


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text=value),
    )


def _profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            _fact("location.origin", "Frankfurt am Main", RequirementLevel.OPEN),
            _fact("commute.transit.max_minutes", "60 minutes", RequirementLevel.MUST_HAVE),
        ]
    )


def test_matching_route_uses_three_weekday_samples_and_the_median() -> None:
    container = ApplicationContainer(Settings(database_url="sqlite:///:memory:"))
    provider = WindowProvider([31, 38, 44])

    assessment = container.mobility_service(provider).assess(
        uuid4(),
        uuid4(),
        _profile(),
        "Darmstadt",
    )[0]

    assert len(provider.calls) == 3
    assert [call.departure_at.hour for call in provider.calls] == [7, 8, 8]
    assert [call.departure_at.minute for call in provider.calls] == [30, 0, 30]
    assert assessment.estimate.duration_minutes == 38
    assert assessment.estimate.duration_low_minutes == 31
    assert assessment.estimate.duration_high_minutes == 44
    assert assessment.estimate.sample_minutes == [31, 38, 44]
    assert assessment.estimate.confidence == RouteConfidence.HIGH


def test_extreme_route_outlier_is_not_used_for_matching() -> None:
    container = ApplicationContainer(Settings(database_url="sqlite:///:memory:"))
    provider = WindowProvider([30, 442, 34])

    estimate = (
        container.mobility_service(provider)
        .assess(
            uuid4(),
            uuid4(),
            _profile(),
            "Darmstadt",
        )[0]
        .estimate
    )

    assert estimate.duration_minutes == 32
    assert estimate.sample_minutes == [30, 34]
    assert estimate.confidence == RouteConfidence.MEDIUM
    assert any("result rejected" in attempt for attempt in estimate.attempts)


def test_routing_uses_the_most_precise_advertisement_evidence() -> None:
    source = "Work at Example Street 12, 60311 Frankfurt am Main."
    job = JobPosting(
        title="Engineer",
        company="Example",
        location="Frankfurt am Main",
        summary="Build products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text=source,
        facts=[
            JobFact(
                key="location.address",
                value="Example Street 12, 60311 Frankfurt am Main",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Example Street 12, 60311 Frankfurt am Main",
            )
        ],
    )

    assert routing_destination_from_job(job) == "Example Street 12, 60311 Frankfurt am Main"


def test_google_is_an_explicit_balanced_mode_choice() -> None:
    privacy_first = ApplicationContainer(
        Settings(
            database_url="sqlite:///:memory:",
            google_routes_api_key="secret",
            mobility_privacy_mode="privacy_first",
        )
    ).travel_time_provider()
    balanced = ApplicationContainer(
        Settings(
            database_url="sqlite:///:memory:",
            google_routes_api_key="secret",
            mobility_privacy_mode="balanced",
        )
    ).travel_time_provider()

    assert isinstance(privacy_first, FallbackTravelTimeProvider)
    assert [provider.name for provider in privacy_first.providers] == [
        "transitous",
        "valhalla-osm",
    ]
    assert isinstance(balanced, FallbackTravelTimeProvider)
    assert [provider.name for provider in balanced.providers][:2] == [
        "google-routes",
        "transitous",
    ]


def test_v068_keeps_twenty_five_equal_full_quality_slots_and_no_explore_routing() -> None:
    policy = ProductAccessPolicy()

    assert policy.max_stored_jobs == 25
    assert policy.free_match_result_limit == 25
    assert policy.exact_route_match_limit == 25
    assert policy.explore_exact_routing_enabled is False


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Frankfurt am Main", RoutePrecision.CITY_TO_CITY),
        ("Sachsenhausen district", RoutePrecision.DISTRICT),
        ("60311 Frankfurt am Main", RoutePrecision.POSTAL_CODE),
        ("Mainzer Landstraße 50, 60329 Frankfurt", RoutePrecision.ADDRESS),
        ("Frankfurt Hauptbahnhof", RoutePrecision.RAIL_HUB),
    ],
)
def test_route_label_precision_is_explicit(label: str, expected: RoutePrecision) -> None:
    assert _label_precision(label) == expected


def test_route_scope_describes_what_the_endpoints_can_prove() -> None:
    assert (
        _route_scope(TravelQuery(origin="Frankfurt", destination="Darmstadt", mode="transit"))
        == "station_to_station"
    )
    assert (
        _route_scope(
            TravelQuery(
                origin="Frankfurt",
                destination="Example Street 1, 64283 Darmstadt",
                mode="transit",
            )
        )
        == "station_to_door"
    )
    assert (
        _route_scope(
            TravelQuery(
                origin="Example Street 1, 60311 Frankfurt",
                destination="Darmstadt",
                mode="transit",
            )
        )
        == "door_to_station"
    )
    assert (
        _route_scope(
            TravelQuery(
                origin="Example Street 1, 60311 Frankfurt",
                destination="Work Road 2, 64283 Darmstadt",
                mode="car",
            )
        )
        == "door_to_door"
    )


def test_cached_route_compatibility_helpers_tolerate_old_or_invalid_values() -> None:
    city_query = TravelQuery(origin="Frankfurt", destination="Darmstadt", mode="transit")

    assert _stored_samples("[31, 38, 44]", None) == [31, 38, 44]
    assert _stored_samples("not-json", 39) == [39]
    assert _stored_samples(None, None) == []
    assert _stored_precision("address", city_query, "google-routes") == RoutePrecision.ADDRESS
    assert _stored_precision("invalid", city_query, "transitous") == RoutePrecision.RAIL_HUB
    assert _stored_confidence("high") == RouteConfidence.HIGH
    assert _stored_confidence("invalid") == RouteConfidence.LOW
    assert _stored_endpoint_precision(None, "Frankfurt", "transitous") == RoutePrecision.RAIL_HUB
    assert (
        _stored_endpoint_precision("invalid", "60311 Frankfurt", "google-routes")
        == RoutePrecision.POSTAL_CODE
    )
    assert _provider_attribution("google-routes")[0] == "Google Maps"
    assert _provider_attribution("unknown") == (None, None)


def test_route_metadata_and_window_helpers_cover_degraded_samples() -> None:
    query = TravelQuery(
        origin="Example Street 1, 60311 Frankfurt",
        destination="Work Road 2, 64283 Darmstadt",
        mode=TravelMode.CAR,
    )
    raw = TravelEstimate(
        status=CommuteStatus.AVAILABLE,
        provider="google-routes",
        duration_minutes=37,
    )

    completed = _complete_route_metadata(raw, query)

    assert completed.duration_low_minutes == 37
    assert completed.duration_high_minutes == 37
    assert completed.sample_minutes == [37]
    assert completed.confidence == RouteConfidence.HIGH
    assert completed.route_scope == "door_to_door"
    assert _query_precision(query) == RoutePrecision.ADDRESS
    assert _aggregate_confidence(completed, 1) == RouteConfidence.LOW
    assert _aggregate_confidence(completed, 2) == RouteConfidence.MEDIUM
    assert _minimum_cache_ttl([completed]) is None
    assert (
        _minimum_cache_ttl(
            [
                completed.model_copy(update={"cache_ttl_seconds": 3_600}),
                completed.model_copy(update={"cache_ttl_seconds": 7_200}),
            ]
        )
        == 3_600
    )
    assert _window_message(None, 3).startswith("Typical weekday")
    assert _window_message("Provider note.", 2).endswith("Provider note.")


@pytest.mark.parametrize(
    ("mode", "minutes"),
    [
        (TravelMode.TRANSIT, 442),
        (TravelMode.CAR, 400),
        (TravelMode.BICYCLE, 400),
        (TravelMode.WALK, 1),
    ],
)
def test_plausibility_bounds_reject_extreme_routes(mode: TravelMode, minutes: int) -> None:
    query = TravelQuery(origin="Frankfurt", destination="Darmstadt", mode=mode)
    estimate = TravelEstimate(
        status=CommuteStatus.AVAILABLE,
        provider="test",
        duration_minutes=minutes,
    )

    assert _plausibility_issue(query, estimate, OfflinePlaceIndex()) is not None
