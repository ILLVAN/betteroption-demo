from __future__ import annotations

import json
from pathlib import Path

import httpx

from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.discovery_sources import (
    AshbyDiscoveryProvider,
    AtsDiscoveryExpander,
    ConfiguredAtsBoard,
    DiscoverySourceMesh,
    ExaFallbackDiscoveryProvider,
    GreenhouseDiscoveryProvider,
    LeverDiscoveryProvider,
    parse_configured_boards,
)
from betteroption.extraction import SectionExtraction
from betteroption.mobility import NominatimPlaceResolver, RoutePrecision
from betteroption.profile import EvidenceStatus, ProfileSection
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import new_session, record_section_extraction
from betteroption.settings import Settings


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def _job(
    external_id: str,
    *,
    provider: str = "test",
    title: str = "Embedded Software Engineer",
    url: str | None = None,
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        external_id=external_id,
        title=title,
        company="Example Systems",
        location="Frankfurt am Main",
        summary="Embedded software and firmware development.",
        source_url=url or f"https://example.com/jobs/{external_id}",
    )


class StaticDiscoveryProvider:
    name = "static"
    attribution = "Static test source"
    attribution_url = "https://example.com/source"

    def __init__(self, jobs: list[DiscoveredJob]) -> None:
        self.jobs = jobs
        self.calls = 0

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.calls += 1
        return self.jobs[: query.limit]


def test_configured_ats_boards_are_explicit_and_deduplicated() -> None:
    boards = parse_configured_boards(
        "Example GmbH=example; Example GmbH=example; EU GmbH=eu:eu-board",
        allow_eu_prefix=True,
    )

    assert [(board.company, board.token, board.region) for board in boards] == [
        ("Example GmbH", "example", "global"),
        ("EU GmbH", "eu-board", "eu"),
    ]


def test_greenhouse_connector_reads_only_public_job_board_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.params["content"] == "true"
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 42,
                        "title": "Embedded Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/42",
                        "location": {"name": "Berlin, Germany"},
                        "content": "<p>Build embedded firmware.</p>",
                        "departments": [{"name": "Engineering"}],
                        "updated_at": "2026-08-02T09:30:00Z",
                    }
                ]
            },
        )

    provider = GreenhouseDiscoveryProvider(
        [ConfiguredAtsBoard("Acme", "acme")],
        client=_client(handler),
    )

    jobs = provider.search(DiscoveryQuery(text="embedded", location="Berlin"))

    assert len(jobs) == 1
    assert jobs[0].provider == "greenhouse"
    assert jobs[0].company == "Acme"
    assert jobs[0].summary == "Build embedded firmware."
    assert jobs[0].published_at is None


def test_lever_connector_honours_the_european_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.eu.lever.co"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "job-1",
                    "text": "Firmware Developer",
                    "hostedUrl": "https://jobs.eu.lever.co/acme/job-1",
                    "descriptionPlain": "Develop embedded firmware.",
                    "categories": {
                        "location": "Munich, Germany",
                        "team": "Engineering",
                    },
                    "createdAt": 1_752_000_000_000,
                }
            ],
        )

    provider = LeverDiscoveryProvider(
        [ConfiguredAtsBoard("Acme EU", "acme", region="eu")],
        client=_client(handler),
    )

    jobs = provider.search(DiscoveryQuery(text="firmware", location="Munich"))

    assert len(jobs) == 1
    assert jobs[0].provider == "lever"
    assert jobs[0].company == "Acme EU"


def test_ashby_connector_reads_listed_jobs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.ashbyhq.com"
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "listed",
                        "title": "Embedded Software Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/listed",
                        "location": "Hamburg, Germany",
                        "descriptionPlain": "Embedded C and C++ development.",
                        "isListed": True,
                    },
                    {
                        "id": "hidden",
                        "title": "Hidden Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/hidden",
                        "location": "Hamburg, Germany",
                        "isListed": False,
                    },
                ]
            },
        )

    provider = AshbyDiscoveryProvider(
        [ConfiguredAtsBoard("Acme", "acme")],
        client=_client(handler),
    )

    jobs = provider.search(DiscoveryQuery(text="embedded", location="Hamburg"))

    assert [job.external_id for job in jobs] == ["acme:listed"]


def test_ats_expansion_detects_a_public_board_from_a_seed_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "boards-api.greenhouse.io"
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 2,
                        "title": "Embedded Test Engineer",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
                        "location": {"name": "Dresden, Germany"},
                        "content": "Test embedded systems.",
                    }
                ]
            },
        )

    expander = AtsDiscoveryExpander(client=_client(handler))
    seed = _job(
        "seed",
        url="https://job-boards.greenhouse.io/acme/jobs/1",
    )

    jobs = expander.search(
        DiscoveryQuery(text="embedded", location="Dresden"),
        [seed],
    )

    assert [job.external_id for job in jobs] == ["acme:2"]


def test_source_mesh_skips_paid_fallback_when_primary_coverage_is_enough() -> None:
    primary = StaticDiscoveryProvider([_job(str(index)) for index in range(3)])
    fallback = StaticDiscoveryProvider([_job("fallback", provider="fallback")])
    mesh = DiscoverySourceMesh(
        [primary],
        fallback_providers=[fallback],
        fallback_min_results=3,
    )

    jobs = mesh.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert len(jobs) == 3
    assert fallback.calls == 0
    assert mesh.last_fallback_used is False


def test_source_mesh_uses_fallback_only_below_the_configured_floor() -> None:
    primary = StaticDiscoveryProvider([_job("primary")])
    fallback = StaticDiscoveryProvider([_job("fallback", provider="fallback")])
    mesh = DiscoverySourceMesh(
        [primary],
        fallback_providers=[fallback],
        fallback_min_results=2,
    )

    jobs = mesh.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert {job.external_id for job in jobs} == {"primary", "fallback"}
    assert fallback.calls == 1
    assert mesh.last_fallback_used is True


def test_excluded_primary_source_cannot_suppress_fallback_coverage() -> None:
    primary = StaticDiscoveryProvider(
        [
            _job(
                "excluded",
                provider="exa-fallback",
                url="https://absolventa.de/jobs/channel/engineering",
            )
        ]
    )
    fallback = StaticDiscoveryProvider([_job("fallback", provider="fallback")])
    mesh = DiscoverySourceMesh(
        [primary],
        fallback_providers=[fallback],
        fallback_min_results=1,
    )

    jobs = mesh.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert [job.external_id for job in jobs] == ["fallback"]
    assert fallback.calls == 1


def test_exa_fallback_returns_traceable_candidates_without_copying_job_pages() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "malformed",
                        "title": "Malformed job",
                        "url": "https://[",
                    },
                    {
                        "id": "exa-1",
                        "title": "Embedded Engineer | Acme Careers",
                        "url": "https://careers.acme.example/jobs/embedded-engineer",
                        "highlights": ["Build embedded software in a product team."],
                        "publishedDate": "2026-07-20T10:00:00Z",
                    },
                ]
            },
        )

    provider = ExaFallbackDiscoveryProvider("secret", client=_client(handler))

    jobs = provider.search(DiscoveryQuery(text="embedded", location="Frankfurt"))

    assert len(jobs) == 1
    assert jobs[0].provider == "exa-fallback"
    assert jobs[0].location == "Location to verify"
    assert "linkedin.com" in captured["excludeDomains"]  # type: ignore[operator]
    assert "absolventa.de" in captured["excludeDomains"]  # type: ignore[operator]
    assert captured["numResults"] == 40


def test_user_authored_mobility_limits_survive_an_empty_model_extraction() -> None:
    session = new_session()
    extraction = SectionExtraction(
        summary="No structured details returned.",
        facts=[],
        follow_up_question=None,
    )

    record_section_extraction(
        session,
        ProfileSection.LOCATION_MOBILITY,
        ("Maximum 60 minutes by car one way, 80 minutes by train, and 180 minutes by bicycle."),
        extraction,
    )

    assert {(fact.key, fact.value) for fact in session.profile.facts} == {
        ("commute.car.max_minutes", "60 minutes by car one way"),
        ("commute.transit.max_minutes", "80 minutes by train one way"),
        ("commute.bicycle.max_minutes", "180 minutes by bicycle one way"),
    }


class EmptyMobilityExtractor:
    model = "empty-mobility-test"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="The explicit mobility statement was saved.",
            facts=[],
            follow_up_question=None,
        )


def test_targeted_modal_limit_is_saved_and_supersedes_only_the_same_mode(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'profile.db').as_posix()}")
    )
    workflow = ProfileWorkflowService(
        container.workspaces,
        extractor=EmptyMobilityExtractor(),
    )
    workspace = workflow.start()

    workflow.add_section_detail(
        workspace.id,
        ProfileSection.LOCATION_MOBILITY,
        "Maximum 30 minutes by car one way.",
    )
    workflow.add_section_detail(
        workspace.id,
        ProfileSection.LOCATION_MOBILITY,
        "Maximum 80 minutes by train one way.",
    )
    saved = workflow.add_section_detail(
        workspace.id,
        ProfileSection.LOCATION_MOBILITY,
        "Maximum 60 minutes by car one way.",
    )

    active = {
        (fact.key, fact.value)
        for fact in saved.session.profile.facts
        if fact.evidence_status == EvidenceStatus.CONFIRMED
    }
    assert active == {
        ("commute.car.max_minutes", "60 minutes by car one way"),
        ("commute.transit.max_minutes", "80 minutes by train one way"),
    }
    rejected_car = [
        fact
        for fact in saved.session.profile.facts
        if fact.key == "commute.car.max_minutes" and fact.evidence_status == EvidenceStatus.REJECTED
    ]
    assert [fact.value for fact in rejected_car] == ["30 minutes by car one way"]


def test_generic_nominatim_resolver_accepts_matching_european_districts() -> None:
    responses = {
        "Frankfurt Bockenheim": {
            "display_name": "Bockenheim, Innenstadt II, Frankfurt am Main, Hessen, Germany",
            "lat": "50.123",
            "lon": "8.642",
            "addresstype": "suburb",
            "address": {"suburb": "Bockenheim", "city": "Frankfurt am Main"},
        },
        "Berlin Kreuzberg": {
            "display_name": "Kreuzberg, Friedrichshain-Kreuzberg, Berlin, Germany",
            "lat": "52.493",
            "lon": "13.383",
            "addresstype": "suburb",
            "address": {"suburb": "Kreuzberg", "city": "Berlin"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[responses[request.url.params["q"]]])

    resolver = NominatimPlaceResolver(client=_client(handler))

    assert resolver.resolve("Frankfurt Bockenheim").precision == RoutePrecision.DISTRICT  # type: ignore[union-attr]
    assert resolver.resolve("Berlin Kreuzberg").precision == RoutePrecision.DISTRICT  # type: ignore[union-attr]


def test_generic_nominatim_resolver_rejects_a_same_name_wrong_city() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "display_name": "Bockenheim an der Weinstrasse, Rheinland-Pfalz, Germany",
                    "lat": "49.606",
                    "lon": "8.184",
                    "addresstype": "village",
                    "address": {"village": "Bockenheim an der Weinstrasse"},
                }
            ],
        )

    resolver = NominatimPlaceResolver(client=_client(handler))

    assert resolver.resolve("Frankfurt Bockenheim") is None
