"""Application service and view models for evidence-backed match results."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, wait
from contextvars import copy_context
from datetime import datetime, timezone
from enum import StrEnum
from time import perf_counter
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy.exc import OperationalError

from .access import ProductAccessPolicy
from .concurrency import DaemonThreadPoolExecutor
from .employer_reputation import (
    EmployerReputationRepository,
    normalize_employer_name,
    resolved_employer_name,
)
from .job_corpus import JobCorpusService
from .job_context import EmployerContextService, JobContext
from .job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    JobEvidenceOverrideRepository,
)
from .job_ratings import PersonaJobRatingRepository
from .job_repository import JobAvailability, JobRecord, JobRepository
from .matching import (
    CONTEXT_COMPANY_NAME,
    CONTEXT_REPUTATION_SUMMARY,
    MatchDisposition,
    MatchOutcome,
    MatchReason,
    MatchResult,
    MatchRun,
    job_source_evidence_fingerprint,
    legacy_user_evidence_fingerprint,
    match_job,
    match_jobs,
    profile_evidence_fingerprint,
    rating_input_fingerprint,
    user_evidence_fingerprint,
)
from .match_evidence import MatchEvidenceResolverPort
from .mobility import CommuteAssessment, MobilityService, routing_destinations_from_job
from .operations import ProviderOperationLedger, provider_operation_scope
from .presentation import format_job_location, job_is_remote_only
from .profile import StrictModel
from .profile_repository import ProfileWorkspace
from .salary import (
    SalaryBenchmarkProvider,
    SalaryEvidence,
    SalaryGuess,
    SalaryResearchResult,
    jobs_missing_advertised_salary,
)
from .result_repository import (
    ConcurrentResultUpdateError,
    JobInteraction,
    JobInteractionEvent,
    ResultRepository,
    MatchRunMetrics,
    StoredMatchResult,
    StoredMatchRun,
)


DISPOSITION_LABELS = {
    MatchDisposition.TOP: "Top match",
    MatchDisposition.STRETCH: "Stretch match",
    MatchDisposition.BLOCKED: "Blocked by a boundary",
}

CURRENT_MATCHING_ALGORITHM = "matching-v0.7.2i"
LOCAL_PROJECTION_MAX_ATTEMPTS = 3


def _retryable_projection_write_error(exc: OperationalError) -> bool:
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "could not serialize",
            "deadlock detected",
        )
    )


class ResultServiceError(RuntimeError):
    """Raised when a result run cannot be created or presented safely."""


class ResultAccessError(PermissionError):
    """Raised when a recommendation is outside the free result allowance."""


class FullRematchStatus(StrictModel):
    """Whether an expensive provider-backed refresh has a legitimate input change."""

    allowed: bool
    reason: str
    requires_complete_match: bool = False


class RatingProjectionState(StrEnum):
    """Outcome of applying a saved rating to the latest persisted ranking."""

    UPDATED = "updated"
    NO_LATEST_MATCH = "no_latest_match"
    OLD_ALGORITHM = "old_algorithm"
    JOB_MISSING = "job_missing"
    FAILED = "failed"


class RatingProjection(StrictModel):
    """Typed, provider-free result of one rating projection attempt."""

    status: RatingProjectionState
    warning: str | None = None
    results: dict[UUID, MatchResult] = Field(default_factory=dict)

    @classmethod
    def no_latest_match(cls) -> RatingProjection:
        return cls(
            status=RatingProjectionState.NO_LATEST_MATCH,
            warning="No Match ranking exists yet. Run Matching to include this rating.",
        )

    @classmethod
    def old_algorithm(cls) -> RatingProjection:
        return cls(
            status=RatingProjectionState.OLD_ALGORITHM,
            warning=(
                "The latest Match uses an older scoring algorithm. "
                "Run complete Matching to include this rating."
            ),
        )

    @classmethod
    def job_missing(cls) -> RatingProjection:
        return cls(
            status=RatingProjectionState.JOB_MISSING,
            warning=(
                "This job is not part of the latest Match. "
                "Run complete Matching to include this rating."
            ),
        )

    @classmethod
    def failed(cls) -> RatingProjection:
        return cls(
            status=RatingProjectionState.FAILED,
            warning=(
                "The rating was saved, but the current Match ranking could not be updated. "
                "Refresh and try again."
            ),
        )


class ResultItem(StrictModel):
    stored: StoredMatchResult
    record: JobRecord
    accessible: bool
    source_is_current: bool
    interaction: JobInteraction | None = None

    @property
    def disposition_label(self) -> str:
        return DISPOSITION_LABELS[self.stored.result.disposition]

    @property
    def display_location(self) -> str:
        return format_job_location(self.stored.job)

    @property
    def remote_only(self) -> bool:
        return job_is_remote_only(self.stored.job)

    @property
    def unknowns(self) -> list[MatchReason]:
        return [
            reason
            for reason in self.stored.result.reasons
            if reason.outcome == MatchOutcome.UNKNOWN
        ]

    @property
    def strengths(self) -> list[MatchReason]:
        return [
            reason
            for reason in self.stored.result.reasons
            if reason.outcome in {MatchOutcome.SATISFIED, MatchOutcome.SUPPORTING}
        ]

    @property
    def conflicts(self) -> list[MatchReason]:
        return [
            reason
            for reason in self.stored.result.reasons
            if reason.outcome == MatchOutcome.VIOLATED
        ]

    @property
    def why_still_apply(self) -> str | None:
        if self.stored.result.disposition != MatchDisposition.STRETCH:
            return None
        job = self.stored.job
        commute_fact_ids = {
            assessment.profile_fact_id for assessment in self.stored.result.commutes
        }
        job_evidence_strengths = [
            reason
            for reason in self.strengths
            if reason.profile_fact_id not in commute_fact_ids and reason.evidence_quotes
        ]
        strengths = [_short(reason.profile_value) for reason in job_evidence_strengths[:2]]
        if not strengths and self.stored.result.matched_required_skills:
            strengths = [
                f"your evidenced {skill} experience"
                for skill in self.stored.result.matched_required_skills[:2]
            ]
        if not strengths:
            strengths = [
                _short(reason.profile_value)
                for reason in self.strengths
                if reason.profile_fact_id in commute_fact_ids
            ][:1]
        strongest_case = _join_phrases(strengths) or "the role's advertised technical work"
        if self.conflicts:
            boundary = _short(self.conflicts[0].profile_value)
            return (
                f"{job.company}'s {job.title} role still has a concrete fit through "
                f"{strongest_case}. It conflicts with your “{boundary}” boundary, so apply "
                "only if that specific boundary is negotiable—and raise it before investing "
                "in a tailored application."
            )
        unknowns = [
            _short(reason.profile_value)
            for reason in self.unknowns
            if reason.profile_fact_id not in commute_fact_ids
        ][:2]
        if unknowns:
            return (
                f"The strongest case for {job.company}'s {job.title} role is "
                f"{strongest_case}. The advertisement is still silent on "
                f"{_join_phrases(unknowns)}; ask about those points in the first conversation "
                "before investing in a tailored application."
            )
        return (
            f"{job.company}'s {job.title} role is a Stretch rather than a Top match, but "
            f"{strongest_case} gives you a specific application angle. Lead with that evidence "
            "and verify the remaining role details in the first conversation."
        )


def _short(value: str, limit: int = 90) -> str:
    clean = " ".join(value.split()).strip(" .")
    return clean if len(clean) <= limit else f"{clean[: limit - 1].rstrip()}…"


def _join_phrases(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"


class ResultGroups(StrictModel):
    run: StoredMatchRun
    top: list[ResultItem] = Field(default_factory=list)
    stretch: list[ResultItem] = Field(default_factory=list)
    blocked: list[ResultItem] = Field(default_factory=list)
    free_limit: int
    granted_count: int
    profile_is_current: bool
    algorithm_is_current: bool

    @property
    def locked_count(self) -> int:
        return sum(not item.accessible for item in [*self.top, *self.stretch])

    @property
    def has_partial_job_refresh(self) -> bool:
        """Expose a mixed-age result set created by a single-job rematch."""

        return bool(self.run.metrics and self.run.metrics.jobs_evaluated < len(self.run.results))


class ResultDetail(StrictModel):
    groups: ResultGroups
    item: ResultItem
    events: list[JobInteractionEvent] = Field(default_factory=list)


class ResultService:
    def __init__(
        self,
        jobs: JobRepository,
        corpus: JobCorpusService,
        results: ResultRepository,
        policy: ProductAccessPolicy,
        mobility: MobilityService | None = None,
        employer_context: EmployerContextService | None = None,
        operation_ledger: ProviderOperationLedger | None = None,
        salary_benchmark: SalaryBenchmarkProvider | None = None,
        salary_research_max_jobs: int = 10,
        job_overrides: JobEvidenceOverrideRepository | None = None,
        employer_reputation: EmployerReputationRepository | None = None,
        job_ratings: PersonaJobRatingRepository | None = None,
        match_evidence_resolver: MatchEvidenceResolverPort | None = None,
        restrict_to_grants: bool = False,
    ) -> None:
        self.jobs = jobs
        self.corpus = corpus
        self.results = results
        self.policy = policy
        self.mobility = mobility
        self.employer_context = employer_context
        self.operation_ledger = operation_ledger
        self.salary_benchmark = salary_benchmark
        self.salary_research_max_jobs = min(25, max(1, salary_research_max_jobs))
        self.job_overrides = job_overrides
        self.employer_reputation = employer_reputation
        self.job_ratings = job_ratings
        self.match_evidence_resolver = match_evidence_resolver
        self.restrict_to_grants = restrict_to_grants

    def run(
        self,
        workspace: ProfileWorkspace,
        *,
        workflow_id: UUID | None = None,
        progress: Callable[[str, int, int, str], None] | None = None,
        record_ids: set[UUID] | None = None,
        task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> ResultGroups:
        workflow_id = workflow_id or uuid4()

        def report(phase: str, completed: int, total: int, message: str) -> None:
            if progress is not None:
                progress(phase, completed, total, message)

        def checkpoint() -> None:
            control = getattr(progress, "checkpoint", None)
            if callable(control):
                control()

        existing = self.results.get_run(workflow_id)
        if existing is not None:
            if existing.workspace_id != workspace.id:
                raise ResultServiceError("The workflow id belongs to another Compass.")
            report(
                "saving",
                0,
                1,
                "Finishing the recovered match run without repeating provider work.",
            )
            existing = self._finalize_saved_run(
                workspace,
                existing,
                workflow_id=workflow_id,
            )
            report("complete", 1, 1, "The existing completed match run was recovered.")
            return self._present(workspace, existing)

        started = perf_counter()
        report("preflight", 0, 1, "Checking your Compass and verified jobs.")
        if not workspace.session.profile.confirmed_facts:
            raise ResultServiceError(
                "Confirm at least one compass statement before creating matches."
            )
        jobs = self.corpus.jobs_ready_for_presentation()
        if not jobs:
            raise ResultServiceError(
                "Add at least one open, successfully extracted opportunity before matching."
            )
        allowed_record_ids = (
            {grant.job_record_id for grant in self.results.access_grants(workspace.id)}
            if self.restrict_to_grants
            else None
        )
        records_by_job_id: dict[UUID, JobRecord] = {}
        jobs_by_id = {job.id: job for job in jobs}
        for job in jobs:
            # Current revision identity is authoritative, including manual
            # pasted jobs that intentionally have no external source URL.  The
            # URL fallback retains compatibility with injected corpus adapters
            # that return an equivalent posting instance.
            record = self.jobs.find_current_by_posting_id(job.id)
            if record is None:
                record = self.jobs.find_by_urls(
                    str(job.source_url or ""), str(job.requested_url or "")
                )
            if (
                record is not None
                and record.availability == JobAvailability.LIVE
                and (allowed_record_ids is None or record.id in allowed_record_ids)
            ):
                records_by_job_id[job.id] = record
        eligible_jobs = [job for job in jobs if job.id in records_by_job_id]
        if not eligible_jobs:
            raise ResultServiceError("No currently verified job page is ready for matching.")
        previous = self.results.latest_run(workspace.id) if record_ids else None
        can_reuse_previous = bool(
            previous and previous.algorithm_version == CURRENT_MATCHING_ALGORITHM
        )
        if record_ids and previous is not None and not can_reuse_previous:
            raise ResultServiceError(
                "The saved Match uses an older algorithm. Run complete Match before fully "
                "refreshing only one job."
            )
        jobs_to_evaluate = (
            [job for job in eligible_jobs if records_by_job_id[job.id].id in record_ids]
            if record_ids
            else eligible_jobs
        )
        if not jobs_to_evaluate:
            raise ResultServiceError("None of the selected live jobs is ready for matching.")
        route_jobs = [job for job in jobs_to_evaluate if not job_is_remote_only(job)][
            : self.policy.exact_route_match_limit
        ]
        salary_research_jobs = (
            jobs_missing_advertised_salary(
                workspace.session.profile,
                jobs_to_evaluate,
                limit=self.salary_research_max_jobs,
                require_profile_criterion=False,
            )
            if self.salary_benchmark is not None
            else []
        )
        total_units = (
            len(route_jobs) + len(jobs_to_evaluate) + 3 + (1 if salary_research_jobs else 0)
        )
        completed_units = 1
        report(
            "preflight",
            completed_units,
            total_units,
            f"{len(jobs_to_evaluate)} verified jobs are ready for evidence checks.",
        )
        commutes_by_job_id: dict[UUID, list[CommuteAssessment]] = {}
        contexts_by_job_id: dict[UUID, JobContext] = {}
        salary_evidence_by_job_id: dict[UUID, list[SalaryEvidence]] = {}
        salary_guesses_by_job_id: dict[UUID, SalaryGuess] = {}
        job_overrides_by_job_id: dict[UUID, list[JobEvidenceOverride]] = {}
        employer_reputation_by_job_id: dict[UUID, int] = {}
        job_ratings_by_job_id: dict[UUID, int] = {}
        if self.job_overrides is not None:
            overrides_by_record_id = self.job_overrides.list_for_jobs(
                workspace.id,
                {records_by_job_id[job.id].id for job in eligible_jobs},
            )
            job_overrides_by_job_id = {
                job.id: overrides_by_record_id.get(records_by_job_id[job.id].id, [])
                for job in jobs_to_evaluate
            }
            employer_keys_by_job_id: dict[UUID, str] = {}
            shared_context_by_employer: dict[str, JobEvidenceOverride] = {}
            for job in eligible_jobs:
                overrides = overrides_by_record_id.get(records_by_job_id[job.id].id, [])
                corrected_name = next(
                    (
                        item.text_value
                        for item in overrides
                        if item.kind == JobEvidenceOverrideKind.CONTEXT
                        and item.target_key == CONTEXT_COMPANY_NAME
                        and item.text_value
                    ),
                    job.company,
                )
                resolved_name = resolved_employer_name(corrected_name)
                if resolved_name is None:
                    continue
                try:
                    _, employer_key = normalize_employer_name(resolved_name)
                except ValueError:
                    continue
                employer_keys_by_job_id[job.id] = employer_key
                private_context = max(
                    (
                        item
                        for item in overrides
                        if item.kind == JobEvidenceOverrideKind.CONTEXT
                        and item.target_key == CONTEXT_REPUTATION_SUMMARY
                        and item.text_value
                    ),
                    key=lambda item: item.updated_at,
                    default=None,
                )
                current = shared_context_by_employer.get(employer_key)
                if private_context is not None and (
                    current is None or private_context.updated_at > current.updated_at
                ):
                    shared_context_by_employer[employer_key] = private_context
            for job in jobs_to_evaluate:
                employer_key = employer_keys_by_job_id.get(job.id)
                shared_context = (
                    shared_context_by_employer.get(employer_key) if employer_key else None
                )
                if shared_context is None:
                    continue
                own = [
                    item
                    for item in job_overrides_by_job_id.get(job.id, [])
                    if not (
                        item.kind == JobEvidenceOverrideKind.CONTEXT
                        and item.target_key == CONTEXT_REPUTATION_SUMMARY
                    )
                ]
                own.append(
                    shared_context.model_copy(
                        update={
                            "workspace_id": workspace.id,
                            "job_record_id": records_by_job_id[job.id].id,
                        }
                    )
                )
                job_overrides_by_job_id[job.id] = own
        if (
            self.employer_reputation is not None
            and workspace.account_id is not None
            and workspace.persona_id is not None
        ):
            ratings = self.employer_reputation.list_for_persona(
                workspace.persona_id,
                account_id=workspace.account_id,
            )
            stars_by_employer_key = {rating.employer_key: rating.stars for rating in ratings}
            for job in jobs_to_evaluate:
                employer_name = next(
                    (
                        override.text_value
                        for override in job_overrides_by_job_id.get(job.id, [])
                        if override.target_key == CONTEXT_COMPANY_NAME and override.text_value
                    ),
                    job.company,
                )
                employer_name = resolved_employer_name(employer_name)
                if employer_name is None:
                    continue
                try:
                    _, employer_key = normalize_employer_name(employer_name)
                except ValueError:
                    continue
                if employer_key in stars_by_employer_key:
                    employer_reputation_by_job_id[job.id] = stars_by_employer_key[employer_key]
        if (
            self.job_ratings is not None
            and workspace.account_id is not None
            and workspace.persona_id is not None
        ):
            rated_record_ids = {records_by_job_id[job.id].id for job in jobs_to_evaluate}
            ratings_by_record_id = self.job_ratings.list_for_jobs(
                workspace.persona_id,
                rated_record_ids,
                account_id=workspace.account_id,
            )
            job_ratings_by_job_id = {
                job.id: rating.stars
                for job in jobs_to_evaluate
                if (rating := ratings_by_record_id.get(records_by_job_id[job.id].id)) is not None
            }

        # Routing and optional company research are independent I/O. Running the
        # two bounded pools together prevents one slow public source from making
        # every other job wait behind it. Provider-level pacing and locks remain
        # authoritative, so this does not bypass public-service fair-use limits.
        mobility_pool = (
            DaemonThreadPoolExecutor(
                max_workers=min(8, len(route_jobs)),
                thread_name_prefix="routes",
            )
            if self.mobility is not None and route_jobs
            else None
        )
        context_pool = (
            DaemonThreadPoolExecutor(
                max_workers=min(8, len(jobs_to_evaluate)),
                thread_name_prefix="company-context",
            )
            if self.employer_context is not None
            else None
        )
        with provider_operation_scope(workflow_id, "match-run"):
            if salary_research_jobs and self.salary_benchmark is not None:
                report(
                    "salary_evidence",
                    completed_units,
                    total_units,
                    "Checking attributable European salary evidence in one bounded batch.",
                )
                try:
                    salary_research = self.salary_benchmark.research(salary_research_jobs)
                    if isinstance(salary_research, SalaryResearchResult):
                        salary_evidence_by_job_id = salary_research.evidence
                        salary_guesses_by_job_id = salary_research.guesses
                    else:
                        # Compatibility for injected pre-v0.7.1g test/research adapters.
                        salary_evidence_by_job_id = salary_research
                except Exception:
                    # Salary orientation is optional. Provider/accounting adapters
                    # record their own failure; absence of evidence stays UNKNOWN.
                    salary_evidence_by_job_id = {}
                completed_units += 1
            pools_completed = False
            try:
                mobility_futures = (
                    {
                        job.id: mobility_pool.submit(
                            copy_context().run,
                            self.mobility.assess,
                            workspace.id,
                            records_by_job_id[job.id].id,
                            workspace.session.profile,
                            routing_destinations_from_job(job),
                            company=job.company,
                        )
                        for job in route_jobs
                    }
                    if mobility_pool is not None and self.mobility is not None
                    else {}
                )
                context_futures = (
                    {
                        job.id: context_pool.submit(
                            copy_context().run,
                            self.employer_context.assess,
                            job,
                        )
                        for job in jobs_to_evaluate
                    }
                    if context_pool is not None and self.employer_context is not None
                    else {}
                )
                mobility_job_ids = {future: job_id for job_id, future in mobility_futures.items()}
                context_job_ids = {future: job_id for job_id, future in context_futures.items()}
                pending = set(mobility_job_ids) | set(context_job_ids)
                while pending:
                    checkpoint()
                    completed, pending = wait(
                        pending,
                        timeout=0.25,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in completed:
                        if future in mobility_job_ids:
                            job_id = mobility_job_ids[future]
                            commutes_by_job_id[job_id] = future.result()
                            completed_units += 1
                            report(
                                "routing",
                                completed_units,
                                total_units,
                                f"Calculated commute evidence for {len(commutes_by_job_id)} of {len(route_jobs)} routed jobs.",
                            )
                        else:
                            job_id = context_job_ids[future]
                            contexts_by_job_id[job_id] = future.result()
                            completed_units += 1
                            report(
                                "company_evidence",
                                completed_units,
                                total_units,
                                f"Checked public company evidence for {len(contexts_by_job_id)} of {len(jobs_to_evaluate)} jobs.",
                            )
                pools_completed = True
            finally:
                if mobility_pool is not None:
                    mobility_pool.shutdown(
                        wait=pools_completed,
                        cancel_futures=not pools_completed,
                    )
                if context_pool is not None:
                    context_pool.shutdown(
                        wait=pools_completed,
                        cancel_futures=not pools_completed,
                    )
            report(
                "matching",
                completed_units,
                total_units,
                "Comparing evidence with your Compass boundaries.",
            )
            evaluated_run = match_jobs(
                workspace.session.profile,
                jobs_to_evaluate,
                run_id=workflow_id,
                commutes_by_job_id=commutes_by_job_id,
                contexts_by_job_id=contexts_by_job_id,
                salary_evidence_by_job_id=salary_evidence_by_job_id,
                salary_guesses_by_job_id=salary_guesses_by_job_id,
                job_overrides_by_job_id=job_overrides_by_job_id,
                employer_reputation_by_job_id=employer_reputation_by_job_id,
                job_ratings_by_job_id=job_ratings_by_job_id,
                match_evidence_resolver=self.match_evidence_resolver,
            )
            checkpoint()
            run = self._merge_current_results(
                evaluated_run,
                previous if can_reuse_previous else None,
                records_by_job_id,
                jobs_by_id,
                evaluated_record_ids={records_by_job_id[job.id].id for job in jobs_to_evaluate},
            )
            completed_units += 1
            report(
                "saving",
                completed_units,
                total_units,
                "Saving the evidence-backed result groups.",
            )
        record_ids_by_job_id = {job_id: record.id for job_id, record in records_by_job_id.items()}
        operation_summary = (
            self.operation_ledger.summary_since(workflow_id=workflow_id)
            if self.operation_ledger is not None
            else None
        )
        metrics_checkpoint = MatchRunMetrics(
            finished_at=datetime.now(timezone.utc),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            jobs_evaluated=len(jobs_to_evaluate),
            exact_route_jobs=len(route_jobs),
            included_slots=0,
            top_count=sum(result.disposition == MatchDisposition.TOP for result in run.results),
            stretch_count=sum(
                result.disposition == MatchDisposition.STRETCH for result in run.results
            ),
            blocked_count=sum(
                result.disposition == MatchDisposition.BLOCKED for result in run.results
            ),
            provider_operations=(operation_summary.total_operations if operation_summary else 0),
            provider_failures=(operation_summary.failed_operations if operation_summary else 0),
            provider_results=(operation_summary.result_count if operation_summary else 0),
            provider_costed_operations=(
                operation_summary.costed_operations if operation_summary else 0
            ),
            provider_unpriced_operations=(
                operation_summary.unpriced_operations if operation_summary else 0
            ),
            estimated_cost_usd=(operation_summary.estimated_cost_usd if operation_summary else 0),
        )
        checkpoint()
        stored = self.results.save_run(
            workspace.id,
            run,
            workspace.session.profile,
            jobs_by_id,
            record_ids_by_job_id,
            matched_record_ids={records_by_job_id[job.id].id for job in jobs_to_evaluate},
            metrics_checkpoint=metrics_checkpoint,
            commit_task_id=(workflow_id if task_attempt is not None else None),
            expected_task_attempt=task_attempt,
            task_claim_token=task_claim_token,
        )
        checkpoint()
        stored = self._finalize_saved_run(
            workspace,
            stored,
            workflow_id=workflow_id,
            fallback_metrics=metrics_checkpoint,
        )
        completed_units += 1
        report(
            "complete",
            completed_units,
            total_units,
            "Matching is ready.",
        )
        return self._present(workspace, stored)

    def _finalize_saved_run(
        self,
        workspace: ProfileWorkspace,
        stored: StoredMatchRun,
        *,
        workflow_id: UUID,
        fallback_metrics: MatchRunMetrics | None = None,
    ) -> StoredMatchRun:
        """Resume every local post-save step idempotently and provider-free."""

        # A rating can be saved while a long provider-backed Match is still
        # computing. This deterministic pass also safely resumes if the first
        # attempt failed before or during reconciliation.
        stored = self._reconcile_saved_run_ratings(workspace, stored)
        grants = self.results.grant_initial_results(
            workspace.id,
            stored.id,
            limit=self.policy.free_match_result_limit,
        )
        current_record_ids = {item.job_record_id for item in stored.results}
        included_slots = sum(grant.job_record_id in current_record_ids for grant in grants)
        top_count = sum(item.result.disposition == MatchDisposition.TOP for item in stored.results)
        stretch_count = sum(
            item.result.disposition == MatchDisposition.STRETCH for item in stored.results
        )
        blocked_count = sum(
            item.result.disposition == MatchDisposition.BLOCKED for item in stored.results
        )
        metrics_are_current = bool(
            stored.metrics is not None
            and stored.metrics.included_slots == included_slots
            and stored.metrics.top_count == top_count
            and stored.metrics.stretch_count == stretch_count
            and stored.metrics.blocked_count == blocked_count
        )
        if metrics_are_current:
            return stored

        metrics = (
            stored.metrics
            or fallback_metrics
            or self.results.run_metrics_checkpoint(stored.id)
            or self._recovered_run_metrics(stored, workflow_id=workflow_id)
        )
        return self.results.save_run_metrics(
            stored.id,
            metrics.model_copy(
                update={
                    "included_slots": included_slots,
                    "top_count": top_count,
                    "stretch_count": stretch_count,
                    "blocked_count": blocked_count,
                }
            ),
        )

    def _recovered_run_metrics(
        self,
        stored: StoredMatchRun,
        *,
        workflow_id: UUID,
    ) -> MatchRunMetrics:
        """Conservatively finalize a legacy partial run without a checkpoint."""

        operation_summary = (
            self.operation_ledger.summary_since(workflow_id=workflow_id)
            if self.operation_ledger is not None
            else None
        )
        non_remote_jobs = sum(not job_is_remote_only(item.job) for item in stored.results)
        return MatchRunMetrics(
            finished_at=datetime.now(timezone.utc),
            latency_ms=max(
                0,
                round((datetime.now(timezone.utc) - stored.created_at).total_seconds() * 1000),
            ),
            jobs_evaluated=len(stored.results),
            exact_route_jobs=min(non_remote_jobs, self.policy.exact_route_match_limit),
            included_slots=0,
            top_count=0,
            stretch_count=0,
            blocked_count=0,
            provider_operations=(operation_summary.total_operations if operation_summary else 0),
            provider_failures=(operation_summary.failed_operations if operation_summary else 0),
            provider_results=(operation_summary.result_count if operation_summary else 0),
            provider_costed_operations=(
                operation_summary.costed_operations if operation_summary else 0
            ),
            provider_unpriced_operations=(
                operation_summary.unpriced_operations if operation_summary else 0
            ),
            estimated_cost_usd=(operation_summary.estimated_cost_usd if operation_summary else 0),
        )

    def _reconcile_saved_run_ratings(
        self,
        workspace: ProfileWorkspace,
        stored: StoredMatchRun,
    ) -> StoredMatchRun:
        """Make a newly saved full Match converge with concurrent rating writes."""

        latest = self.results.latest_run(workspace.id)
        if latest is None or latest.id != stored.id:
            return stored
        for item in list(latest.results):
            if self._rating_projection_is_current(workspace, item, item.result):
                continue
            try:
                self.rescore_from_stored_evidence(workspace, item.job_record_id)
            except ResultServiceError:
                # A newer full Match won the race and owns reconciliation now.
                break
            latest = self.results.latest_run(workspace.id)
            if latest is None or latest.id != stored.id:
                return stored
        return self.results.get_run(stored.id) or stored

    @staticmethod
    def _merge_current_results(
        evaluated: MatchRun,
        previous: StoredMatchRun | None,
        records_by_job_id: dict[UUID, JobRecord],
        jobs_by_id: dict[UUID, object],
        *,
        evaluated_record_ids: set[UUID],
    ) -> MatchRun:
        """Keep unchanged current results while replacing only selected records."""

        if previous is None:
            return evaluated
        current_record_ids_by_job_id = {
            job_id: record.id for job_id, record in records_by_job_id.items()
        }
        reused = []
        for stored in previous.results:
            if stored.job_record_id in evaluated_record_ids:
                continue
            current_record_id = current_record_ids_by_job_id.get(stored.job.id)
            if current_record_id != stored.job_record_id:
                continue
            if stored.job.id not in jobs_by_id:
                continue
            reused.append(stored.result)
        order = {
            MatchDisposition.TOP: 0,
            MatchDisposition.STRETCH: 1,
            MatchDisposition.BLOCKED: 2,
        }
        combined = [*evaluated.results, *reused]
        combined.sort(key=lambda result: (order[result.disposition], -result.score))
        return evaluated.model_copy(update={"results": combined})

    def latest(self, workspace: ProfileWorkspace) -> ResultGroups | None:
        stored = self.results.latest_run(workspace.id)
        return self._present(workspace, stored) if stored else None

    def detail(
        self,
        workspace: ProfileWorkspace,
        run_id: UUID,
        record_id: UUID,
    ) -> ResultDetail:
        stored = self.results.get_run(run_id)
        if stored is None or stored.workspace_id != workspace.id:
            raise KeyError(f"unknown match run: {run_id}")
        groups = self._present(workspace, stored)
        item = next(
            (
                candidate
                for candidate in [*groups.top, *groups.stretch, *groups.blocked]
                if candidate.record.id == record_id
            ),
            None,
        )
        if item is None:
            raise KeyError(f"opportunity is not part of match run: {record_id}")
        if not item.accessible:
            raise ResultAccessError(
                f"This recommendation is beyond the {self.policy.free_match_result_limit} "
                "free results for this profile."
            )
        return ResultDetail(
            groups=groups,
            item=item,
            events=self.results.interaction_events(workspace.id, record_id),
        )

    def latest_detail(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> ResultDetail | None:
        stored = self.results.latest_run(workspace.id)
        if stored is None:
            return None
        if not any(item.job_record_id == record_id for item in stored.results):
            return None
        return self.detail(workspace, stored.id, record_id)

    def _private_scoring_inputs(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
        job_company: str,
    ) -> tuple[list[JobEvidenceOverride], int | None, int | None]:
        """Load only persona-owned values used by deterministic scoring."""

        overrides = (
            self.job_overrides.list_for_job(workspace.id, record_id)
            if self.job_overrides is not None
            else []
        )
        employer_stars: int | None = None
        job_stars: int | None = None
        if workspace.account_id is None or workspace.persona_id is None:
            return overrides, employer_stars, job_stars

        employer_name = next(
            (
                override.text_value
                for override in overrides
                if override.kind == JobEvidenceOverrideKind.CONTEXT
                and override.target_key == CONTEXT_COMPANY_NAME
                and override.text_value
            ),
            job_company,
        )
        resolved_name = resolved_employer_name(employer_name)
        if self.employer_reputation is not None and resolved_name is not None:
            rating = self.employer_reputation.get(
                workspace.persona_id,
                resolved_name,
                account_id=workspace.account_id,
            )
            employer_stars = rating.stars if rating is not None else None
        if self.job_ratings is not None:
            rating = self.job_ratings.get(
                workspace.persona_id,
                record_id,
                account_id=workspace.account_id,
            )
            job_stars = rating.stars if rating is not None else None
        return overrides, employer_stars, job_stars

    def _rescore_saved_result(
        self,
        workspace: ProfileWorkspace,
        stored: StoredMatchRun,
        item: StoredMatchResult,
    ) -> MatchResult:
        """Build one provider-free result from an immutable saved evidence snapshot."""

        record_id = item.job_record_id
        overrides, employer_stars, job_stars = self._private_scoring_inputs(
            workspace,
            record_id,
            item.job.company,
        )
        automatic = item.result
        context = (
            JobContext(
                employer=automatic.employer_assessment,
                work_mode_facts=automatic.derived_work_mode_facts,
                company_intelligence=automatic.company_intelligence,
            )
            if automatic.employer_assessment is not None
            else None
        )
        # A saved result contains the previous user-adjusted commute as well as
        # the original provider duration.  Strip only the private overlay before
        # applying the current override set again.
        automatic_commutes = [
            commute.model_copy(update={"user_override_minutes": None})
            for commute in automatic.commutes
        ]
        rescored = match_job(
            stored.profile,
            item.job,
            commutes=automatic_commutes,
            context=context,
            reused_automatic_salary_estimate=automatic.automatic_salary_estimate,
            automatic_salary_estimate_is_reused=True,
            job_overrides=overrides,
            employer_reputation_stars=employer_stars,
            job_rating_stars=job_stars,
            semantic_assessments=automatic.semantic_assessments,
        )
        user_fingerprint = automatic.user_evidence_fingerprint
        if automatic.rating_fingerprint is None and user_fingerprint is not None:
            current_override_fingerprint = user_evidence_fingerprint(overrides)
            previous_employer_stars = (
                automatic.employer_reputation.stars
                if automatic.employer_reputation is not None
                else None
            )
            previous_job_stars = (
                automatic.job_rating.stars if automatic.job_rating is not None else None
            )
            legacy_fingerprint = legacy_user_evidence_fingerprint(
                overrides,
                employer_reputation_stars=previous_employer_stars,
                job_rating_stars=previous_job_stars,
            )
            if user_fingerprint in {current_override_fingerprint, legacy_fingerprint}:
                # This is a safe, schema-free lineage upgrade: the stored
                # fingerprint proves that corrected evidence did not change;
                # only its previously bundled rating portion is split out.
                user_fingerprint = current_override_fingerprint
        # A deterministic overlay re-score must not masquerade as a full
        # evidence refresh.  Keep the semantic lineage from the last expensive
        # match so the separate full-rematch gate can still detect Compass,
        # source, or corrected-private-evidence changes since that refresh.
        # The newly calculated rating fingerprint is intentionally retained.
        rescored = rescored.model_copy(
            update={
                "profile_fingerprint": automatic.profile_fingerprint,
                "source_evidence_fingerprint": automatic.source_evidence_fingerprint,
                "user_evidence_fingerprint": user_fingerprint,
            }
        )
        return rescored

    def _rating_projection_is_current(
        self,
        workspace: ProfileWorkspace,
        item: StoredMatchResult,
        result: MatchResult,
    ) -> bool:
        """Confirm a completed local write still reflects the latest ratings."""

        _overrides, employer_stars, job_stars = self._private_scoring_inputs(
            workspace,
            item.job_record_id,
            item.job.company,
        )
        return result.rating_fingerprint == rating_input_fingerprint(
            employer_reputation_stars=employer_stars,
            job_rating_stars=job_stars,
        )

    def rescore_from_stored_evidence(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> MatchResult:
        """Recalculate one score without any provider, extraction, or research call.

        The immutable automatic evidence comes from the latest saved result.
        Only current private overrides and ratings are layered on top.  The
        repository then replaces and reorders the one row atomically while all
        other result JSON remains byte-for-byte untouched.
        """

        last_conflict: Exception | None = None
        for _attempt in range(LOCAL_PROJECTION_MAX_ATTEMPTS):
            stored = self.results.latest_run(workspace.id)
            if stored is None:
                raise ResultServiceError("Run Match once before updating a saved score.")
            if stored.algorithm_version != CURRENT_MATCHING_ALGORITHM:
                raise ResultServiceError(
                    "This result uses an older scoring algorithm. Run complete Match first."
                )
            item = next(
                (candidate for candidate in stored.results if candidate.job_record_id == record_id),
                None,
            )
            if item is None:
                raise ResultServiceError("This job is not part of the latest Match run.")

            rescored = self._rescore_saved_result(workspace, stored, item)
            try:
                self.results.replace_result_atomically(
                    workspace.id,
                    stored.id,
                    record_id,
                    rescored,
                    item.job,
                    expected_result=item.result,
                )
            except ConcurrentResultUpdateError as exc:
                last_conflict = exc
                continue
            except OperationalError as exc:
                if not _retryable_projection_write_error(exc):
                    raise
                last_conflict = exc
                continue
            if self._rating_projection_is_current(workspace, item, rescored):
                return rescored
            last_conflict = ConcurrentResultUpdateError(
                "rating changed while its local result projection was being saved"
            )
        raise ResultServiceError(
            "The ranking changed concurrently. Retry the saved rating or correction."
        ) from last_conflict

    def rescore_employer_from_stored_evidence(
        self,
        workspace: ProfileWorkspace,
        employer_name: str,
    ) -> dict[UUID, MatchResult]:
        """Apply one employer rating to every matching row in the latest run.

        Employer ratings are stored against a normalized company identity, not
        against the job whose control happened to be clicked.  A quick score
        update must follow the same rule: every job in the current Match whose
        effective employer has that identity is recalculated locally.  No
        provider, extraction, or research dependency is touched.
        """

        resolved_target = resolved_employer_name(employer_name)
        if resolved_target is None:
            raise ResultServiceError("Set a specific employer name before updating scores.")
        try:
            _, target_key = normalize_employer_name(resolved_target)
        except ValueError as exc:
            raise ResultServiceError(str(exc)) from exc

        last_conflict: Exception | None = None
        for _attempt in range(LOCAL_PROJECTION_MAX_ATTEMPTS):
            stored = self.results.latest_run(workspace.id)
            if stored is None:
                raise ResultServiceError("Run Match once before updating a saved score.")
            if stored.algorithm_version != CURRENT_MATCHING_ALGORITHM:
                raise ResultServiceError(
                    "This result uses an older scoring algorithm. Run complete Match first."
                )

            affected_items: list[StoredMatchResult] = []
            for item in stored.results:
                overrides = (
                    self.job_overrides.list_for_job(workspace.id, item.job_record_id)
                    if self.job_overrides is not None
                    else []
                )
                effective_name = next(
                    (
                        override.text_value
                        for override in overrides
                        if override.kind == JobEvidenceOverrideKind.CONTEXT
                        and override.target_key == CONTEXT_COMPANY_NAME
                        and override.text_value
                    ),
                    item.job.company,
                )
                resolved_name = resolved_employer_name(effective_name)
                if resolved_name is None:
                    continue
                try:
                    _, employer_key = normalize_employer_name(resolved_name)
                except ValueError:
                    continue
                if employer_key == target_key:
                    affected_items.append(item)

            rescored_by_record = {
                item.job_record_id: self._rescore_saved_result(workspace, stored, item)
                for item in affected_items
            }
            if not rescored_by_record:
                return {}
            try:
                self.results.replace_results_atomically(
                    workspace.id,
                    stored.id,
                    {
                        item.job_record_id: (rescored_by_record[item.job_record_id], item.job)
                        for item in affected_items
                    },
                    expected_results={item.job_record_id: item.result for item in affected_items},
                )
            except ConcurrentResultUpdateError as exc:
                last_conflict = exc
                continue
            except OperationalError as exc:
                if not _retryable_projection_write_error(exc):
                    raise
                last_conflict = exc
                continue
            if all(
                self._rating_projection_is_current(
                    workspace,
                    item,
                    rescored_by_record[item.job_record_id],
                )
                for item in affected_items
            ):
                return rescored_by_record
            last_conflict = ConcurrentResultUpdateError(
                "rating changed while its local result projections were being saved"
            )
        raise ResultServiceError(
            "The ranking changed concurrently. Retry the saved rating or correction."
        ) from last_conflict

    def _rating_projection_unavailable(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> RatingProjection | None:
        stored = self.results.latest_run(workspace.id)
        if stored is None:
            return RatingProjection.no_latest_match()
        if stored.algorithm_version != CURRENT_MATCHING_ALGORITHM:
            return RatingProjection.old_algorithm()
        if not any(item.job_record_id == record_id for item in stored.results):
            return RatingProjection.job_missing()
        return None

    def project_job_rating_from_stored_evidence(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> RatingProjection:
        """Quickscore one rating with an explicit no-op status for the client."""

        if unavailable := self._rating_projection_unavailable(workspace, record_id):
            return unavailable
        try:
            rescored = self.rescore_from_stored_evidence(workspace, record_id)
        except ResultServiceError:
            # A full Match may have raced the preflight. Reclassify known
            # states before reporting a genuine local projection failure.
            return (
                self._rating_projection_unavailable(
                    workspace,
                    record_id,
                )
                or RatingProjection.failed()
            )
        return RatingProjection(
            status=RatingProjectionState.UPDATED,
            results={record_id: rescored},
        )

    def project_employer_rating_from_stored_evidence(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
        employer_name: str,
    ) -> RatingProjection:
        """Quickscore every matching employer row with an explicit client status."""

        if unavailable := self._rating_projection_unavailable(workspace, record_id):
            return unavailable
        try:
            rescored = self.rescore_employer_from_stored_evidence(
                workspace,
                employer_name,
            )
        except ResultServiceError:
            return (
                self._rating_projection_unavailable(
                    workspace,
                    record_id,
                )
                or RatingProjection.failed()
            )
        if record_id not in rescored:
            return RatingProjection.job_missing()
        return RatingProjection(
            status=RatingProjectionState.UPDATED,
            results=rescored,
        )

    def full_rematch_status(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> FullRematchStatus:
        """Gate an expensive one-job evidence refresh on semantic staleness."""

        stored = self.results.latest_run(workspace.id)
        if stored is None:
            return FullRematchStatus(
                allowed=False,
                reason="Run complete Match before refreshing one job.",
                requires_complete_match=True,
            )
        if stored.algorithm_version != CURRENT_MATCHING_ALGORITHM:
            return FullRematchStatus(
                allowed=False,
                reason="The scoring algorithm changed; run complete Match instead.",
                requires_complete_match=True,
            )
        item = next(
            (candidate for candidate in stored.results if candidate.job_record_id == record_id),
            None,
        )
        if item is None:
            return FullRematchStatus(
                allowed=False,
                reason="This job is not part of the latest Match run.",
            )
        result = item.result
        if any(
            fingerprint is None
            for fingerprint in (
                result.profile_fingerprint,
                result.source_evidence_fingerprint,
                result.user_evidence_fingerprint,
            )
        ):
            return FullRematchStatus(
                allowed=True,
                reason="This legacy result has no evidence lineage and may be refreshed once.",
            )

        current_job = self.jobs.get_current_job(record_id)
        if current_job is None:
            return FullRematchStatus(
                allowed=False,
                reason="The source is no longer a live matchable job.",
            )
        overrides, _employer_stars, _job_stars = self._private_scoring_inputs(
            workspace,
            record_id,
            item.job.company,
        )
        changes: list[str] = []
        if result.profile_fingerprint != profile_evidence_fingerprint(workspace.session.profile):
            changes.append("Compass")
        if result.source_evidence_fingerprint != job_source_evidence_fingerprint(current_job):
            changes.append("job source")
        current_user_fingerprint = user_evidence_fingerprint(overrides)
        private_evidence_is_current = result.user_evidence_fingerprint == current_user_fingerprint
        if not private_evidence_is_current and result.rating_fingerprint is None:
            # Results saved before ratings received their own fingerprint
            # bundled both rating values into this field. Compare against the
            # rating values stored in that result, not today's values, so a
            # rating-only edit cannot open a provider-backed rematch gate.
            private_evidence_is_current = (
                result.user_evidence_fingerprint
                == legacy_user_evidence_fingerprint(
                    overrides,
                    employer_reputation_stars=(
                        result.employer_reputation.stars
                        if result.employer_reputation is not None
                        else None
                    ),
                    job_rating_stars=(
                        result.job_rating.stars if result.job_rating is not None else None
                    ),
                )
            )
        if not private_evidence_is_current:
            changes.append("private evidence")
        if not changes:
            return FullRematchStatus(
                allowed=False,
                reason="The Compass, source, and private evidence are already current.",
            )
        return FullRematchStatus(
            allowed=True,
            reason=f"Changed input: {', '.join(changes)}.",
        )

    def match_only_status(
        self,
        workspace: ProfileWorkspace,
        record_id: UUID,
    ) -> FullRematchStatus:
        """Allow a first or newly added job to use the existing one-job pipeline.

        A one-job run can safely create the first saved Match, or merge a newly
        added job into a current run.  It must not merge into results produced
        by an older scoring algorithm; that case still requires a complete
        Match so unlike versions are never presented as one ranking.
        """

        current_job = self.jobs.get_current_job(record_id)
        if current_job is None:
            return FullRematchStatus(
                allowed=False,
                reason="The source is no longer a live matchable job.",
            )
        stored = self.results.latest_run(workspace.id)
        if stored is None:
            return FullRematchStatus(
                allowed=True,
                reason="This job has not been matched yet.",
            )
        if stored.algorithm_version != CURRENT_MATCHING_ALGORITHM:
            return FullRematchStatus(
                allowed=False,
                reason="The scoring algorithm changed; run complete Match instead.",
                requires_complete_match=True,
            )
        if not any(item.job_record_id == record_id for item in stored.results):
            return FullRematchStatus(
                allowed=True,
                reason="This newly added job is not part of the latest Match run.",
            )
        return self.full_rematch_status(workspace, record_id)

    def _present(self, workspace: ProfileWorkspace, stored: StoredMatchRun) -> ResultGroups:
        workspace_id = workspace.id
        granted_ids = {grant.job_record_id for grant in self.results.access_grants(workspace_id)}
        interactions = self.results.interactions(workspace_id)
        records = {
            record.id: record
            for record in self.jobs.list_records()
            if not self.restrict_to_grants or record.id in granted_ids
        }
        current_profile_fingerprint = profile_evidence_fingerprint(workspace.session.profile)
        result_profile_fingerprints = [item.result.profile_fingerprint for item in stored.results]
        if result_profile_fingerprints and all(result_profile_fingerprints):
            profile_is_current = all(
                fingerprint == current_profile_fingerprint
                for fingerprint in result_profile_fingerprints
            )
        elif any(result_profile_fingerprints):
            # A partial refresh of a legacy result set is intentionally marked
            # stale until one complete Match gives every row explicit lineage.
            profile_is_current = False
        else:
            profile_is_current = (
                stored.profile.model_dump_json() == workspace.session.profile.model_dump_json()
            )
        groups = ResultGroups(
            run=stored,
            free_limit=self.policy.free_match_result_limit,
            granted_count=len(granted_ids),
            profile_is_current=profile_is_current,
            algorithm_is_current=stored.algorithm_version == CURRENT_MATCHING_ALGORITHM,
        )
        for stored_result in stored.results:
            record = records.get(stored_result.job_record_id)
            if record is None:
                continue
            blocked = stored_result.result.disposition == MatchDisposition.BLOCKED
            current_job = self.jobs.get_current_job(record.id)
            item = ResultItem(
                stored=stored_result,
                record=record,
                accessible=blocked or record.id in granted_ids,
                source_is_current=(
                    record.availability == JobAvailability.LIVE
                    and current_job is not None
                    and current_job.id == stored_result.job.id
                ),
                interaction=interactions.get(record.id),
            )
            target = {
                MatchDisposition.TOP: groups.top,
                MatchDisposition.STRETCH: groups.stretch,
                MatchDisposition.BLOCKED: groups.blocked,
            }[stored_result.result.disposition]
            target.append(item)
        return groups
