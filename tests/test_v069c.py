from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from betteroption.company_intelligence import CompanyIntelligenceService
from betteroption.container import ApplicationContainer
from betteroption.cv import CvRetention
from betteroption.discovery import DiscoveredJob, DiscoveryQuery, finalize_discovered_jobs
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchOutcome, match_job
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.settings import Settings


def _fact(
    key: str,
    value: str,
    level: RequirementLevel = RequirementLevel.PREFERENCE,
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


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(database_url=f"sqlite:///{(tmp_path / 'v069c.db').as_posix()}")
    )


def test_active_compass_projection_hides_repeated_equivalent_preferences() -> None:
    older = _fact("skill.desired", "Research and development")
    newer = _fact("skill.name", "research & development")
    profile = CandidateProfile(facts=[older, newer])

    assert [fact.id for fact in profile.confirmed_facts] == [newer.id]
    assert len(profile.facts) == 2  # audit evidence remains intact


def test_local_roles_beat_remote_roles_without_a_remote_preference() -> None:
    query = DiscoveryQuery(text="test automation", location="60486")
    jobs = [
        DiscoveredJob(
            provider="test",
            external_id="remote",
            title="Test Automation Engineer",
            company="Remote Company",
            location="Remote",
            remote=True,
            summary="Automate software tests.",
            source_url="https://remote.example/jobs/1",
        ),
        DiscoveredJob(
            provider="test",
            external_id="local",
            title="Test Automation Engineer",
            company="Local Company",
            location="Darmstadt",
            summary="Automate software tests.",
            source_url="https://local.example/jobs/1",
        ),
    ]

    ranked = finalize_discovered_jobs(query, jobs)

    assert ranked[0].company == "Local Company"
    hidden = finalize_discovered_jobs(query.model_copy(update={"include_remote_jobs": False}), jobs)
    assert [job.company for job in hidden] == ["Local Company"]


def test_feedback_can_be_saved_as_one_editable_compass_preference(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    service = ProfileWorkflowService(container.workspaces)

    service.add_feedback_preference(
        workspace.id,
        "More hands-on development",
        source_label="Example role",
    )
    service.add_feedback_preference(
        workspace.id,
        "More hands-on development",
        source_label="Example role",
    )

    saved = container.workspaces.get(workspace.id)
    assert saved is not None
    learned = [
        fact for fact in saved.session.profile.confirmed_facts if fact.key == "feedback.preference"
    ]
    assert [fact.value for fact in learned] == ["More hands-on development"]
    assert learned[0].source.section == ProfileSection.PREFERENCES


def test_cv_repository_records_completed_review_state(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    document = container.cvs.save(
        workspace.id,
        "resume.txt",
        "text/plain",
        b"Python and German language experience in embedded test automation.",
        CvRetention.UNTIL_DELETED,
    )

    reviewed = container.cvs.mark_reviewed(workspace.id, document.id)

    assert document.reviewed_at is None
    assert reviewed.reviewed_at is not None
    assert container.cvs.get(workspace.id, document.id).reviewed_at is not None


def test_attributed_product_profile_reduces_unrelated_exclusion_uncertainty() -> None:
    job = JobPosting(
        title="Test Automation Engineer",
        company="Heating Optimizer",
        location="Frankfurt",
        summary="Test software for building energy optimization.",
        source_type=JobSourceType.URL_TEXT,
        source_name="Employer careers",
        source_url="https://heating.example/careers/test",
        requested_url="https://heating.example/careers/test",
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        source_text="We optimize renewable energy use in buildings.",
    )
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text="Our energy software optimizes heating in commercial buildings.",
        homepage_url="https://heating.example/",
    )
    profile = CandidateProfile(
        facts=[_fact("industry.excluded", "military", RequirementLevel.EXCLUSION)]
    )
    context = JobContext(
        employer=EmployerAssessment(
            kind=EmployerKind.DIRECT_EMPLOYER,
            confidence=ContextConfidence.MEDIUM,
            likely_direct_contract=True,
            explanation="Employer source.",
        ),
        company_intelligence=intelligence,
    )

    result = match_job(profile, job, context=context)
    reason = next(item for item in result.reasons if item.profile_value == "military")

    assert reason.outcome == MatchOutcome.SUPPORTING
    assert reason.evidence_urls[0] == "https://heating.example/"
    assert "https://heating.example/careers/test" in reason.evidence_urls
    assert "does not prove absence" in reason.explanation


def test_explicit_spoken_language_requirement_uses_candidate_evidence() -> None:
    profile = CandidateProfile(
        facts=[_fact("language.spoken", "German C1", section=ProfileSection.EXPERIENCE)]
    )
    job = JobPosting(
        title="Test Automation Engineer",
        company="Example",
        location="Frankfurt",
        summary="Automate tests.",
        source_type=JobSourceType.SAMPLE,
        source_name="fixture",
        source_text="Fließende Deutschkenntnisse auf mindestens C1 sind erforderlich.",
    )

    result = match_job(profile, job)

    assert result.matched_required_skills == ["German (C1)"]
    assert result.missing_required_skills == []
