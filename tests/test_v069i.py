from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import MatchDisposition, match_job
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_consistency import inspect_profile_consistency
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.web import create_app


def _fact(
    key: str,
    value: str,
    level: RequirementLevel,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def test_consistency_check_flags_seniority_extremes_but_not_role_breadth() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("seniority.target", "senior", RequirementLevel.MUST_HAVE),
            _fact("role.level", "junior-level role", RequirementLevel.PREFERENCE),
            _fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            _fact("role.family", "test automation", RequirementLevel.PREFERENCE),
        ]
    )

    issues = inspect_profile_consistency(profile)

    assert [issue.code for issue in issues] == ["seniority-extremes"]
    assert "Junior and senior" in issues[0].title
    assert "embedded software" not in " ".join(issues[0].statements)


def test_consistency_check_flags_same_condition_wanted_and_excluded() -> None:
    profile = CandidateProfile(
        facts=[
            _fact(
                "industry.sector",
                "defence",
                RequirementLevel.MUST_HAVE,
                ProfileSection.MUST_HAVES,
            ),
            _fact(
                "industry.sector",
                "defence",
                RequirementLevel.EXCLUSION,
                ProfileSection.EXCLUSIONS,
            ),
        ]
    )

    issues = inspect_profile_consistency(profile)

    assert [issue.code for issue in issues] == ["opposite-level:industry.sector"]


def test_consistency_check_does_not_turn_a_matching_exclusion_into_a_positive_target() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("work_model.onsite", "onsite only", RequirementLevel.MUST_HAVE),
            _fact("work_model.remote", "fully remote", RequirementLevel.EXCLUSION),
        ]
    )

    assert "workplace-extremes" not in {
        issue.code for issue in inspect_profile_consistency(profile)
    }


def test_sparse_evidence_cannot_produce_an_eighty_point_score() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            _fact("role.responsibility", "product development", RequirementLevel.PREFERENCE),
            _fact("career.direction", "engineering", RequirementLevel.PREFERENCE),
            _fact("industry.sector", "automotive", RequirementLevel.PREFERENCE),
            _fact("work_model.remote", "hybrid", RequirementLevel.MUST_HAVE),
            _fact("employment.contract", "direct contract", RequirementLevel.MUST_HAVE),
            _fact("compensation.annual_gross", "65000", RequirementLevel.MUST_HAVE),
            _fact("work_model.weekly_hours", "35", RequirementLevel.MUST_HAVE),
            _fact("seniority.target", "junior", RequirementLevel.PREFERENCE),
        ]
    )
    job = JobPosting(
        title="Senior Embedded Product Engineer",
        company="Example",
        location="Frankfurt",
        summary="Senior automotive product engineering.",
        source_type=JobSourceType.SAMPLE,
        source_name="evidence calibration",
        source_text=(
            "Senior embedded software product development and engineering for automotive systems."
        ),
        facts=[
            JobFact(
                key="role.family",
                value="embedded software",
                kind=JobFactKind.CONTEXT,
                evidence_quote="embedded software",
            ),
            JobFact(
                key="role.responsibility",
                value="product development",
                kind=JobFactKind.CONTEXT,
                evidence_quote="product development",
            ),
            JobFact(
                key="career.direction",
                value="engineering",
                kind=JobFactKind.CONTEXT,
                evidence_quote="engineering",
            ),
            JobFact(
                key="industry.sector",
                value="automotive",
                kind=JobFactKind.CONTEXT,
                evidence_quote="automotive",
            ),
        ],
    )

    result = match_job(profile, job)

    assert result.score <= 70
    assert result.disposition == MatchDisposition.TOP
    assert result.hard_evidence_coverage == 0


def test_web_blocks_a_search_contradiction_without_an_acknowledgement_bypass(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'consistency.db').as_posix()}",
            auth_mode="local",
        )
    )
    session = new_session()
    session.profile.facts = [
        _fact(
            "industry.sector",
            "defence",
            RequirementLevel.MUST_HAVE,
            ProfileSection.MUST_HAVES,
        ),
        _fact(
            "industry.sector",
            "defence",
            RequirementLevel.EXCLUSION,
            ProfileSection.EXCLUSIONS,
        ),
    ]
    container.workspaces.create(session)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    blocked = client.post("/matches/run", follow_redirects=False)
    page = client.get("/matches")
    acknowledged = client.post(
        "/matches/run",
        data={"confirm_consistency": "true"},
        follow_redirects=False,
    )

    assert blocked.status_code == 303
    assert "same+condition+is+both+wanted+and+excluded" in blocked.headers["location"]
    assert "The same condition is both wanted and excluded" in page.text
    assert "Ask me later" not in page.text
    assert acknowledged.status_code == 303
    assert "same+condition+is+both+wanted+and+excluded" in acknowledged.headers["location"]


def test_bulk_deletion_has_server_visible_intent_and_accessible_dialog(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'dialog.db').as_posix()}",
            auth_mode="local",
        )
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get("/matches")

    assert "data-delete-dialog" in page.text
    assert "Delete permanently" in page.text
