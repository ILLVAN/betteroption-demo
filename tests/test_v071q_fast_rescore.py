from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from betteroption.accounts import RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    ReasonOverrideValue,
)
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.match_evidence import (
    SemanticFitOutcome,
    SemanticMatchAssessment,
    job_fact_fingerprint,
)
from betteroption.matching import MatchDisposition, MatchOutcome
from betteroption.operations import ProviderOperationSummary
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.result_repository import ConcurrentResultUpdateError
from betteroption.results import ResultService
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument


# These tests exercise stored-evidence rescoring, not expiry. Keep their source
# observations inside the production 24-hour presentation window regardless of
# the calendar date on which the regression suite is run.
NOW = datetime.now(timezone.utc).replace(microsecond=0)
PASSWORD = "correct horse battery staple"


def _container(tmp_path: Path, *, auth_mode: str = "local") -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / f'q-{auth_mode}.db').as_posix()}",
            auth_mode=auth_mode,
            registration_mode="open",
            employer_homepage_research=False,
            transitous_enabled=False,
            valhalla_enabled=False,
            osm_geocoder_enabled=False,
        )
    )


def _fact(
    key: str,
    value: str,
    level: RequirementLevel,
    *,
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


def _workspace(
    container: ApplicationContainer,
    *,
    account_id: UUID | None = None,
    persona_id: UUID | None = None,
):
    session = new_session()
    session.profile.facts = [
        _fact("work_model.remote", "hybrid", RequirementLevel.MUST_HAVE),
        _fact(
            "compensation.minimum",
            "EUR 60,000 gross/year",
            RequirementLevel.MUST_HAVE,
            section=ProfileSection.COMPENSATION_TIME,
        ),
        _fact(
            "skill.demonstrated",
            "Python",
            RequirementLevel.OPEN,
            section=ProfileSection.EXPERIENCE,
        ),
    ]
    return container.workspaces.create(
        session,
        account_id=account_id,
        persona_id=persona_id,
    )


def _job(container: ApplicationContainer, slug: str, *, company: str = "Example GmbH"):
    url = f"https://careers.example.com/jobs/{slug}"
    source = f"{company} seeks a {slug} specialist. Hybrid work is available. Python is required."
    job = JobPosting(
        title=f"{slug.title()} Specialist",
        company=company,
        location="Berlin",
        summary="Build useful products in a hybrid team.",
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
                key="work_model.remote",
                value="hybrid",
                kind=JobFactKind.OFFER,
                evidence_quote="Hybrid work is available",
            ),
            JobFact(
                key="skill.name",
                value="Python",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Python is required",
            ),
        ],
    )
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return record, job


def _service(container: ApplicationContainer, **dependencies) -> ResultService:
    return ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        job_overrides=container.job_overrides,
        employer_reputation=container.employer_reputation,
        job_ratings=container.job_ratings,
        **dependencies,
    )


class _ProviderMustNotRun:
    def __getattr__(self, name: str):
        raise AssertionError(f"fast re-score touched provider/research dependency: {name}")


class _OnsiteContext:
    def __init__(self) -> None:
        self.fact = JobFact(
            key="work_model.onsite",
            value="on-site",
            kind=JobFactKind.CONTEXT,
            evidence_quote="Hybrid work is available",
        )

    def assess(self, job: JobPosting) -> JobContext:
        del job
        return JobContext(
            employer=EmployerAssessment(
                kind=EmployerKind.UNKNOWN,
                confidence=ContextConfidence.LOW,
                explanation="The employer relationship is not established.",
            ),
            work_mode_facts=[self.fact],
        )


class _CountingContext:
    def __init__(self) -> None:
        self.calls = 0

    def assess(self, job: JobPosting) -> JobContext:
        del job
        self.calls += 1
        return JobContext(
            employer=EmployerAssessment(
                kind=EmployerKind.UNKNOWN,
                confidence=ContextConfidence.LOW,
                explanation="The employer relationship is not established.",
            )
        )


class _UnpricedOperationLedger:
    def summary_since(self, *, workflow_id: UUID) -> ProviderOperationSummary:
        del workflow_id
        return ProviderOperationSummary(
            total_operations=1,
            result_count=1,
            unpriced_operations=1,
        )


class _SemanticResolver:
    model = "test"

    def __init__(self, evidence: JobFact) -> None:
        self.evidence = evidence
        self.calls = 0

    def assess(self, *, profile_facts_by_job_id, jobs):
        self.calls += 1
        job = jobs[0]
        criterion = next(
            fact
            for fact in profile_facts_by_job_id[job.id]
            if fact.key == "work_model.office_days_max"
        )
        return {
            job.id: [
                SemanticMatchAssessment(
                    job_id=job.id,
                    profile_fact_id=criterion.id,
                    outcome=SemanticFitOutcome.VIOLATED,
                    confidence=ContextConfidence.MEDIUM,
                    evidence_job_fact_ids=[self.evidence.id],
                    evidence_fact_fingerprints={
                        self.evidence.id: job_fact_fingerprint(self.evidence)
                    },
                    explanation="The on-site arrangement conflicts with the office-day limit.",
                )
            ]
        }


def _result_for(container: ApplicationContainer, workspace_id: UUID, record_id: UUID):
    run = container.results.latest_run(workspace_id)
    assert run is not None
    return run, next(row for row in run.results if row.job_record_id == record_id)


def test_fast_rescore_updates_one_row_atomically_without_provider_calls(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    target, _ = _job(container, "target")
    untouched, _ = _job(container, "untouched")
    _service(container).run(workspace)
    run_before, target_before = _result_for(container, workspace.id, target.id)
    untouched_before = next(row for row in run_before.results if row.job_record_id == untouched.id)
    reason = next(
        row for row in target_before.result.reasons if row.profile_key == "work_model.remote"
    )
    old_lineage = (
        target_before.result.profile_fingerprint,
        target_before.result.source_evidence_fingerprint,
        target_before.result.user_evidence_fingerprint,
    )
    container.job_overrides.upsert(
        JobEvidenceOverride(
            workspace_id=workspace.id,
            job_record_id=target.id,
            kind=JobEvidenceOverrideKind.REASON,
            target_key=str(reason.profile_fact_id),
            target_label=reason.profile_value,
            reason_value=ReasonOverrideValue.VIOLATED,
        )
    )

    rescored = _service(
        container,
        mobility=_ProviderMustNotRun(),
        employer_context=_ProviderMustNotRun(),
        salary_benchmark=_ProviderMustNotRun(),
        operation_ledger=_ProviderMustNotRun(),
    ).rescore_from_stored_evidence(workspace, target.id)

    run_after, target_after = _result_for(container, workspace.id, target.id)
    untouched_after = next(row for row in run_after.results if row.job_record_id == untouched.id)
    assert run_after.id == run_before.id
    assert container.results.count_runs(workspace.id) == 1
    assert untouched_after.result.model_dump_json() == untouched_before.result.model_dump_json()
    assert untouched_after.job.model_dump_json() == untouched_before.job.model_dump_json()
    assert rescored.score < target_before.result.score
    assert rescored.disposition == MatchDisposition.BLOCKED
    assert (
        next(
            row for row in rescored.reasons if row.profile_fact_id == reason.profile_fact_id
        ).outcome
        == MatchOutcome.VIOLATED
    )
    assert (
        target_after.result.profile_fingerprint,
        target_after.result.source_evidence_fingerprint,
        target_after.result.user_evidence_fingerprint,
    ) == old_lineage
    assert run_after.metrics is not None
    assert run_after.metrics.top_count == sum(
        row.result.disposition == MatchDisposition.TOP for row in run_after.results
    )
    assert run_after.metrics.stretch_count == sum(
        row.result.disposition == MatchDisposition.STRETCH for row in run_after.results
    )
    status = _service(container).full_rematch_status(workspace, target.id)
    assert status.allowed
    assert "private evidence" in status.reason


def test_fast_rescore_reuses_saved_semantic_assessment_without_provider_call(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    workspace.session.profile.facts.append(
        _fact(
            "work_model.office_days_max",
            "At most 2 office days",
            RequirementLevel.MUST_HAVE,
            section=ProfileSection.WORKING_MODEL,
        )
    )
    container.workspaces.save(workspace)
    record, _ = _job(container, "semantic")
    context = _OnsiteContext()
    resolver = _SemanticResolver(context.fact)

    first = _service(
        container,
        employer_context=context,
        match_evidence_resolver=resolver,
    ).run(workspace)
    assert resolver.calls == 1
    assert first.blocked[0].stored.result.semantic_assessments

    rescored = _service(
        container,
        match_evidence_resolver=_ProviderMustNotRun(),
    ).rescore_from_stored_evidence(workspace, record.id)

    assert rescored.disposition == MatchDisposition.BLOCKED
    assert rescored.semantic_assessments == first.blocked[0].stored.result.semantic_assessments


def test_employer_quickscore_updates_every_matching_company_without_provider_calls(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    first, _ = _job(container, "first", company="Example Products GmbH")
    second, _ = _job(container, "second", company="Example Products G.m.b.H.")
    unrelated, _ = _job(container, "unrelated", company="Other Machines AG")
    _service(container).run(workspace)
    run_before, first_before = _result_for(container, workspace.id, first.id)
    second_before = next(row for row in run_before.results if row.job_record_id == second.id)
    unrelated_before = next(row for row in run_before.results if row.job_record_id == unrelated.id)
    container.employer_reputation.set_rating(
        persona.id,
        "Example Products GmbH",
        5,
        account_id=account.id,
    )

    rescored = _service(
        container,
        mobility=_ProviderMustNotRun(),
        employer_context=_ProviderMustNotRun(),
        salary_benchmark=_ProviderMustNotRun(),
        operation_ledger=_ProviderMustNotRun(),
    ).rescore_employer_from_stored_evidence(workspace, "EXAMPLE PRODUCTS G.m.b.H.")

    assert set(rescored) == {first.id, second.id}
    assert rescored[first.id].score == first_before.result.score + 8
    assert rescored[second.id].score == second_before.result.score + 8
    run_after, _ = _result_for(container, workspace.id, first.id)
    unrelated_after = next(row for row in run_after.results if row.job_record_id == unrelated.id)
    assert unrelated_after.result.model_dump_json() == unrelated_before.result.model_dump_json()


def test_explicit_salary_override_and_zero_rating_rescore_without_research(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    record, _ = _job(container, "rated")
    _service(container).run(workspace)
    _run, before = _result_for(container, workspace.id, record.id)
    salary_reason = next(
        reason for reason in before.result.reasons if reason.profile_key == "compensation.minimum"
    )
    assert salary_reason.outcome == MatchOutcome.UNKNOWN
    container.job_overrides.upsert(
        JobEvidenceOverride(
            workspace_id=workspace.id,
            job_record_id=record.id,
            kind=JobEvidenceOverrideKind.CONTEXT,
            target_key="salary.orientation.annual_range_eur",
            target_label="Expected salary orientation",
            text_value="65000:75000",
        )
    )
    no_provider_service = _service(
        container,
        mobility=_ProviderMustNotRun(),
        employer_context=_ProviderMustNotRun(),
        salary_benchmark=_ProviderMustNotRun(),
        operation_ledger=_ProviderMustNotRun(),
    )
    salary_rescore = no_provider_service.rescore_from_stored_evidence(
        workspace,
        record.id,
    )
    assert next(
        reason for reason in salary_rescore.reasons if reason.profile_key == "compensation.minimum"
    ).outcome in {MatchOutcome.SATISFIED, MatchOutcome.SUPPORTING}

    container.job_ratings.set_rating(
        persona.id,
        record.id,
        0,
        account_id=account.id,
    )
    zero_rated = no_provider_service.rescore_from_stored_evidence(workspace, record.id)
    assert zero_rated.score == 0
    assert zero_rated.disposition == MatchDisposition.STRETCH
    assert zero_rated.job_rating is not None and not zero_rated.job_rating.hard_blocker

    container.job_ratings.clear(persona.id, record.id, account_id=account.id)
    restored = no_provider_service.rescore_from_stored_evidence(workspace, record.id)
    assert restored.disposition != MatchDisposition.BLOCKED
    assert restored.job_rating is None


def test_pure_job_and_employer_ratings_update_lineage_without_opening_full_rematch(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "rating-lineage@example.com",
        "Rating Lineage",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    record, _ = _job(container, "rating-lineage", company="Lineage Products GmbH")
    _service(container).run(workspace)
    result_service = _service(
        container,
        mobility=_ProviderMustNotRun(),
        employer_context=_ProviderMustNotRun(),
        salary_benchmark=_ProviderMustNotRun(),
        operation_ledger=_ProviderMustNotRun(),
    )
    _run, initial = _result_for(container, workspace.id, record.id)
    evidence_lineage = initial.result.user_evidence_fingerprint
    initial_rating_lineage = initial.result.rating_fingerprint
    assert not result_service.full_rematch_status(workspace, record.id).allowed

    container.employer_reputation.set_rating(
        persona.id,
        "Lineage Products GmbH",
        5,
        account_id=account.id,
    )
    assert not result_service.full_rematch_status(workspace, record.id).allowed
    employer_projection = result_service.rescore_employer_from_stored_evidence(
        workspace,
        "Lineage Products GmbH",
    )[record.id]
    assert employer_projection.rating_fingerprint != initial_rating_lineage
    assert employer_projection.user_evidence_fingerprint == evidence_lineage
    assert not result_service.full_rematch_status(workspace, record.id).allowed

    container.job_ratings.set_rating(
        persona.id,
        record.id,
        0,
        account_id=account.id,
    )
    assert not result_service.full_rematch_status(workspace, record.id).allowed
    job_projection = result_service.rescore_from_stored_evidence(workspace, record.id)
    assert job_projection.score == 0
    assert job_projection.disposition == MatchDisposition.STRETCH
    assert job_projection.user_evidence_fingerprint == evidence_lineage
    assert job_projection.rating_fingerprint != employer_projection.rating_fingerprint
    assert not result_service.full_rematch_status(workspace, record.id).allowed


def test_quickscore_retries_one_compare_and_swap_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "rating-cas@example.com",
        "Rating CAS",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    record, _ = _job(container, "rating-cas")
    result_service = _service(container)
    result_service.run(workspace)
    container.job_ratings.set_rating(persona.id, record.id, 4, account_id=account.id)

    original = container.results.replace_result_atomically
    attempts = 0

    def conflict_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConcurrentResultUpdateError("simulated stale projection")
        return original(*args, **kwargs)

    monkeypatch.setattr(container.results, "replace_result_atomically", conflict_once)

    rescored = result_service.rescore_from_stored_evidence(workspace, record.id)

    assert attempts == 2
    assert rescored.job_rating is not None and rescored.job_rating.stars == 4


def test_full_match_reconciles_a_rating_saved_after_its_initial_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "rating-full-race@example.com",
        "Rating Full Race",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    record, _ = _job(container, "rating-full-race")
    original = container.results.save_run

    def save_after_rating(*args, **kwargs):
        container.job_ratings.set_rating(
            persona.id,
            record.id,
            0,
            account_id=account.id,
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(container.results, "save_run", save_after_rating)

    groups = _service(container).run(workspace)

    item = next(
        item
        for item in [*groups.top, *groups.stretch, *groups.blocked]
        if item.record.id == record.id
    )
    assert item.stored.result.score == 0
    assert item.stored.result.disposition == MatchDisposition.STRETCH
    assert item.stored.result.job_rating is not None
    assert item.stored.result.job_rating.stars == 0
    assert not _service(container).full_rematch_status(workspace, record.id).allowed


def test_existing_workflow_resumes_after_grant_failure_without_provider_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    _job(container, "resume-grant")
    context = _CountingContext()
    result_service = _service(container, employer_context=context)
    workflow_id = uuid4()
    original = container.results.grant_initial_results
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated grant failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(container.results, "grant_initial_results", fail_once)

    with pytest.raises(RuntimeError, match="simulated grant failure"):
        result_service.run(workspace, workflow_id=workflow_id)

    partial = container.results.get_run(workflow_id)
    assert partial is not None and partial.metrics is None
    assert context.calls == 1

    recovered = result_service.run(workspace, workflow_id=workflow_id)

    assert recovered.run.metrics is not None
    assert recovered.granted_count == 1
    assert attempts == 2
    assert context.calls == 1
    assert container.results.count_runs(workspace.id) == 1


def test_existing_workflow_resumes_after_metrics_failure_without_provider_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    _job(container, "resume-metrics")
    context = _CountingContext()
    result_service = _service(
        container,
        employer_context=context,
        operation_ledger=_UnpricedOperationLedger(),
    )
    workflow_id = uuid4()
    original = container.results.save_run_metrics
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated metrics failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(container.results, "save_run_metrics", fail_once)

    with pytest.raises(RuntimeError, match="simulated metrics failure"):
        result_service.run(workspace, workflow_id=workflow_id)

    partial = container.results.get_run(workflow_id)
    assert partial is not None and partial.metrics is None
    assert len(container.results.access_grants(workspace.id)) == 1
    assert context.calls == 1

    recovered = result_service.run(workspace, workflow_id=workflow_id)

    assert recovered.run.metrics is not None
    assert recovered.run.metrics.included_slots == 1
    assert recovered.run.metrics.provider_unpriced_operations == 1
    assert attempts == 2
    assert context.calls == 1
    assert container.results.count_runs(workspace.id) == 1


def test_existing_workflow_resumes_failed_rating_reconcile_without_provider_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path, auth_mode="accounts")
    account = container.accounts.create(
        "rating-resume@example.com",
        "Rating Resume",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    workspace = _workspace(
        container,
        account_id=account.id,
        persona_id=persona.id,
    )
    record, _ = _job(container, "rating-resume")
    context = _CountingContext()
    result_service = _service(container, employer_context=context)
    workflow_id = uuid4()
    original = result_service._reconcile_saved_run_ratings
    attempts = 0

    def fail_once(saved_workspace, stored):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            container.job_ratings.set_rating(
                persona.id,
                record.id,
                0,
                account_id=account.id,
            )
            raise RuntimeError("simulated reconcile failure")
        return original(saved_workspace, stored)

    monkeypatch.setattr(result_service, "_reconcile_saved_run_ratings", fail_once)

    with pytest.raises(RuntimeError, match="simulated reconcile failure"):
        result_service.run(workspace, workflow_id=workflow_id)

    partial = container.results.get_run(workflow_id)
    assert partial is not None and partial.metrics is None
    assert partial.results[0].result.job_rating is None
    assert context.calls == 1

    recovered = result_service.run(workspace, workflow_id=workflow_id)
    item = next(
        item
        for item in [*recovered.top, *recovered.stretch, *recovered.blocked]
        if item.record.id == record.id
    )

    assert item.stored.result.score == 0
    assert item.stored.result.disposition == MatchDisposition.STRETCH
    assert item.stored.result.job_rating is not None
    assert item.stored.result.job_rating.stars == 0
    assert recovered.run.metrics is not None
    assert attempts == 2
    assert context.calls == 1
    assert container.results.count_runs(workspace.id) == 1


def test_fast_rescore_keeps_other_workspace_private_evidence_isolated(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    first = _workspace(container)
    second = _workspace(container)
    record, _ = _job(container, "shared-source")
    _service(container).run(first)
    _service(container).run(second)
    _second_run, second_before = _result_for(container, second.id, record.id)
    _first_run, first_before = _result_for(container, first.id, record.id)
    reason = next(
        row for row in first_before.result.reasons if row.profile_key == "work_model.remote"
    )
    container.job_overrides.upsert(
        JobEvidenceOverride(
            workspace_id=first.id,
            job_record_id=record.id,
            kind=JobEvidenceOverrideKind.REASON,
            target_key=str(reason.profile_fact_id),
            target_label=reason.profile_value,
            reason_value=ReasonOverrideValue.VIOLATED,
        )
    )
    _service(container).rescore_from_stored_evidence(first, record.id)

    _second_run_after, second_after = _result_for(container, second.id, record.id)
    assert second_after.result.model_dump_json() == second_before.result.model_dump_json()
    assert container.job_overrides.list_for_job(second.id, record.id) == []


def test_full_rematch_gate_tracks_full_refresh_lineage_not_fast_rescore_time(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    record, _ = _job(container, "lineage")
    result_service = _service(container)
    result_service.run(workspace)
    assert not result_service.full_rematch_status(workspace, record.id).allowed

    _run, before = _result_for(container, workspace.id, record.id)
    legacy = before.result.model_copy(
        update={
            "profile_fingerprint": None,
            "source_evidence_fingerprint": None,
            "user_evidence_fingerprint": None,
        }
    )
    container.results.replace_result_atomically(
        workspace.id,
        _run.id,
        record.id,
        legacy,
        before.job,
    )
    legacy_status = result_service.full_rematch_status(workspace, record.id)
    assert legacy_status.allowed
    assert "legacy" in legacy_status.reason.casefold()

    # One real full refresh records lineage and closes the gate again.
    result_service.run(workspace, record_ids={record.id})
    assert not result_service.full_rematch_status(workspace, record.id).allowed
    workspace.session.profile.facts.append(
        _fact("culture.preference", "calm team", RequirementLevel.PREFERENCE)
    )
    container.workspaces.save(workspace)
    compass_status = result_service.full_rematch_status(workspace, record.id)
    assert compass_status.allowed
    assert "Compass" in compass_status.reason
