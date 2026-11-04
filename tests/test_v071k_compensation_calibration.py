from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.matching import (
    SOLID_MATCH_CALIBRATION_CAP,
    MatchDisposition,
    match_job,
    solid_match_calibration_bonus,
)
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.profile import (
    COMPENSATION_RANGE_MIN_EUR,
    CandidateProfile,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import SectionStatus, new_session
from betteroption.settings import Settings
from betteroption.web import create_app


class SalaryExtractor:
    model = "salary-range-test"

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        assert section == ProfileSection.COMPENSATION_TIME
        assert "58,000" in user_text and "72,000" in user_text
        return SectionExtraction(
            summary="The annual gross minimum and target are explicit.",
            facts=[
                ExtractedFactDraft(
                    key="compensation.minimum",
                    value="EUR 58,000 gross/year",
                    level="must_have",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="minimum EUR 58,000",
                ),
                ExtractedFactDraft(
                    key="compensation.target",
                    value="EUR 72,000 gross/year",
                    level="preference",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="target EUR 72,000",
                ),
            ],
            follow_up_question=None,
        )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'compensation.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )


def test_default_and_legacy_profiles_project_to_the_neutral_ui_range() -> None:
    default = CandidateProfile()
    legacy_empty = CandidateProfile.model_validate({"compensation": {}})
    legacy_minimum = CandidateProfile.model_validate(
        {"compensation": {"minimum_gross_annual": 58_000}}
    )

    assert default.compensation.range_minimum_gross_annual == COMPENSATION_RANGE_MIN_EUR
    assert default.compensation.range_target_gross_annual is None
    assert not default.compensation.has_annual_gross_constraint
    assert legacy_empty.compensation.range_minimum_gross_annual == 0
    assert legacy_empty.compensation.range_target_gross_annual is None
    assert legacy_minimum.compensation.minimum_gross_annual == 58_000
    assert legacy_minimum.compensation.range_target_gross_annual is None


def test_guided_compensation_answer_populates_the_same_typed_range(tmp_path: Path) -> None:
    container = _container(tmp_path)
    session = new_session()
    for progress in session.sections[:3]:
        progress.status = SectionStatus.SKIPPED
    workspace = container.workspaces.create(session)
    service = ProfileWorkflowService(
        container.workspaces,
        extractor=SalaryExtractor(),
    )

    saved = service.answer(
        workspace.id,
        "My minimum is EUR 58,000 gross and my target is EUR 72,000 gross per year.",
    )

    assert saved.session.profile.compensation.minimum_gross_annual == 58_000
    assert saved.session.profile.compensation.target_gross_annual == 72_000
    assert saved.session.profile.compensation.minimum_level == RequirementLevel.MUST_HAVE


def test_compass_range_route_is_atomic_and_default_clears_constraints(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create(new_session())
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get(f"/profile/{workspace.id}")
    assert page.status_code == 200
    assert 'name="minimum_gross_annual"' in page.text
    assert 'name="target_gross_annual"' in page.text
    assert 'value="0"' in page.text
    assert 'value=""' in page.text
    assert 'value="300000">300k</option>' in page.text

    invalid = client.post(
        f"/profile/{workspace.id}/compensation-range",
        data={"minimum_gross_annual": "80000", "target_gross_annual": "60000"},
        follow_redirects=False,
    )
    unchanged = container.workspaces.get(workspace.id)
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    assert unchanged is not None
    assert not unchanged.session.profile.compensation.has_annual_gross_constraint

    saved = client.post(
        f"/profile/{workspace.id}/compensation-range",
        data={"minimum_gross_annual": "55000", "target_gross_annual": "70000"},
        follow_redirects=False,
    )
    reopened = container.workspaces.get(workspace.id)
    assert saved.status_code == 303
    assert reopened is not None
    assert reopened.session.profile.compensation.minimum_gross_annual == 55_000
    assert reopened.session.profile.compensation.target_gross_annual == 70_000
    active_salary = [
        fact
        for fact in reopened.session.profile.confirmed_facts
        if fact.key == "compensation.annual_gross"
    ]
    assert {(fact.value, fact.level) for fact in active_salary} == {
        ("EUR 55000", RequirementLevel.MUST_HAVE),
        ("EUR 70000", RequirementLevel.PREFERENCE),
    }

    reset = client.post(
        f"/profile/{workspace.id}/compensation-range",
        data={"minimum_gross_annual": "0", "target_gross_annual": ""},
        follow_redirects=False,
    )
    neutral = container.workspaces.get(workspace.id)
    assert reset.status_code == 303
    assert neutral is not None
    assert not neutral.session.profile.compensation.has_annual_gross_constraint
    assert not [
        fact
        for fact in neutral.session.profile.confirmed_facts
        if fact.key == "compensation.annual_gross"
    ]


@pytest.mark.parametrize(
    ("hard", "preferences", "skills", "expected"),
    [
        (0, 0, 0, 0),
        (1, 0, 0, 1),
        (1, 1, 1, 3),
        (4, 4, 4, SOLID_MATCH_CALIBRATION_CAP),
    ],
)
def test_solid_match_calibration_is_exact_and_capped(
    hard: int,
    preferences: int,
    skills: int,
    expected: int,
) -> None:
    assert (
        solid_match_calibration_bonus(
            satisfied_hard_requirements=hard,
            supporting_preferences=preferences,
            matched_required_skills=skills,
            hard_violations=0,
            violated_exclusion=False,
        )
        == expected
    )


def test_calibration_never_weakens_violations_or_private_rating_effects() -> None:
    assert (
        solid_match_calibration_bonus(
            satisfied_hard_requirements=10,
            supporting_preferences=10,
            matched_required_skills=10,
            hard_violations=1,
            violated_exclusion=False,
        )
        == 0
    )
    assert (
        solid_match_calibration_bonus(
            satisfied_hard_requirements=10,
            supporting_preferences=10,
            matched_required_skills=10,
            hard_violations=0,
            violated_exclusion=True,
        )
        == 0
    )

    profile = CandidateProfile(
        facts=[
            ProfileFact(
                key="role.family",
                value="software engineering",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence="high",
                source=SourceExcerpt(
                    section=ProfileSection.DIRECTION,
                    text="software engineering",
                ),
            )
        ]
    )
    job = JobPosting(
        title="Software Engineer",
        company="Example",
        location="Berlin",
        summary="Software engineering",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="Test",
        source_text="Software engineering",
        facts=[
            JobFact(
                key="role.family",
                value="software engineering",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Software engineering",
            )
        ],
    )
    neutral = match_job(profile, job)
    one_star = match_job(profile, job, job_rating_stars=1)
    zero_rated = match_job(profile, job, job_rating_stars=0)
    calibration = next(
        section
        for section in neutral.score_mechanics.sections
        if section.key == "solid_match_calibration"
    )

    assert 0 < calibration.applied_points <= SOLID_MATCH_CALIBRATION_CAP
    assert one_star.score == neutral.score - 12
    assert zero_rated.disposition == MatchDisposition.STRETCH
    assert zero_rated.score == 0
