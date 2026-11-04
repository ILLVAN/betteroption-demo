from __future__ import annotations

from betteroption.discovery import (
    DiscoveryQuery,
    _market_safe_web_location,
    _resolve_discovery_place,
)
from betteroption.geography import OfflineGermanPostalCodeIndex, OfflinePlaceIndex


def _leipzig_query() -> DiscoveryQuery:
    return DiscoveryQuery(
        text="embedded software",
        location="Leipzig Central Station",
    )


def test_city_name_outranks_generic_station_alias_in_compass_origin() -> None:
    place = _resolve_discovery_place(
        "Leipzig Central Station",
        OfflinePlaceIndex(),
        OfflineGermanPostalCodeIndex(),
    )

    assert place is not None
    assert place.label == "Leipzig"
    assert place.country_code == "DE"


def test_web_fallback_rejects_foreign_job_when_query_location_only_appears_in_summary() -> None:
    location = _market_safe_web_location(
        "Embedded Engineer in Davao Oriental",
        "Semantic results for embedded software near Leipzig Central Station.",
        _leipzig_query(),
        ["Leipzig"],
        remote=False,
        source_url="https://ph.trabajo.org/jobs/embedded-engineer",
    )

    assert location is None


def test_web_fallback_accepts_locality_visible_only_in_a_real_job_excerpt() -> None:
    location = _market_safe_web_location(
        "Embedded Engineer | Warm Systems Careers",
        "Develop embedded software near Leipzig.",
        _leipzig_query(),
        ["Leipzig"],
        remote=False,
        source_url="https://careers.warmsystems.example/jobs/123",
    )

    assert location == "Leipzig"


def test_web_fallback_keeps_unresolved_market_neutral_job_visibly_unknown() -> None:
    location = _market_safe_web_location(
        "Embedded Engineer | Acme Careers",
        "Build embedded software in a product team.",
        _leipzig_query(),
        ["Leipzig"],
        remote=False,
        source_url="https://careers.acme.example/jobs/embedded-engineer",
    )

    assert location == "Location to verify"


def test_web_fallback_accepts_requested_locality_when_visible_in_title() -> None:
    location = _market_safe_web_location(
        "Junior Embedded Engineer in Leipzig",
        "Build control software for industrial products.",
        _leipzig_query(),
        ["Leipzig"],
        remote=False,
    )

    assert location == "Leipzig"


def test_remote_web_fallback_requires_an_explicit_requested_market_signal() -> None:
    rejected = _market_safe_web_location(
        "Remote Embedded Engineer",
        "Join a product team based in the Philippines.",
        _leipzig_query(),
        ["Leipzig"],
        remote=True,
    )
    accepted = _market_safe_web_location(
        "Remote Embedded Engineer",
        "This role can be performed remotely from Germany.",
        _leipzig_query(),
        ["Leipzig"],
        remote=True,
    )

    assert rejected is None
    assert accepted == "Remote · DE"
