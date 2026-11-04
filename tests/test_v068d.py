from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from betteroption.geography import OfflineGermanPostalCodeIndex
from betteroption.jobs import JobPosting, JobSourceType, normalize_placeholder_employer
from betteroption.mobility import (
    CommuteStatus,
    GoogleRoutesTravelTimeProvider,
    TransitousTravelTimeProvider,
    TravelQuery,
    _company_destination_search_hint,
)
from betteroption.profile import TravelMode


NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


def test_transitous_rejects_wrong_alzenau_station_and_uses_the_actual_city() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/geocode"):
            query = request.url.params["text"]
            if "Frankfurt" in query:
                return httpx.Response(
                    200,
                    request=request,
                    json=[
                        {
                            "type": "PLACE",
                            "name": "Frankfurt am Main",
                            "country": "DE",
                            "lat": 50.1155,
                            "lon": 8.6842,
                        }
                    ],
                )
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "type": "STOP",
                        "name": "Zum Alten Bahnhof",
                        "country": "DE",
                        "importance": 100,
                        "lat": 50.97781,
                        "lon": 8.09141,
                    },
                    {
                        "type": "PLACE",
                        "name": "Alzenau",
                        "country": "DE",
                        "lat": 50.0888,
                        "lon": 9.06455,
                    },
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": [{"duration": 2_700}]},
        )

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Alzenau",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 45
    assert estimate.destination_resolved == "Alzenau, DE"
    assert any("requested locality" in note for note in estimate.attempts)


def test_german_postcode_is_resolved_locally_before_transitous_routing() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/geocode"):
            assert "60486" not in request.url.params["text"]
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "type": "PLACE",
                        "name": "Alzenau",
                        "country": "DE",
                        "lat": 50.0888,
                        "lon": 9.06455,
                    }
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": [{"duration": 4_080}]},
        )

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(
        TravelQuery(
            origin="60486",
            destination="Alzenau",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 68
    assert estimate.origin_resolved == "60486 Frankfurt am Main, DE"
    assert sum(request.url.path.endswith("/geocode") for request in requests) == 1
    assert any("resolved locally" in note for note in estimate.attempts)


def test_bundled_postcode_index_maps_60486_to_frankfurt() -> None:
    place = OfflineGermanPostalCodeIndex().resolve("60486")

    assert place is not None
    assert place.label == "60486 Frankfurt am Main"
    assert place.country_code == "DE"
    assert place.latitude == 50.1162
    assert place.longitude == 8.6365


def test_unsafe_geocoder_result_is_an_explicit_error_not_a_false_route() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=[
                {
                    "type": "STOP",
                    "name": "Zum Alten Bahnhof",
                    "country": "DE",
                    "lat": 50.97781,
                    "lon": 8.09141,
                }
            ],
        )

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(TravelQuery(origin="Alzenau", destination="Darmstadt", mode=TravelMode.TRANSIT))

    assert estimate.status == CommuteStatus.PROVIDER_ERROR
    assert "location could not be geocoded safely" in (estimate.message or "")


def test_known_personio_demo_company_is_replaced_by_repeated_body_identity() -> None:
    source = (
        "Company: The Demo Daten GmbH\n"
        "Why othermo? Build energy-saving gateway hardware with othermo."
    )
    job = JobPosting(
        title="Testing Engineer / QA (m/w/d)",
        company="The Demo Daten GmbH",
        location="Alzenau",
        summary="Test firmware.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text=source,
    )

    corrected = normalize_placeholder_employer(job)

    assert corrected.company == "othermo"
    assert any("demo employer placeholder" in warning for warning in corrected.extraction_warnings)


def test_arbitrary_company_names_are_never_rewritten() -> None:
    job = JobPosting(
        title="Engineer",
        company="Actual Employer GmbH",
        location="Alzenau",
        summary="Build products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text="Why anotherco? anotherco builds products.",
    )

    assert normalize_placeholder_employer(job).company == "Actual Employer GmbH"


def test_company_poi_hint_is_used_only_when_no_precise_job_address_exists() -> None:
    assert _company_destination_search_hint("othermo GmbH", "Alzenau") == "othermo GmbH, Alzenau"
    assert (
        _company_destination_search_hint("othermo GmbH", "Siemensstraße 30, 63755 Alzenau") is None
    )


def test_google_receives_the_company_poi_hint_but_retains_the_evidenced_destination() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={"routes": [{"duration": "2700s", "distanceMeters": 38_000}]},
        )

    query = TravelQuery(
        origin="Frankfurt",
        destination="Alzenau",
        destination_search_hint="othermo GmbH, Alzenau",
        mode=TravelMode.TRANSIT,
        departure_at=NOW,
    )
    estimate = GoogleRoutesTravelTimeProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).estimate(query)

    assert estimate.status == CommuteStatus.AVAILABLE
    assert captured["destination"] == {"address": "othermo GmbH, Alzenau"}
    assert query.destination == "Alzenau"
