from __future__ import annotations

from pathlib import Path
from uuid import UUID

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from betteroption.candidate_languages import (
    PROGRAMMING_LANGUAGES,
    SPOKEN_LANGUAGES,
    profile_language_selections,
)
from betteroption.container import ApplicationContainer
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import match_job, skill_is_evidenced_by_profile
from betteroption.mobility import CommuteAssessment, CommuteStatus, TravelEstimate
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
from betteroption.session import SectionStatus, progress_for
from betteroption.settings import Settings
from betteroption.web import create_app


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v072-languages.db').as_posix()}",
            auth_mode="local",
        )
    )


def _start(client: TestClient) -> UUID:
    response = client.post("/profile/start", follow_redirects=False)
    assert response.status_code == 303
    return UUID(response.headers["location"].rsplit("/", 1)[-1])


def _evidence_fact(key: str, value: str) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=RequirementLevel.OPEN,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.EXPERIENCE, text=value),
    )


def _job(*, source_text: str, facts: list[JobFact] | None = None) -> JobPosting:
    return JobPosting(
        title="Software Engineer",
        company="Example",
        location="Frankfurt",
        summary="Build software.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text=source_text,
        facts=facts or [],
    )


def test_catalogs_are_broad_stable_and_have_no_implicit_selection() -> None:
    assert len(SPOKEN_LANGUAGES) >= 180
    assert {"German", "Swahili", "Cantonese", "American Sign Language"}.issubset(SPOKEN_LANGUAGES)
    assert len(PROGRAMMING_LANGUAGES) >= 90
    assert {
        "Python",
        "C++",
        "VHDL",
        "Structured Text (IEC 61131-3)",
    }.issubset(PROGRAMMING_LANGUAGES)
    assert profile_language_selections(CandidateProfile(), programming=False) == {}
    assert profile_language_selections(CandidateProfile(), programming=True) == {}


def test_language_editors_persist_per_workspace_and_drive_experience_readiness(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    workspace_id = _start(client)

    saved = client.post(
        f"/profile/{workspace_id}/spoken-languages",
        data={
            "language_name": ["German", "Swahili"],
            "proficiency::German": "3",
            "proficiency::Swahili": "0",
        },
        follow_redirects=False,
    )

    assert saved.status_code == 303
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert {
        fact.value
        for fact in workspace.session.profile.confirmed_candidate_evidence
        if fact.key == "language.spoken"
    } == {"German · native", "Swahili · beginner"}
    assert (
        progress_for(workspace.session, ProfileSection.EXPERIENCE).status == SectionStatus.COMPLETED
    )

    restarted = _container(tmp_path)
    reopened = restarted.workspaces.get(workspace_id)
    assert reopened is not None
    assert profile_language_selections(
        reopened.session.profile,
        programming=False,
    ) == {"German": "native", "Swahili": "beginner"}

    removed = client.post(
        f"/profile/{workspace_id}/spoken-languages",
        data={},
        follow_redirects=False,
    )
    assert removed.status_code == 303
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert profile_language_selections(workspace.session.profile, programming=False) == {}
    assert (
        progress_for(workspace.session, ProfileSection.EXPERIENCE).status == SectionStatus.PENDING
    )


def test_removing_editor_language_keeps_readiness_when_other_experience_exists(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    workspace_id = _start(client)
    client.post(
        f"/profile/{workspace_id}/programming-languages",
        data={
            "language_name": "Python",
            "proficiency::Python": "2",
        },
    )
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    workspace.session.profile.facts.append(_evidence_fact("education.degree", "BEng"))
    container.workspaces.save(workspace)

    client.post(f"/profile/{workspace_id}/programming-languages", data={})

    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert (
        progress_for(workspace.session, ProfileSection.EXPERIENCE).status == SectionStatus.COMPLETED
    )
    assert [fact.value for fact in workspace.session.profile.confirmed_candidate_evidence] == [
        "BEng"
    ]


def test_compass_renders_collapsed_cv_and_accessible_searchable_language_tiles(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    workspace_id = _start(client)

    page = client.get(f"/profile/{workspace_id}")
    soup = BeautifulSoup(page.text, "html.parser")

    cv_tile = soup.select_one("details.v072-cv-tile")
    assert cv_tile is not None and not cv_tile.has_attr("open")
    spoken = soup.select_one("#spoken-languages")
    programming = soup.select_one("details#programming-languages")
    assert spoken is not None and programming is not None
    assert page.text.index('id="spoken-languages"') < page.text.index('id="programming-languages"')
    assert spoken.select_one('input[type="search"][aria-controls="spoken-language-options"]')
    assert spoken.select_one('input[value="German"]:not([checked])')
    assert programming.select_one('input[value="Python"]:not([checked])')
    spoken_slider = spoken.select_one('input[type="range"][data-language-level]')
    programming_slider = programming.select_one('input[type="range"][data-language-level]')
    assert spoken_slider is not None
    assert spoken_slider["min"] == "0" and spoken_slider["max"] == "3"
    assert spoken_slider["step"] == "1" and spoken_slider.has_attr("disabled")
    assert programming_slider is not None and programming_slider.has_attr("disabled")
    script = (Path(__file__).parents[1] / "src/betteroption/web/static/app.js").read_text(
        encoding="utf-8"
    )
    assert "level.disabled = !isSelected" in script
    assert 'level.setAttribute("aria-valuetext", label)' in script
    assert ">Train<" in page.text
    assert "Train &amp; transit" not in page.text


def test_spoken_and_programming_levels_are_soft_but_exact_presence_is_required() -> None:
    profile = CandidateProfile(
        facts=[
            _evidence_fact("language.spoken", "Swahili · beginner"),
            _evidence_fact("skill.programming_language", "Python · beginner"),
            _evidence_fact("skill.programming_language", "Java · professional"),
        ]
    )
    spoken_job = _job(source_text="Native-level Swahili is required for this role.")
    programming_job = _job(
        source_text="Professional Python development is required. JavaScript is required.",
        facts=[
            JobFact(
                key="skill.name",
                value="Python (professional)",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Professional Python development is required.",
            ),
            JobFact(
                key="skill.name",
                value="JavaScript",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="JavaScript is required.",
            ),
        ],
    )

    spoken_result = match_job(profile, spoken_job)
    programming_result = match_job(profile, programming_job)

    assert spoken_result.matched_required_skills == ["Swahili (native)"]
    assert programming_result.matched_required_skills == ["Python (professional)"]
    assert programming_result.missing_required_skills == ["JavaScript"]
    assert skill_is_evidenced_by_profile(profile, "Swahili (C2)")
    assert skill_is_evidenced_by_profile(profile, "Python (expert)")
    assert not skill_is_evidenced_by_profile(profile, "JavaScript")


def test_standard_mobility_reasons_are_scored_once_but_not_rendered_twice() -> None:
    car = ProfileFact(
        key="commute.car.max_minutes",
        value="40 minutes by car one way",
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text="40 min by car"),
    )
    walk = ProfileFact(
        key="commute.walk.max_minutes",
        value="20 minutes walking one way",
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text="20 min walking"),
    )

    def assessment(fact: ProfileFact, mode: TravelMode, minutes: int) -> CommuteAssessment:
        return CommuteAssessment(
            profile_fact_id=fact.id,
            profile_key=fact.key,
            profile_value=str(fact.value),
            level=fact.level,
            origin="Frankfurt",
            destination="Offenbach",
            mode=mode,
            maximum_minutes=60,
            estimate=TravelEstimate(
                status=CommuteStatus.AVAILABLE,
                provider="test",
                duration_minutes=minutes,
            ),
        )

    result = match_job(
        CandidateProfile(facts=[car, walk]),
        _job(source_text="Build software in Offenbach."),
        commutes=[
            assessment(car, TravelMode.CAR, 25),
            assessment(walk, TravelMode.WALK, 15),
        ],
    )

    assert all(reason.profile_fact_id != car.id for reason in result.reasons)
    assert any(reason.profile_fact_id == walk.id for reason in result.reasons)
    assert result.score_mechanics is not None
    compass = next(
        section for section in result.score_mechanics.sections if section.key == "compass"
    )
    assert compass.applied_points == 8
