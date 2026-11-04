from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from betteroption.accounts import AccountRepository, RegistrationMode
from betteroption.database import Database
from betteroption.job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    JobEvidenceOverrideRepository,
    ReasonOverrideValue,
    SkillOverrideValue,
)
from betteroption.job_repository import JobObservationKind, JobRepository
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchOutcome, match_job
from betteroption.mobility import CommuteAssessment, CommuteStatus, TravelEstimate
from betteroption.personas import PersonaRepository
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
from betteroption.profile_repository import ProfileWorkspaceRepository
from betteroption.url_ingestion import FetchedDocument


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
JOB_URL = "https://careers.example.com/jobs/user-evidence"


def _fact(
    key: str,
    value: str,
    level: RequirementLevel,
    *,
    section: ProfileSection = ProfileSection.MUST_HAVES,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def _job() -> JobPosting:
    return JobPosting(
        title="Senior Python Engineer",
        company="Example Products",
        location="Frankfurt",
        summary="Lead a Python engineering team.",
        source_type=JobSourceType.URL_TEXT,
        source_name=JOB_URL,
        source_url=JOB_URL,
        requested_url=JOB_URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text="Senior Python Engineer with at least 6 years of experience. Python required.",
        facts=[
            JobFact(
                key="skill.name",
                value="Python",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Python required.",
            )
        ],
        observed_at=NOW,
    )


def _store_job(repository: JobRepository) -> UUID:
    document = FetchedDocument(
        requested_url=JOB_URL,
        final_url=JOB_URL,
        status_code=200,
        content_type="text/html",
        text="Senior Python Engineer. Python required.",
        fetched_at=NOW,
    )
    return repository.store_revision(document, _job(), JobObservationKind.NEW).id


def test_repository_keeps_same_job_corrections_isolated_by_workspace(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'overrides.db').as_posix()}")
    workspaces = ProfileWorkspaceRepository(database)
    jobs = JobRepository(database)
    overrides = JobEvidenceOverrideRepository(database)
    workspace_a = workspaces.create()
    workspace_b = workspaces.create()
    record_id = _store_job(jobs)

    saved_a = overrides.upsert(
        JobEvidenceOverride(
            workspace_id=workspace_a.id,
            job_record_id=record_id,
            kind=JobEvidenceOverrideKind.SKILL,
            target_key="python",
            target_label="Python",
            skill_value=SkillOverrideValue.MATCHED,
        )
    )
    saved_b = overrides.upsert(
        JobEvidenceOverride(
            workspace_id=workspace_b.id,
            job_record_id=record_id,
            kind=JobEvidenceOverrideKind.SKILL,
            target_key="python",
            target_label="Python",
            skill_value=SkillOverrideValue.MISSING,
        )
    )

    assert saved_a.workspace_id != saved_b.workspace_id
    assert overrides.list_for_job(workspace_a.id, record_id)[0].skill_value == "matched"
    assert overrides.list_for_job(workspace_b.id, record_id)[0].skill_value == "missing"
    assert overrides.delete(
        workspace_a.id,
        record_id,
        JobEvidenceOverrideKind.SKILL,
        "python",
    )
    assert overrides.list_for_job(workspace_a.id, record_id) == []
    assert len(overrides.list_for_job(workspace_b.id, record_id)) == 1


def test_repository_follows_persona_across_replacement_compass_workspaces(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'persona-overrides.db').as_posix()}")
    accounts = AccountRepository(database)
    personas = PersonaRepository(database)
    workspaces = ProfileWorkspaceRepository(database)
    jobs = JobRepository(database)
    overrides = JobEvidenceOverrideRepository(database)
    account = accounts.create(
        "persona@example.com",
        "Persona Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    persona = personas.create(account.id, "Main", maximum_personas=5)
    first_workspace = workspaces.create(account_id=account.id, persona_id=persona.id)
    record_id = _store_job(jobs)
    overrides.upsert(
        JobEvidenceOverride(
            workspace_id=first_workspace.id,
            job_record_id=record_id,
            kind=JobEvidenceOverrideKind.SKILL,
            target_key="python",
            target_label="Python",
            skill_value=SkillOverrideValue.MATCHED,
        )
    )

    replacement_workspace = workspaces.create(account_id=account.id, persona_id=persona.id)

    inherited = overrides.list_for_job(replacement_workspace.id, record_id)
    assert len(inherited) == 1
    assert inherited[0].workspace_id == first_workspace.id
    assert inherited[0].skill_value == "matched"

    overrides.upsert(
        JobEvidenceOverride(
            workspace_id=replacement_workspace.id,
            job_record_id=record_id,
            kind=JobEvidenceOverrideKind.SKILL,
            target_key="python",
            target_label="Python",
            skill_value=SkillOverrideValue.MISSING,
        )
    )
    updated = overrides.list_for_job(replacement_workspace.id, record_id)
    assert len(updated) == 1
    assert updated[0].skill_value == "missing"


def test_reason_and_skill_overrides_recompute_outcomes_without_editing_compass() -> None:
    seniority = _fact("seniority.target", "junior", RequirementLevel.MUST_HAVE)
    profile = CandidateProfile(facts=[seniority])
    job = _job()
    automatic = match_job(profile, job)
    automatic_reason = next(
        reason for reason in automatic.reasons if reason.profile_fact_id == seniority.id
    )
    assert automatic_reason.outcome == MatchOutcome.VIOLATED
    assert "Python" in automatic.missing_required_skills

    corrected = match_job(
        profile,
        job,
        job_overrides=[
            JobEvidenceOverride(
                workspace_id=profile.id,
                job_record_id=job.id,
                kind=JobEvidenceOverrideKind.REASON,
                target_key=str(seniority.id),
                target_label=seniority.value,
                reason_value=ReasonOverrideValue.POSITIVE,
                note="The responsibilities are junior despite the title.",
            ),
            JobEvidenceOverride(
                workspace_id=profile.id,
                job_record_id=job.id,
                kind=JobEvidenceOverrideKind.SKILL,
                target_key="python",
                target_label="Python",
                skill_value=SkillOverrideValue.MATCHED,
            ),
        ],
    )
    corrected_reason = next(
        reason for reason in corrected.reasons if reason.profile_fact_id == seniority.id
    )

    assert corrected_reason.outcome == MatchOutcome.SATISFIED
    assert corrected_reason.automatic_outcome == MatchOutcome.VIOLATED
    assert corrected_reason.user_overridden
    assert corrected.hard_violations == 0
    assert corrected.score > automatic.score
    assert corrected.user_overridden_matched_skills == ["Python"]
    assert "Python" not in corrected.missing_required_skills
    assert profile.facts == [seniority]


def test_commute_override_preserves_provider_value_but_drives_boundary() -> None:
    commute_fact = _fact(
        "commute.car_minutes_max",
        "At most 30 minutes by car",
        RequirementLevel.MUST_HAVE,
        section=ProfileSection.LOCATION_MOBILITY,
    )
    assessment = CommuteAssessment(
        profile_fact_id=commute_fact.id,
        profile_key=commute_fact.key,
        profile_value=commute_fact.value,
        level=commute_fact.level,
        origin="Frankfurt",
        destination="Darmstadt",
        mode=TravelMode.CAR,
        maximum_minutes=30,
        estimate=TravelEstimate(
            status=CommuteStatus.AVAILABLE,
            provider="test-router",
            duration_minutes=50,
        ),
    )
    profile = CandidateProfile(facts=[commute_fact])
    automatic = match_job(profile, _job(), commutes=[assessment])
    corrected = match_job(
        profile,
        _job(),
        commutes=[assessment],
        job_overrides=[
            JobEvidenceOverride(
                workspace_id=profile.id,
                job_record_id=assessment.profile_fact_id,
                kind=JobEvidenceOverrideKind.COMMUTE_MINUTES,
                target_key=str(commute_fact.id),
                target_label="Car commute to Darmstadt",
                commute_minutes=20,
            )
        ],
    )

    assert automatic.hard_violations == 1
    assert corrected.hard_violations == 0
    assert corrected.commutes[0].estimate.duration_minutes == 50
    assert corrected.commutes[0].automatic_duration_minutes == 50
    assert corrected.commutes[0].user_override_minutes == 20
    assert all(row.profile_fact_id != commute_fact.id for row in corrected.reasons)
