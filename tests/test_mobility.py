from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from betteroption.container import ApplicationContainer
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.mobility import (
    CommuteStatus,
    GoogleRoutesTravelTimeProvider,
    TravelEstimate,
    TravelQuery,
)
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelMode,
)
from betteroption.results import ResultService
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument


NOW = datetime.now(timezone.utc)


class FixedTravelProvider:
    name = "fixed-test-routes"

    def __init__(self, duration_minutes: int) -> None:
        self.duration_minutes = duration_minutes
        self.calls: list[TravelQuery] = []

    def estimate(self, query: TravelQuery) -> TravelEstimate:
        self.calls.append(query)
        return TravelEstimate(
            status=CommuteStatus.AVAILABLE,
            provider=self.name,
            duration_minutes=self.duration_minutes,
            distance_km=31.5,
            checked_at=NOW,
        )


def confirmed_fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text=value),
    )


def build_container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'mobility.db').as_posix()}")
    )


def seed_workspace_and_job(container: ApplicationContainer):
    session = new_session()
    session.profile.facts = [
        confirmed_fact("location.origin", "Frankfurt am Main", RequirementLevel.OPEN),
        confirmed_fact(
            "commute.transit.max_minutes",
            "45 minutes",
            RequirementLevel.MUST_HAVE,
        ),
        ProfileFact(
            key="role.family",
            value="embedded software",
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.DIRECTION,
                text="embedded software",
            ),
        ),
    ]
    workspace = container.workspaces.create(session)
    url = "https://careers.example.com/jobs/embedded"
    source = "Embedded software engineer in Alzenau."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Example",
        location="Alzenau, Germany",
        summary="Build embedded products.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
        facts=[
            JobFact(
                key="role.family",
                value="embedded software",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Embedded software engineer",
            )
        ],
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return workspace, record, job


def result_service(container: ApplicationContainer, provider: FixedTravelProvider) -> ResultService:
    return ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        container.mobility_service(provider),
    )


def test_matching_uses_and_reuses_a_cached_commute_estimate(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace, record, _job = seed_workspace_and_job(container)
    provider = FixedTravelProvider(38)
    service = result_service(container, provider)

    first = service.run(workspace)
    second = service.run(workspace)

    first_item = first.top[0]
    second_item = second.top[0]
    assert first_item.record.id == record.id
    assert first_item.stored.result.commutes[0].within_limit is True
    assert first_item.stored.result.commutes[0].cached is False
    assert second_item.stored.result.commutes[0].cached is True
    assert len(provider.calls) == 1
    assert first_item.stored.result.score >= 60
    assert all(
        reason.profile_fact_id != first_item.stored.result.commutes[0].profile_fact_id
        for reason in first_item.stored.result.reasons
    )


def test_a_proven_commute_boundary_conflict_blocks_the_must_have(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace, _record, _job = seed_workspace_and_job(container)
    groups = result_service(container, FixedTravelProvider(67)).run(workspace)

    assert groups.top == []
    assert groups.stretch == []
    assert len(groups.blocked) == 1
    assert groups.blocked[0].stored.result.hard_violations == 1
    assert groups.blocked[0].stored.result.commutes[0].within_limit is False


def test_google_routes_adapter_requests_only_duration_and_distance() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["field_mask"] = request.headers["X-Goog-FieldMask"]
        return httpx.Response(
            200,
            json={"routes": [{"duration": "2280s", "distanceMeters": 31500}]},
            request=request,
        )

    provider = GoogleRoutesTravelTimeProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    estimate = provider.estimate(
        TravelQuery(
            origin="Frankfurt am Main",
            destination="Alzenau",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 38
    assert estimate.distance_km == 31.5
    assert captured["field_mask"] == "routes.duration,routes.distanceMeters"
    assert captured["body"]["travelMode"] == "TRANSIT"
    assert captured["body"]["origin"] == {"address": "Frankfurt am Main"}
