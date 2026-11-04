from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock

import httpx

from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryQuery,
    SourceReadiness,
    _market_safe_web_location,
    _same_discovery_market,
)
from betteroption.discovery_sources import ExaFallbackDiscoveryProvider
from betteroption.url_ingestion import FetchedDocument


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_default_market_scope_is_continent_safe_without_being_europe_specific() -> None:
    assert _same_discovery_market("DE", "FR")
    assert _same_discovery_market("CA", "US")
    assert _same_discovery_market("PH", "JP")
    assert not _same_discovery_market("DE", "PH")
    assert not _same_discovery_market("CA", "PH")


def test_worldwide_search_can_keep_an_explicit_cross_continent_location() -> None:
    query = DiscoveryQuery(
        text="embedded software",
        location="Leipzig",
        worldwide=True,
    )

    location = _market_safe_web_location(
        "Embedded Software Engineer in Davao",
        "Build embedded products in the Philippines.",
        query,
        ["Leipzig"],
        remote=False,
        source_url="https://ph.trabajo.org/jobs/embedded-engineer",
    )

    assert location is not None
    assert "Davao" in location


def test_exa_keeps_multiple_focused_searches_inside_one_provider_budget() -> None:
    payloads: list[dict[str, object]] = []
    lock = Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        with lock:
            payloads.append(payload)
            index = len(payloads)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"exa-{index}",
                        "title": f"Embedded Software Engineer in Leipzig {index}",
                        "url": f"https://careers.example/jobs/embedded-{index}",
                        "highlights": ["Build embedded software in Leipzig."],
                        "publishedDate": "2026-07-20T10:00:00Z",
                    }
                ]
            },
        )

    provider = ExaFallbackDiscoveryProvider(
        "secret",
        client=_client(handler),
        search_budget_seconds=10,
    )
    query = DiscoveryQuery(
        text="embedded software",
        location="Leipzig",
        desired_terms=["embedded software", "test automation"],
        limit=100,
    )
    jobs = provider.search(query)

    assert len(payloads) >= 2
    assert provider.last_request_count == len(payloads)
    assert provider.maximum_request_count(query) == len(payloads)
    assert all(payload["userLocation"] == "DE" for payload in payloads)
    assert jobs
    assert all(job.location == "Leipzig" for job in jobs)


class _CountingFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, url: str) -> FetchedDocument:
        self.calls += 1
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            text="Embedded Engineer. Responsibilities and qualifications. Apply now.",
            fetched_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )


def test_freshness_checks_are_bounded_and_unchecked_web_hits_fail_closed() -> None:
    fetcher = _CountingFetcher()
    availability = DiscoveryAvailabilityFilter(
        fetcher=fetcher,  # type: ignore[arg-type]
        maximum_checks=5,
        maximum_checks_per_host=1,
        total_timeout_seconds=2,
    )
    jobs = [
        DiscoveredJob(
            provider="exa-fallback",
            external_id=str(index),
            title=f"Embedded Engineer {index}",
            company=f"Employer {index}",
            location="Leipzig",
            source_url=f"https://careers{index}.example/jobs/{index}",
        )
        for index in range(30)
    ]

    kept = availability.keep_open_or_unknown(jobs)

    assert fetcher.calls == 5
    assert [job.external_id for job in kept] == [job.external_id for job in jobs[:5]]
    assert all(job.source_readiness == SourceReadiness.READY for job in kept)


def test_unresolved_location_never_receives_invented_zero_distance() -> None:
    from betteroption.discovery import finalize_discovered_jobs

    job = DiscoveredJob(
        provider="exa-fallback",
        external_id="unknown-place",
        title="Embedded Software Engineer",
        company="Acme",
        location="Location to verify",
        source_url="https://careers.example/jobs/unknown-place",
    )

    ranked = finalize_discovered_jobs(
        DiscoveryQuery(text="embedded software", location="Leipzig"),
        [job],
    )

    assert ranked[0].distance_km is None
    assert ranked[0].distance_relevance is None
