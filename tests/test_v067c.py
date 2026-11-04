from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from betteroption.brave_search import (
    BraveSearchAuthenticationError,
    BraveSearchPlanError,
    BraveSearchRateLimitError,
)
from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    ArbeitnowDiscoveryProvider,
    BraveWebDiscoveryProvider,
    CompositeDiscoveryProvider,
    DiscoveredJob,
    DiscoveryQuery,
    discovery_query_from_profile,
)
from betteroption.mobility import (
    CommuteStatus,
    TransitousTravelTimeProvider,
    TravelQuery,
    query_fingerprint,
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
from betteroption.web import create_app


NOW = datetime(2026, 7, 20, 7, 0, tzinfo=timezone.utc)


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text=value),
    )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'v067c.db').as_posix()}",
            auth_mode="local",
            employer_homepage_research=False,
        )
    )


def test_transitous_disambiguates_frankfurt_and_chooses_shortest_itinerary() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/geocode"):
            if "Frankfurt" in request.url.params["text"]:
                return httpx.Response(
                    200,
                    request=request,
                    json=[
                        {
                            "name": "Frankfurt (Oder)",
                            "country": "DE",
                            "areas": [{"name": "Brandenburg", "matched": False}],
                            "score": 500,
                            "importance": 0.5,
                            "lat": 52.35,
                            "lon": 14.55,
                        },
                        {
                            "name": "Frankfurt am Main",
                            "country": "DE",
                            "areas": [{"name": "Hessen", "matched": True}],
                            "score": 100,
                            "importance": 0.9,
                            "lat": 50.11,
                            "lon": 8.68,
                        },
                    ],
                )
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "name": "Seligenstadt",
                        "country": "DE",
                        "areas": [{"name": "Hessen", "matched": False}],
                        "score": 100,
                        "lat": 50.04,
                        "lon": 8.97,
                    }
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "itineraries": [
                    {"duration": 26_520},
                    {
                        "duration": 2_700,
                        "startTime": "2026-07-20T09:00:00+02:00",
                        "endTime": "2026-07-20T09:45:00+02:00",
                    },
                ]
            },
        )

    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    estimate = provider.estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Seligenstadt",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 45
    assert calls[-1].url.params["fromPlace"] == "50.11,8.68"
    assert calls[-1].url.params["numItineraries"] == "7"
    assert any("Frankfurt am Main" in attempt for attempt in estimate.attempts)
    assert any("Seligenstadt" in attempt for attempt in estimate.attempts)


def test_transitous_duration_is_cross_checked_against_timestamps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/geocode"):
            is_frankfurt = "Frankfurt" in request.url.params["text"]
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "name": request.url.params["text"],
                        "lat": 50.1 if is_frankfurt else 50.04,
                        "lon": 8.7 if is_frankfurt else 8.97,
                    }
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "itineraries": [
                    {
                        "duration": 26_520,
                        "startTime": "2026-07-20T09:00:00+02:00",
                        "endTime": "2026-07-20T09:45:00+02:00",
                    }
                ]
            },
        )

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(TravelQuery(origin="Frankfurt", destination="Seligenstadt", mode="transit"))

    assert estimate.duration_minutes == 45
    assert any("disagreed" in attempt for attempt in estimate.attempts)


def test_commute_cache_fingerprint_invalidates_the_prefixed_release() -> None:
    query = TravelQuery(origin="Frankfurt", destination="Seligenstadt", mode="transit")
    old_material = "frankfurt|seligenstadt|transit|any"
    old_fingerprint = hashlib.sha256(old_material.encode()).hexdigest()

    assert query_fingerprint(query) != old_fingerprint


def test_compass_search_uses_direction_skills_and_origin_not_hard_boundaries() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("role.family", "Embedded software", RequirementLevel.PREFERENCE),
            _fact("skill.desired", "C++", RequirementLevel.PREFERENCE),
            _fact("location.origin", "Frankfurt am Main", RequirementLevel.OPEN),
            _fact("compensation.minimum", "€70,000", RequirementLevel.MUST_HAVE),
            _fact("industry.excluded", "Defence", RequirementLevel.EXCLUSION),
        ]
    )

    query = discovery_query_from_profile(profile)

    assert "Embedded software" in query.text
    assert "C++" in query.text
    assert "70,000" not in query.text
    assert "Defence" not in query.text
    assert query.location == "Frankfurt am Main"


def test_arbeitnow_location_is_a_boost_not_an_exact_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        rows = (
            [
                {
                    "slug": "firmware-seligenstadt",
                    "title": "Firmware Engineer",
                    "company_name": "Calm Machines",
                    "location": "Seligenstadt",
                    "remote": False,
                    "tags": ["RTOS"],
                    "description": "Embedded microcontroller development.",
                    "url": "https://www.arbeitnow.com/jobs/firmware-seligenstadt",
                    "created_at": 1_768_000_000,
                }
            ]
            if page == 1
            else []
        )
        return httpx.Response(200, request=request, json={"data": rows})

    jobs = ArbeitnowDiscoveryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_pages=8,
    ).search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert [job.title for job in jobs] == ["Firmware Engineer"]
    assert jobs[0].location == "Seligenstadt"


def test_optional_brave_search_excludes_sources_that_block_product_fetching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Embedded Engineer | Warm Systems Careers",
                            "url": "https://careers.warmsystems.example/jobs/123",
                            "description": "Develop embedded software near Frankfurt.",
                            "profile": {"long_name": "Warm Systems"},
                        },
                        {
                            "title": "Embedded Engineer Jobs",
                            "url": "https://www.linkedin.com/jobs/view/123",
                            "description": "Restricted aggregator result.",
                        },
                    ]
                }
            },
        )

    provider = BraveWebDiscoveryProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    jobs = provider.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert len(jobs) == 1
    assert jobs[0].company == "Warm Systems"
    assert jobs[0].provider == "brave-web"


@pytest.mark.parametrize(
    ("status_code", "error_type", "safe_marker"),
    [
        (401, BraveSearchAuthenticationError, "HTTP 401"),
        (403, BraveSearchPlanError, "Search-product access"),
        (429, BraveSearchRateLimitError, "HTTP 429"),
    ],
)
def test_brave_search_classifies_plan_failures_without_exposing_the_key(
    status_code: int,
    error_type: type[Exception],
    safe_marker: str,
) -> None:
    secret = "brave-secret-that-must-not-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, json={"message": secret})

    provider = BraveWebDiscoveryProvider(
        secret,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(error_type) as captured:
        provider.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert safe_marker in str(captured.value)
    assert secret not in str(captured.value)


def test_brave_search_treats_a_valid_empty_response_as_reached_not_failed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, json={"web": {"results": []}})

    provider = BraveWebDiscoveryProvider(
        "search-plan-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.search(DiscoveryQuery(text="rare role", location="Frankfurt")) == []
    assert calls > 0


def test_brave_search_probe_uses_one_fixed_web_search_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, request=request, json={"web": {"results": []}})

    provider = BraveWebDiscoveryProvider(
        "search-plan-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.validate_search_access()

    assert len(calls) == 1
    assert calls[0].url.path == "/res/v1/web/search"
    assert calls[0].url.params["q"] == "site:example.com"
    assert calls[0].url.params["count"] == "1"


def test_composite_search_deduplicates_and_keeps_each_source_visible() -> None:
    job = DiscoveredJob(
        provider="first",
        external_id="1",
        title="Embedded Engineer",
        company="Acme",
        source_url="https://acme.example/jobs/1?tracking=yes",
    )

    class Provider:
        def __init__(self, name: str) -> None:
            self.name = name
            self.attribution = f"{name} source"
            self.attribution_url = f"https://{name}.example/docs"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            return [job.model_copy(update={"provider": self.name})]

    provider = CompositeDiscoveryProvider([Provider("first"), Provider("second")])

    assert len(provider.search(DiscoveryQuery(text="embedded"))) == 1
    assert len(provider.attributions) == 2


def test_explore_can_run_directly_from_the_latest_compass(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    workspace.session.profile.facts.extend(
        [
            _fact("role.family", "Embedded software", RequirementLevel.PREFERENCE),
            _fact("location.origin", "Frankfurt am Main", RequirementLevel.OPEN),
        ]
    )
    container.workspaces.save(workspace)

    class Provider:
        name = "fixed"
        attribution = "Fixed"
        attribution_url = "https://feed.example/docs"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            assert "Embedded software" in query.text
            assert query.location == "Frankfurt am Main"
            return []

    app = create_app(container, data_directory=tmp_path / "data", discovery_provider=Provider())
    with TestClient(app) as client:
        response = client.get("/explore?use_compass=true", follow_redirects=False)
        assert response.status_code == 303
        task_path = urlsplit(response.headers["location"]).path
        assert task_path.startswith("/tasks/")
        deadline = monotonic() + 5
        status = None
        while monotonic() < deadline:
            status = client.get(f"{task_path}/status").json()
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            sleep(0.02)
        assert status is not None
        assert status["status"] == "succeeded", status
        page = client.get(status["result_url"])

    assert page.status_code == 200
    assert "Search with Compass" in page.text
    assert "This query came from your confirmed" in page.text
    assert 'value="Embedded software"' in page.text


def test_cv_preview_requires_data_rule_acknowledgement_and_copy_has_spacing(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get(f"/profile/{workspace.id}")
    css = client.get("/static/app.css")

    assert 'name="acknowledge_cv_rules" value="true" required' in page.text
    assert "Prepare private preview" in page.text
    assert 'name="extract_evidence"' not in page.text
    assert ".switch-row strong, .switch-row small { display: block; }" in css.text
