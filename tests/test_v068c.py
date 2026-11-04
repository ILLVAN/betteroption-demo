from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx

from betteroption.mobility import (
    CommuteStatus,
    MobilityService,
    TransitousTravelTimeProvider,
    TravelQuery,
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


NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text=value),
    )


def _transit_profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            _fact("location.origin", "Frankfurt", RequirementLevel.OPEN),
            _fact("commute.transit.max_minutes", "60 minutes", RequirementLevel.MUST_HAVE),
        ]
    )


class NoOpCommuteRepository:
    def get(self, *args, **kwargs):
        return None

    def save(self, *args, **kwargs) -> None:
        return None


def _route_handler(plan_responses: list[httpx.Response] | None = None):
    plan_calls: list[httpx.Request] = []
    geocode_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/geocode"):
            geocode_calls.append(request)
            frankfurt = "Frankfurt" in request.url.params["text"]
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "type": "STOP",
                        "name": "Frankfurt Hbf" if frankfurt else "Alzenau Bahnhof",
                        "lat": 50.107 if frankfurt else 50.086,
                        "lon": 8.663 if frankfurt else 9.072,
                    }
                ],
            )
        plan_calls.append(request)
        if plan_responses:
            response = plan_responses.pop(0)
            return httpx.Response(
                response.status_code,
                request=request,
                headers=response.headers,
                json=response.json() if response.content else None,
            )
        return httpx.Response(200, request=request, json={"itineraries": [{"duration": 2_700}]})

    return handler, plan_calls, geocode_calls


def test_keyless_transitous_uses_one_seven_alternative_plan_per_matched_job() -> None:
    handler, plan_calls, geocode_calls = _route_handler()
    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    assessment = MobilityService(NoOpCommuteRepository(), provider).assess(
        uuid4(),
        uuid4(),
        _transit_profile(),
        "Alzenau",
    )[0]

    assert assessment.estimate.status == CommuteStatus.AVAILABLE
    assert assessment.estimate.duration_minutes == 45
    assert assessment.estimate.sample_minutes == [45]
    assert len(plan_calls) == 1
    assert len(geocode_calls) == 2
    assert plan_calls[0].url.params["numItineraries"] == "7"


def test_transitous_retries_one_rate_limit_and_exposes_the_http_status() -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"}),
        httpx.Response(200, json={"itineraries": [{"duration": 2_760}]}),
    ]
    handler, plan_calls, _ = _route_handler(responses)
    sleeps: list[float] = []
    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=sleeps.append,
    )

    estimate = provider.estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Alzenau",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 46
    assert len(plan_calls) == 2
    assert sleeps == [0.0]


def test_transitous_persistent_rate_limit_is_visible_as_http_429() -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"}),
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"}),
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"}),
    ]
    handler, _, _ = _route_handler(responses)
    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _: None,
    )

    estimate = provider.estimate(
        TravelQuery(origin="Frankfurt", destination="Alzenau", mode=TravelMode.TRANSIT)
    )

    assert estimate.status == CommuteStatus.PROVIDER_ERROR
    assert estimate.message == "Transitous lookup failed: HTTP 429"
    assert estimate.attempts == ["Transitous/MOTIS failed with HTTP 429."]
