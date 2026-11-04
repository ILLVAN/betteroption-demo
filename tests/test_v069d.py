from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.mobility import (
    CommuteAssessment,
    CommuteStatus,
    RouteConfidence,
    TravelEstimate,
)
from betteroption.presentation import commute_visual_state
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    ReviewAction,
    SourceExcerpt,
    TravelMode,
)
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.settings import Settings
from betteroption.web import create_app


class EmptyExtractor:
    model = "empty-test-model"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="The explicit statement was retained.",
            facts=[],
            follow_up_question=None,
        )


class SectionAwareExtractor:
    model = "section-aware-test-model"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="One statement was extracted.",
            facts=[
                ExtractedFactDraft(
                    key=(
                        "skill.experience"
                        if section == ProfileSection.EXPERIENCE
                        else "role.family"
                    ),
                    value=(
                        "Python" if section == ProfileSection.EXPERIENCE else "Platform engineering"
                    ),
                    level=RequirementLevel.OPEN,
                    evidence_status="explicit",
                    confidence=Confidence.HIGH,
                    source_quote=user_text,
                )
            ],
            follow_up_question=None,
        )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v069d.db').as_posix()}",
            _env_file=None,
        )
    )


def _fact(key: str, value: str) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.PREFERENCES, text=value),
    )


def test_explicit_section_addition_survives_empty_structured_extraction(tmp_path: Path) -> None:
    container = _container(tmp_path)
    service = ProfileWorkflowService(container.workspaces, extractor=EmptyExtractor())
    workspace = service.start()

    saved = service.add_section_detail(
        workspace.id,
        ProfileSection.PREFERENCES,
        "A product team with calm technical ownership",
    )

    assert [(fact.key, fact.value) for fact in saved.session.profile.confirmed_facts] == [
        (
            "user.preferences.statement",
            "A product team with calm technical ownership",
        )
    ]


def test_pending_cv_review_does_not_block_an_explicit_compass_addition(tmp_path: Path) -> None:
    container = _container(tmp_path)
    service = ProfileWorkflowService(container.workspaces, extractor=SectionAwareExtractor())
    workspace = service.start()
    service.add_private_evidence(workspace.id, "Python experience")

    saved = service.add_section_detail(
        workspace.id,
        ProfileSection.DIRECTION,
        "Platform engineering",
    )

    assert any(
        fact.value == "Platform engineering" for fact in saved.session.profile.confirmed_facts
    )
    assert any(fact.value == "Python" for fact in saved.session.profile.pending_facts)
    direction_fact = next(
        fact
        for fact in saved.session.profile.confirmed_facts
        if fact.value == "Platform engineering"
    )

    revised = service.revise_confirmed_fact(
        workspace.id,
        direction_fact.id,
        action=ReviewAction.EDIT_VALUE,
        new_value="Embedded platform engineering",
    )

    assert any(
        fact.value == "Embedded platform engineering"
        for fact in revised.session.profile.confirmed_facts
    )
    assert any(fact.value == "Python" for fact in revised.session.profile.pending_facts)


def test_active_projection_collapses_same_section_wording_across_ontology_keys() -> None:
    older = _fact("role.responsibility", "Prototyping")
    newer = _fact("skill.desired", "prototyping")

    profile = CandidateProfile(facts=[older, newer])

    assert [fact.id for fact in profile.confirmed_facts] == [newer.id]
    assert len(profile.facts) == 2


def _commute(status: CommuteStatus, duration: int | None, limit: int = 60) -> CommuteAssessment:
    return CommuteAssessment(
        profile_fact_id=uuid4(),
        profile_key="commute.car.max_minutes",
        profile_value="60 minutes by car",
        level=RequirementLevel.MUST_HAVE,
        origin="Frankfurt",
        destination="Darmstadt",
        mode=TravelMode.CAR,
        maximum_minutes=limit,
        estimate=TravelEstimate(
            status=status,
            provider="test",
            duration_minutes=duration,
            confidence=RouteConfidence.HIGH,
        ),
    )


def test_commute_visual_states_use_a_fifteen_percent_stretch_band() -> None:
    assert commute_visual_state(_commute(CommuteStatus.AVAILABLE, 60)) == "within"
    assert commute_visual_state(_commute(CommuteStatus.AVAILABLE, 69)) == "stretch"
    assert commute_visual_state(_commute(CommuteStatus.AVAILABLE, 70)) == "conflict"
    assert commute_visual_state(_commute(CommuteStatus.PROVIDER_ERROR, None)) == "unavailable"


def test_compass_actions_return_to_the_changed_section_or_statement(tmp_path: Path) -> None:
    container = _container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=EmptyExtractor(),
        )
    )
    started = client.post("/profile/start", follow_redirects=False)
    workspace_id = UUID(started.headers["location"].rsplit("/", 1)[-1])

    addition = client.post(
        f"/profile/{workspace_id}/sections/preferences/detail",
        data={"answer": "A calm product team"},
        follow_redirects=False,
    )
    assert addition.headers["location"].endswith("#section-preferences")
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    fact_id = workspace.session.profile.confirmed_facts[0].id

    edit = client.post(
        f"/profile/{workspace_id}/saved-facts/{fact_id}",
        data={
            "action": "edit_value",
            "new_value": "A calm technical product team",
            "new_level": "preference",
        },
        follow_redirects=False,
    )
    assert edit.headers["location"].endswith(f"#fact-{fact_id}")

    page = client.get(f"/profile/{workspace_id}")
    assert 'class="panel primary-action-shell compass-primary-action-shell"' in page.text
    assert page.text.count(">Guided setup <span") == 1
    assert "Continue guided setup" not in page.text


def test_default_discovery_depth_uses_the_full_keyless_feed_budget(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'settings.db').as_posix()}",
        _env_file=None,
    )

    assert settings.arbeitnow_discovery_pages == 30
