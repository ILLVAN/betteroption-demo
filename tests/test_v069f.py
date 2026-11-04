from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryQuery,
)
from betteroption.mobility import FallbackTravelTimeProvider
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument, UrlFailureKind, UrlIngestionError
from betteroption.web.app import create_app


class _Provider:
    def __init__(self, name: str, *, persistent_cache_allowed: bool) -> None:
        self.name = name
        self.persistent_cache_allowed = persistent_cache_allowed

    def estimate(self, query):  # pragma: no cover - composition test only
        raise AssertionError("estimate should not run")


class _AvailabilityFetcher:
    def fetch(self, url: str):
        if "closed" in url:
            raise UrlIngestionError(
                "job page returned HTTP 410",
                kind=UrlFailureKind.EXPIRED,
                http_status=410,
            )
        if "blocked" in url:
            raise UrlIngestionError(
                "robots.txt blocks this URL",
                kind=UrlFailureKind.BLOCKED,
            )
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            text="We are hiring. Responsibilities and qualifications. Apply now.",
            fetched_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )


class _RememberingDiscovery:
    name = "remembering"
    attribution = "Test discovery"
    attribution_url = "https://example.com/discovery"

    def __init__(self) -> None:
        self.calls = 0
        self.last_regional_count = 1

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.calls += 1
        return [
            DiscoveredJob(
                provider="test",
                external_id=str(self.calls),
                title=f"{query.text.title()} Engineer",
                company="Example",
                location=query.location or "Frankfurt",
                summary="Build useful systems.",
                source_url=f"https://example.com/jobs/{self.calls}",
            )
        ]


def _job(identity: str) -> DiscoveredJob:
    return DiscoveredJob(
        provider="exa-fallback",
        external_id=identity,
        title=f"Job {identity}",
        company="Example",
        source_url=f"https://example.com/jobs/{identity}",
    )


def test_balanced_fallback_chain_does_not_read_a_lower_priority_route_cache() -> None:
    chain = FallbackTravelTimeProvider(
        [
            _Provider("google-routes", persistent_cache_allowed=False),
            _Provider("valhalla-osm", persistent_cache_allowed=True),
        ]
    )

    assert chain.persistent_cache_allowed is True
    assert chain.persistent_cache_read_allowed is False


def test_only_successfully_verified_web_discoveries_remain() -> None:
    availability = DiscoveryAvailabilityFilter(
        fetcher=_AvailabilityFetcher(),
        max_workers=2,
        cache_ttl=timedelta(minutes=1),
    )

    kept = availability.keep_open_or_unknown([_job("open"), _job("closed"), _job("blocked")])

    assert [job.external_id for job in kept] == ["open"]


def test_explore_remembers_the_last_successful_search_until_replaced(tmp_path: Path) -> None:
    provider = _RememberingDiscovery()
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
            auth_mode="local",
        )
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=provider,
        )
    )

    first = client.get("/explore?q=embedded&location=Frankfurt")
    client.get("/")
    remembered = client.get("/explore")
    replacement = client.get("/explore?q=automation&location=Darmstadt")

    assert "Embedded Engineer" in first.text
    assert "Embedded Engineer" in remembered.text
    assert provider.calls == 2
    assert "Automation Engineer" in replacement.text
    assert "Embedded Engineer" not in replacement.text
