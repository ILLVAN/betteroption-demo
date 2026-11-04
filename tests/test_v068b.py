from __future__ import annotations

from datetime import datetime, timezone

import httpx

from betteroption.mobility import (
    CommuteStatus,
    RoutePrecision,
    TransitousTravelTimeProvider,
    TravelQuery,
)
from betteroption.profile import TravelMode


NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


def test_transitous_uses_city_geocoding_without_inventing_an_alzenau_station() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/geocode"):
            query = request.url.params["text"]
            if "Frankfurt" in query:
                return httpx.Response(
                    200,
                    request=request,
                    json=[
                        {
                            "type": "STOP",
                            "name": "Frankfurt (Main) Hbf",
                            "lat": 50.107,
                            "lon": 8.663,
                        }
                    ],
                )
            if query == "Alzenau, Germany":
                return httpx.Response(
                    200,
                    request=request,
                    json=[
                        {
                            "type": "PLACE",
                            "name": "Alzenau",
                            "country": "DE",
                            "lat": 50.086,
                            "lon": 9.072,
                        }
                    ],
                )
            raise AssertionError(f"unexpected geocode query: {query}")
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": [{"duration": 2_760}]},
        )

    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    estimate = provider.estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Alzenau",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    geocode_queries = [
        request.url.params["text"] for request in calls if request.url.path.endswith("/geocode")
    ]
    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 46
    assert estimate.destination_resolved == "Alzenau, DE"
    assert estimate.destination_precision == RoutePrecision.CITY_TO_CITY
    assert geocode_queries == [
        "Frankfurt am Main, Hessen, Germany",
        "Alzenau, Germany",
    ]


def test_transitous_does_not_repeat_an_identical_city_centre_route() -> None:
    plan_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/geocode"):
            query = request.url.params["text"]
            station_query = "Bahnhof" in query or "Hauptbahnhof" in query
            frankfurt = "Frankfurt" in query
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "type": "STOP" if station_query else "PLACE",
                        "name": query,
                        "lat": (50.107 if station_query else 50.110)
                        if frankfurt
                        else (50.086 if station_query else 50.091),
                        "lon": (8.663 if station_query else 8.682)
                        if frankfurt
                        else (9.072 if station_query else 9.064),
                    }
                ],
            )
        plan_calls.append(request)
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": []},
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

    assert estimate.status == CommuteStatus.NO_ROUTE
    assert estimate.duration_minutes is None
    assert len(plan_calls) == 1


def test_transitous_geocoding_is_reused_across_morning_samples() -> None:
    geocode_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal geocode_calls
        if request.url.path.endswith("/geocode"):
            geocode_calls += 1
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
        return httpx.Response(200, request=request, json={"itineraries": [{"duration": 2_700}]})

    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    for minute in (30, 0, 30):
        provider.estimate(
            TravelQuery(
                origin="Frankfurt",
                destination="Alzenau",
                mode=TravelMode.TRANSIT,
                departure_at=NOW.replace(hour=7 if minute == 30 else 8, minute=minute),
            )
        )

    assert geocode_calls == 2
