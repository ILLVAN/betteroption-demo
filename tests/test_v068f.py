from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from betteroption.container import ApplicationContainer
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.geography import OfflinePlaceIndex
from betteroption.mobility import (
    CommuteStatus,
    FallbackTravelTimeProvider,
    TransitousTravelTimeProvider,
    TravelQuery,
    ValhallaTravelTimeProvider,
)
from betteroption.profile import EvidenceStatus, ProfileSection, TravelMode
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import SectionStatus, next_review_section, progress_for
from betteroption.settings import Settings


NOW = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)


def test_default_privacy_chain_covers_transit_and_non_transit_modes(tmp_path: Path) -> None:
    container = ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'mobility.db').as_posix()}")
    )

    provider = container.travel_time_provider()

    assert isinstance(provider, FallbackTravelTimeProvider)
    assert any(isinstance(item, TransitousTravelTimeProvider) for item in provider.providers)
    assert any(isinstance(item, ValhallaTravelTimeProvider) for item in provider.providers)


@pytest.mark.parametrize(
    ("mode", "costing"),
    [
        (TravelMode.CAR, "auto"),
        (TravelMode.BICYCLE, "bicycle"),
        (TravelMode.WALK, "pedestrian"),
    ],
)
def test_valhalla_routes_every_non_transit_mode_without_google(
    mode: TravelMode,
    costing: str,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["x-client-id"] == "betteroption.example"
        return httpx.Response(
            200,
            request=request,
            json={"trip": {"summary": {"time": 2_100, "length": 37.4}}},
        )

    estimate = ValhallaTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).estimate(
        TravelQuery(
            origin="60486",
            destination="Alzenau",
            mode=mode,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 35
    assert estimate.distance_km == 37.4
    assert estimate.origin_resolved == "60486 Frankfurt am Main, DE"
    assert captured["costing"] == costing
    alzenau = OfflinePlaceIndex().resolve("Alzenau")
    assert alzenau is not None
    assert estimate.destination_resolved == f"{alzenau.label}, {alzenau.country_code}"
    assert captured["locations"] == [
        {"lat": 50.1162, "lon": 8.6365, "type": "break"},
        {"lat": alzenau.latitude, "lon": alzenau.longitude, "type": "break"},
    ]


def test_valhalla_keeps_unresolvable_endpoint_unknown() -> None:
    estimate = ValhallaTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: None)),
    ).estimate(
        TravelQuery(
            origin="a private address without a city",
            destination="Alzenau",
            mode=TravelMode.WALK,
        )
    )

    assert estimate.status == CommuteStatus.NEEDS_PRECISE_LOCATION
    assert estimate.duration_minutes is None


class CompassExtractor:
    model = "test-compass-model"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="Platform engineering is now part of the Compass.",
            facts=[
                ExtractedFactDraft(
                    key="role.family",
                    value="Platform engineering",
                    level="preference",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="platform engineering",
                )
            ],
            follow_up_question=None,
        )


class InferredBoundaryExtractor:
    model = "test-inferred-boundary-model"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="One possible boundary was inferred.",
            facts=[
                ExtractedFactDraft(
                    key="industry.sector",
                    value="Defence",
                    level="exclusion",
                    evidence_status="inferred",
                    confidence="low",
                    source_quote="meaningful products",
                )
            ],
            follow_up_question=None,
        )


def compass_workflow(tmp_path: Path) -> ProfileWorkflowService:
    container = ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'compass.db').as_posix()}")
    )
    return ProfileWorkflowService(container.workspaces, extractor=CompassExtractor())


def test_compass_answer_is_active_immediately_but_remains_editable(tmp_path: Path) -> None:
    workflow = compass_workflow(tmp_path)
    workspace = workflow.start()

    saved = workflow.answer(workspace.id, "I want platform engineering.")

    fact = saved.session.profile.facts[0]
    assert fact.evidence_status == EvidenceStatus.CONFIRMED
    assert fact.needs_confirmation is False
    assert fact.user_note == "Accepted from the user's Compass answer; editable at any time"
    assert saved.session.profile.pending_facts == []
    assert next_review_section(saved.session) is None
    assert progress_for(saved.session, ProfileSection.DIRECTION).status == SectionStatus.COMPLETED


def test_targeted_compass_addition_is_active_without_review_tray(tmp_path: Path) -> None:
    workflow = compass_workflow(tmp_path)
    workspace = workflow.start()

    saved = workflow.add_section_detail(
        workspace.id,
        ProfileSection.DIRECTION,
        "I want platform engineering.",
    )

    assert len(saved.session.profile.confirmed_facts) == 1
    assert saved.session.profile.pending_facts == []
    assert next_review_section(saved.session) is None


def test_inferred_compass_fact_is_active_but_cannot_become_a_hidden_boundary(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'inferred.db').as_posix()}")
    )
    workflow = ProfileWorkflowService(
        container.workspaces,
        extractor=InferredBoundaryExtractor(),
    )
    workspace = workflow.start()

    saved = workflow.answer(workspace.id, "Meaningful products matter to me.")

    fact = saved.session.profile.confirmed_facts[0]
    assert fact.value == "Defence"
    assert fact.level.value == "open"
    assert fact.needs_confirmation is False
