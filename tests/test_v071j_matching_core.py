from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from alembic.script import ScriptDirectory

from betteroption.accounts import RegistrationMode
from betteroption.company_intelligence import (
    CompanyIntelligence,
    CompanyProductProfile,
    EmployerReputationSummary,
    IntelligenceConfidence,
)
from betteroption.container import ApplicationContainer
from betteroption.database import _migration_config
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
)
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import (
    JobFact,
    JobFactKind,
    JobPosting,
    JobSourceType,
    JobUrlStatus,
)
from betteroption.matching import (
    CONTEXT_COMPANY_REVENUE_MODEL,
    CONTEXT_EMPLOYER_RELATIONSHIP,
    CONTEXT_SALARY_RANGE,
    CONTEXT_WORK_MODE_PREFIX,
    MatchDisposition,
    match_job,
)
from betteroption.salary import SalaryGuess
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument


NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            ProfileFact(
                key="role.family",
                value="software engineering",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.DIRECTION,
                    text="software engineering",
                ),
            )
        ]
    )


def _job() -> JobPosting:
    source = "Software engineering is the core responsibility."
    return JobPosting(
        title="Software Engineer",
        company="Example Products GmbH",
        location="Berlin",
        summary=source,
        source_type=JobSourceType.URL_TEXT,
        source_name="Example careers",
        requested_url="https://careers.example/jobs/1",
        source_url="https://careers.example/jobs/1",
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
        facts=[
            JobFact(
                key="role.family",
                value="software engineering",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Software engineering",
            )
        ],
    )


def _context() -> JobContext:
    return JobContext(
        employer=EmployerAssessment(
            kind=EmployerKind.DIRECT_EMPLOYER,
            confidence=ContextConfidence.MEDIUM,
            likely_direct_contract=True,
            explanation="The source supports a direct employer relationship.",
        ),
        company_intelligence=CompanyIntelligence(
            company="Example Products GmbH",
            product=CompanyProductProfile(
                summary="The company sells software subscriptions.",
                revenue_model="software subscriptions",
                categories=["software"],
                confidence=IntelligenceConfidence.MEDIUM,
            ),
            reputation=EmployerReputationSummary(
                kununu_manual_url="https://www.kununu.com/de/search?q=example",
                summary="No attributed review score was imported.",
                caveat="Verify review profiles manually.",
            ),
        ),
    )


def test_private_employer_rating_has_deterministic_material_score_effect() -> None:
    automatic = match_job(_profile(), _job(), evaluated_at=NOW)
    one_star = match_job(
        _profile(),
        _job(),
        employer_reputation_stars=1,
        evaluated_at=NOW,
    )
    five_stars = match_job(
        _profile(),
        _job(),
        employer_reputation_stars=5,
        evaluated_at=NOW,
    )
    zero_stars = match_job(
        _profile(),
        _job(),
        employer_reputation_stars=0,
        evaluated_at=NOW,
    )

    assert one_star.score == automatic.score - 16
    assert five_stars.score == automatic.score + 8
    assert zero_stars.score == 0
    assert zero_stars.disposition == MatchDisposition.STRETCH
    assert zero_stars.hard_violations == automatic.hard_violations
    assert zero_stars.employer_reputation is not None
    assert not zero_stars.employer_reputation.hard_blocker


def test_context_salary_and_work_mode_corrections_keep_automatic_evidence() -> None:
    job = _job()
    work_fact = JobFact(
        key="work_model.hybrid",
        value="hybrid",
        kind=JobFactKind.CONTEXT,
        evidence_quote="Hybrid work",
    )
    context = _context().model_copy(update={"work_mode_facts": [work_fact]})
    workspace_id = uuid4()
    overrides = [
        JobEvidenceOverride(
            workspace_id=workspace_id,
            job_record_id=job.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key=f"{CONTEXT_WORK_MODE_PREFIX}{work_fact.key}",
            target_label="Working-mode evidence",
            text_value="remote-first",
        ),
        JobEvidenceOverride(
            workspace_id=workspace_id,
            job_record_id=job.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key=CONTEXT_SALARY_RANGE,
            target_label="Salary orientation",
            text_value="60000:75000",
        ),
    ]

    result = match_job(
        _profile(),
        job,
        context=context,
        salary_guess=SalaryGuess(
            occupation_family="Software development",
            annual_min_eur=50_000,
            annual_max_eur=70_000,
            country_code="DE",
            region="Berlin",
            assumption="Broad local orientation.",
        ),
        job_overrides=overrides,
        evaluated_at=NOW,
    )

    assert result.derived_work_mode_facts[0].value == "hybrid"
    assert result.effective_work_mode_facts[0].value == "remote-first"
    assert result.automatic_salary_estimate is not None
    assert result.automatic_salary_estimate.annual_min_eur == 50_000
    assert result.salary_estimate is not None
    assert (result.salary_estimate.annual_min_eur, result.salary_estimate.annual_max_eur) == (
        60_000,
        75_000,
    )


def test_private_job_rating_is_distinct_and_unrated_is_neutral() -> None:
    automatic = match_job(_profile(), _job(), evaluated_at=NOW)
    one_star = match_job(_profile(), _job(), job_rating_stars=1, evaluated_at=NOW)
    five_stars = match_job(_profile(), _job(), job_rating_stars=5, evaluated_at=NOW)
    zero_stars = match_job(_profile(), _job(), job_rating_stars=0, evaluated_at=NOW)

    assert automatic.job_rating is None
    assert one_star.score == automatic.score - 12
    assert five_stars.score == automatic.score + 8
    assert zero_stars.score == 0
    assert zero_stars.disposition == MatchDisposition.STRETCH
    assert zero_stars.hard_violations == automatic.hard_violations
    assert zero_stars.job_rating is not None and not zero_stars.job_rating.hard_blocker


def test_remote_only_job_skips_routes_and_keeps_three_quarters_mobility_credit() -> None:
    mobility_fact = ProfileFact(
        key="commute.car.max_minutes",
        value="45 minutes by car one way",
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.LOCATION_MOBILITY,
            text="45 minutes by car one way",
        ),
    )
    remote_job = _job().model_copy(
        update={
            "location": "Remote – Europe",
            "source_text": "This is a fully remote software engineering role.",
            "facts": [
                JobFact(
                    key="work_model.remote",
                    value="fully remote",
                    kind=JobFactKind.OFFER,
                    evidence_quote="fully remote",
                )
            ],
        }
    )

    result = match_job(
        CandidateProfile(facts=[mobility_fact]),
        remote_job,
        evaluated_at=NOW,
    )

    assert result.remote_only_mobility
    assert not result.remote_only_excluded
    assert result.remote_mobility_points == 3
    assert result.commutes == []
    assert all(reason.profile_fact_id != mobility_fact.id for reason in result.reasons)


def test_remote_only_job_still_blocks_an_explicit_remote_exclusion() -> None:
    exclusion = ProfileFact(
        key="work_model.remote",
        value="remote work",
        level=RequirementLevel.EXCLUSION,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.LOCATION_MOBILITY,
            text="I exclude remote work",
        ),
    )
    remote_job = _job().model_copy(
        update={
            "location": "Remote",
            "source_text": "This role is fully remote.",
            "facts": [
                JobFact(
                    key="work_model.remote",
                    value="fully remote",
                    kind=JobFactKind.OFFER,
                    evidence_quote="fully remote",
                )
            ],
        }
    )

    result = match_job(
        CandidateProfile(facts=[exclusion]),
        remote_job,
        employer_reputation_stars=5,
        job_rating_stars=5,
        evaluated_at=NOW,
    )

    assert result.remote_only_mobility
    assert result.remote_only_excluded
    assert result.remote_mobility_points == 0
    assert result.disposition == MatchDisposition.BLOCKED
    assert any(reason.outcome.value == "violated" for reason in result.reasons)


def test_score_mechanics_report_actual_rules_and_positive_capacity_shares() -> None:
    result = match_job(
        _profile(),
        _job(),
        employer_reputation_stars=4,
        evaluated_at=NOW,
    )

    mechanics = result.score_mechanics
    assert mechanics is not None
    assert mechanics.final_points == result.score
    assert (
        round(
            sum(section.positive_capacity_share_percent for section in mechanics.sections),
            1,
        )
        == 100.0
    )
    reputation = next(
        section for section in mechanics.sections if section.key == "employer_reputation"
    )
    assert reputation.applied_points == 4
    assert not reputation.can_block
    assert "-16/-8/0/+4/+8" in reputation.mechanics


def test_generic_context_overrides_persist_and_preserve_automatic_evidence() -> None:
    container = ApplicationContainer(Settings(database_url="sqlite:///:memory:", auth_mode="local"))
    workspace = container.workspaces.create(new_session())
    job = _job()
    document = FetchedDocument(
        requested_url="https://careers.example/jobs/1",
        final_url="https://careers.example/jobs/1",
        status_code=200,
        content_type="text/html",
        text=job.source_text,
        fetched_at=NOW,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    overrides = [
        JobEvidenceOverride(
            workspace_id=workspace.id,
            job_record_id=record.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key=CONTEXT_EMPLOYER_RELATIONSHIP,
            target_label="Employer relationship",
            text_value=EmployerKind.RECRUITMENT_AGENCY.value,
        ),
        JobEvidenceOverride(
            workspace_id=workspace.id,
            job_record_id=record.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key=CONTEXT_COMPANY_REVENUE_MODEL,
            target_label="Company product profile",
            text_value="project consulting",
        ),
        JobEvidenceOverride(
            workspace_id=workspace.id,
            job_record_id=record.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key="future.machine.entry",
            target_label="Future machine entry",
            text_value="candidate-corrected value",
        ),
    ]
    for override in overrides:
        container.job_overrides.upsert(override)
    stored = container.job_overrides.list_for_job(workspace.id, record.id)

    result = match_job(
        _profile(),
        job,
        context=_context(),
        job_overrides=stored,
        evaluated_at=NOW,
    )

    assert result.employer_assessment.kind == EmployerKind.DIRECT_EMPLOYER
    assert result.effective_employer_assessment.kind == EmployerKind.RECRUITMENT_AGENCY
    assert result.company_intelligence.product.revenue_model == "software subscriptions"
    assert result.effective_company_intelligence.product.revenue_model == "project consulting"
    assert {item.target_key for item in result.context_evidence_corrections} == {
        CONTEXT_EMPLOYER_RELATIONSHIP,
        CONTEXT_COMPANY_REVENUE_MODEL,
        "future.machine.entry",
    }


def test_job_rating_repository_keeps_zero_distinct_from_clear_and_isolates_personas() -> None:
    container = ApplicationContainer(
        Settings(database_url="sqlite:///:memory:", auth_mode="accounts")
    )
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    other_persona = container.personas.create(account.id, "Other", maximum_personas=5)
    job = _job()
    document = FetchedDocument(
        requested_url="https://careers.example/jobs/rated",
        final_url="https://careers.example/jobs/rated",
        status_code=200,
        content_type="text/html",
        text=job.source_text,
        fetched_at=NOW,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)

    zero = container.job_ratings.set_rating(
        persona.id,
        record.id,
        0,
        account_id=account.id,
    )

    assert zero.stars == 0
    assert container.job_ratings.get(persona.id, record.id, account_id=account.id).stars == 0
    assert container.job_ratings.get(other_persona.id, record.id, account_id=account.id) is None
    assert container.job_ratings.clear(
        persona.id,
        record.id,
        account_id=account.id,
    )
    assert container.job_ratings.get(persona.id, record.id, account_id=account.id) is None


def test_j_migrations_form_one_linear_chain() -> None:
    script = ScriptDirectory.from_config(_migration_config("sqlite:///:memory:"))
    assert script.get_revision("0025_employer_reputation_scoring").down_revision == (
        "0024_posting_date_evidence"
    )
    assert script.get_revision("0027_context_evidence_overrides").down_revision == (
        "0026_application_guidance"
    )
    assert script.get_revision("0028_job_ratings").down_revision == (
        "0027_context_evidence_overrides"
    )
    assert script.get_revision("0029_job_detail_preferences").down_revision == ("0028_job_ratings")
    assert script.get_revision("0030_verified_job_posters").down_revision == (
        "0029_job_detail_preferences"
    )
    assert script.get_revision("0031_private_alpha_roles_feedback").down_revision == (
        "0030_verified_job_posters"
    )
    assert script.get_revision("0032_explore_import_origin").down_revision == (
        "0031_private_alpha_roles_feedback"
    )
    assert script.get_revision("0033_background_task_leases").down_revision == (
        "0032_explore_import_origin"
    )
