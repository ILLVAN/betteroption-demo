"""Persistent match runs, free-result grants, feedback, and application state."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, select

from .background import fence_background_task_commit
from .database import Base, Database
from .jobs import JobPosting
from .job_repository import JobRecordRow
from .matching import MatchDisposition, MatchResult, MatchRun
from .profile import CandidateProfile, StrictModel
from .profile_repository import ProfileWorkspaceRow


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FeedbackState(StrEnum):
    NONE = "none"
    INTERESTED = "interested"
    NOT_RELEVANT = "not_relevant"
    TOO_MUCH_CONSULTING = "too_much_consulting"
    TOO_LITTLE_DEVELOPMENT = "too_little_development"
    TOO_SENIOR = "too_senior"
    CONTEXT_MISMATCH = "context_mismatch"


class ApplicationState(StrEnum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class InteractionEventKind(StrEnum):
    FEEDBACK = "feedback"
    APPLICATION = "application"
    MATCH = "match"


class MatchRunRow(Base):
    __tablename__ = "match_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="matching-v0.7.2i"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jobs_evaluated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exact_route_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    included_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stretch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_operations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_failures: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_results: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_costed_operations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_unpriced_operations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class MatchResultRow(Base):
    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("match_run_id", "job_record_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    match_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    job_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class ResultAccessGrantRow(Base):
    __tablename__ = "result_access_grants"

    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobInteractionRow(Base):
    __tablename__ = "job_interactions"

    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    feedback: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FeedbackState.NONE.value
    )
    application_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApplicationState.DISCOVERED.value
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobInteractionEventRow(Base):
    __tablename__ = "job_interaction_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoredMatchResult(StrictModel):
    id: UUID
    match_run_id: UUID
    job_record_id: UUID
    position: int
    result: MatchResult
    job: JobPosting


class MatchRunMetrics(StrictModel):
    finished_at: datetime
    latency_ms: int
    jobs_evaluated: int
    exact_route_jobs: int
    included_slots: int
    top_count: int
    stretch_count: int
    blocked_count: int
    provider_operations: int
    provider_failures: int
    provider_results: int
    provider_costed_operations: int
    estimated_cost_usd: float
    provider_unpriced_operations: int = 0

    @property
    def has_unpriced_operations(self) -> bool:
        return self.provider_unpriced_operations > 0


class MatchRunOperationsSnapshot(StrictModel):
    id: UUID
    created_at: datetime
    algorithm_version: str
    metrics: MatchRunMetrics


class StoredMatchRun(StrictModel):
    id: UUID
    workspace_id: UUID
    profile_id: UUID
    profile: CandidateProfile
    created_at: datetime
    algorithm_version: str
    results: list[StoredMatchResult]
    metrics: MatchRunMetrics | None = None

    def as_match_run(self) -> MatchRun:
        return MatchRun(
            id=self.id,
            profile_id=self.profile_id,
            created_at=self.created_at,
            algorithm_version=self.algorithm_version,
            results=[item.result for item in self.results],
        )


class ResultAccessGrant(StrictModel):
    workspace_id: UUID
    job_record_id: UUID
    granted_at: datetime


class JobInteraction(StrictModel):
    workspace_id: UUID
    job_record_id: UUID
    feedback: FeedbackState = FeedbackState.NONE
    application_state: ApplicationState = ApplicationState.DISCOVERED
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class JobInteractionEvent(StrictModel):
    id: UUID
    workspace_id: UUID
    job_record_id: UUID
    kind: InteractionEventKind
    value: str
    note: str | None = None
    created_at: datetime


class ConcurrentResultUpdateError(RuntimeError):
    """Raised when a local projection was calculated from a stale result row."""


class ResultRepository:
    """Store result decisions without mixing them into source job revisions."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_result(row: MatchResultRow) -> StoredMatchResult:
        return StoredMatchResult(
            id=UUID(row.id),
            match_run_id=UUID(row.match_run_id),
            job_record_id=UUID(row.job_record_id),
            position=row.position,
            result=MatchResult.model_validate_json(row.result_json),
            job=JobPosting.model_validate_json(row.job_snapshot_json),
        )

    def _to_run(self, database_session, row: MatchRunRow) -> StoredMatchRun:
        result_rows = database_session.scalars(
            select(MatchResultRow)
            .where(MatchResultRow.match_run_id == row.id)
            .order_by(MatchResultRow.position.asc())
        ).all()
        metrics = self._to_metrics(row)
        return StoredMatchRun(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            profile_id=UUID(row.profile_id),
            profile=CandidateProfile.model_validate_json(row.profile_snapshot_json),
            created_at=ensure_utc(row.created_at),
            algorithm_version=row.algorithm_version,
            results=[self._to_result(result) for result in result_rows],
            metrics=metrics,
        )

    @staticmethod
    def _to_metrics(row: MatchRunRow) -> MatchRunMetrics | None:
        if row.latency_ms is None or row.finished_at is None or row.included_slots is None:
            return None
        return MatchRunMetrics(
            finished_at=ensure_utc(row.finished_at),
            latency_ms=row.latency_ms,
            jobs_evaluated=row.jobs_evaluated or 0,
            exact_route_jobs=row.exact_route_jobs or 0,
            included_slots=row.included_slots or 0,
            top_count=row.top_count or 0,
            stretch_count=row.stretch_count or 0,
            blocked_count=row.blocked_count or 0,
            provider_operations=row.provider_operations or 0,
            provider_failures=row.provider_failures or 0,
            provider_results=row.provider_results or 0,
            provider_costed_operations=row.provider_costed_operations or 0,
            provider_unpriced_operations=row.provider_unpriced_operations or 0,
            estimated_cost_usd=row.estimated_cost_usd or 0,
        )

    def save_run(
        self,
        workspace_id: UUID,
        run: MatchRun,
        profile: CandidateProfile,
        jobs_by_id: dict[UUID, JobPosting],
        record_ids_by_job_id: dict[UUID, UUID],
        *,
        matched_record_ids: set[UUID] | None = None,
        metrics_checkpoint: MatchRunMetrics | None = None,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> StoredMatchRun:
        with self.session_factory.begin() as database_session:
            supplied_fence_values = (
                commit_task_id is not None,
                expected_task_attempt is not None,
                task_claim_token is not None,
            )
            if any(supplied_fence_values) and not all(supplied_fence_values):
                raise ValueError("task id, attempt, and claim token must be supplied together")
            if (
                commit_task_id is not None
                and expected_task_attempt is not None
                and task_claim_token is not None
            ):
                fence_background_task_commit(
                    database_session,
                    commit_task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            row = MatchRunRow(
                id=str(run.id),
                workspace_id=str(workspace_id),
                profile_id=str(run.profile_id),
                profile_snapshot_json=profile.model_dump_json(),
                algorithm_version=run.algorithm_version,
                created_at=run.created_at,
            )
            if metrics_checkpoint is not None:
                for field, value in metrics_checkpoint.model_dump(
                    exclude={"included_slots"}
                ).items():
                    setattr(row, field, value)
            database_session.add(row)
            database_session.flush()
            persisted_record_ids: set[UUID] = set()
            for position, result in enumerate(run.results, start=1):
                job = jobs_by_id[result.job_id]
                job_record_id = record_ids_by_job_id[result.job_id]
                persisted_record_ids.add(job_record_id)
                database_session.add(
                    MatchResultRow(
                        id=str(uuid4()),
                        match_run_id=str(run.id),
                        job_record_id=str(job_record_id),
                        position=position,
                        disposition=result.disposition.value,
                        score=result.score,
                        result_json=result.model_dump_json(),
                        job_snapshot_json=job.model_dump_json(),
                    )
                )
            evaluated_record_ids = matched_record_ids or set()
            if not evaluated_record_ids.issubset(persisted_record_ids):
                raise ValueError("matched records must belong to the saved match run")
            matched_at = utc_now()
            for job_record_id in sorted(evaluated_record_ids, key=str):
                key = {
                    "workspace_id": str(workspace_id),
                    "job_record_id": str(job_record_id),
                }
                interaction = database_session.get(JobInteractionRow, key)
                if interaction is not None and (
                    interaction.application_state != ApplicationState.DISCOVERED.value
                ):
                    continue
                if interaction is None:
                    interaction = JobInteractionRow(
                        workspace_id=str(workspace_id),
                        job_record_id=str(job_record_id),
                        feedback=FeedbackState.NONE.value,
                        application_state=ApplicationState.MATCHED.value,
                        note=None,
                        created_at=matched_at,
                        updated_at=matched_at,
                    )
                    database_session.add(interaction)
                else:
                    interaction.application_state = ApplicationState.MATCHED.value
                    interaction.updated_at = matched_at
                database_session.add(
                    JobInteractionEventRow(
                        id=str(uuid4()),
                        workspace_id=str(workspace_id),
                        job_record_id=str(job_record_id),
                        kind=InteractionEventKind.MATCH.value,
                        value=ApplicationState.MATCHED.value,
                        note=None,
                        created_at=matched_at,
                    )
                )
            database_session.flush()
            return self._to_run(database_session, row)

    def replace_result_atomically(
        self,
        workspace_id: UUID,
        run_id: UUID,
        job_record_id: UUID,
        result: MatchResult,
        job: JobPosting,
        *,
        expected_result: MatchResult | None = None,
    ) -> StoredMatchRun:
        """Replace and re-rank one saved result without creating a new run."""

        return self.replace_results_atomically(
            workspace_id,
            run_id,
            {job_record_id: (result, job)},
            expected_results=(
                {job_record_id: expected_result} if expected_result is not None else None
            ),
        )

    def replace_results_atomically(
        self,
        workspace_id: UUID,
        run_id: UUID,
        replacements: dict[UUID, tuple[MatchResult, JobPosting]],
        *,
        expected_results: dict[UUID, MatchResult] | None = None,
    ) -> StoredMatchRun:
        """Replace one or more saved results and re-rank them in one transaction.

        Fast user-evidence scoring must not leave score, disposition, ordering,
        and run counters out of sync.  The whole replacement is therefore one
        database transaction.  No source job row is mutated; ``job`` remains
        the immutable snapshot on which the score was calculated.
        """

        if not replacements:
            raise ValueError("at least one replacement result is required")
        expected_results = expected_results or {}
        if not set(expected_results).issubset(replacements):
            raise ValueError("expected results must refer to replacement rows")

        order = {
            MatchDisposition.TOP.value: 0,
            MatchDisposition.STRETCH.value: 1,
            MatchDisposition.BLOCKED.value: 2,
        }
        with self.session_factory.begin() as database_session:
            run_row = database_session.scalar(
                select(MatchRunRow).where(MatchRunRow.id == str(run_id)).with_for_update()
            )
            if run_row is None or run_row.workspace_id != str(workspace_id):
                raise KeyError(f"unknown match run: {run_id}")
            rows = list(
                database_session.scalars(
                    select(MatchResultRow)
                    .where(MatchResultRow.match_run_id == str(run_id))
                    .with_for_update()
                ).all()
            )
            rows_by_record_id = {UUID(row.job_record_id): row for row in rows}
            for job_record_id, (result, job) in replacements.items():
                result_row = rows_by_record_id.get(job_record_id)
                if result_row is None:
                    raise KeyError(f"opportunity is not part of match run: {job_record_id}")
                if result.job_id != job.id:
                    raise ValueError("replacement result and job snapshot do not match")
                values = {
                    "disposition": result.disposition.value,
                    "score": result.score,
                    "result_json": result.model_dump_json(),
                    "job_snapshot_json": job.model_dump_json(),
                }
                expected = expected_results.get(job_record_id)
                if expected is None:
                    for key, value in values.items():
                        setattr(result_row, key, value)
                    continue

                # PostgreSQL serializes contenders through the locked run row;
                # the conditional write also makes the same stale-write check
                # effective in SQLite, where SELECT FOR UPDATE is a no-op.
                changed = database_session.execute(
                    update(MatchResultRow)
                    .where(
                        MatchResultRow.id == result_row.id,
                        MatchResultRow.result_json == expected.model_dump_json(),
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise ConcurrentResultUpdateError(
                        f"match result changed concurrently: {job_record_id}"
                    )

            database_session.flush()
            database_session.expire_all()
            rows = list(
                database_session.scalars(
                    select(MatchResultRow)
                    .where(MatchResultRow.match_run_id == str(run_id))
                    .with_for_update()
                ).all()
            )

            # Preserve the previous relative order when two rows have the same
            # disposition and score. A random UUID tie-breaker makes unrelated
            # cards visibly jump after a small private edit.
            rows.sort(
                key=lambda row: (
                    order[row.disposition],
                    -row.score,
                    row.position,
                )
            )
            for position, row in enumerate(rows, start=1):
                row.position = position

            if run_row.finished_at is not None:
                run_row.top_count = sum(
                    row.disposition == MatchDisposition.TOP.value for row in rows
                )
                run_row.stretch_count = sum(
                    row.disposition == MatchDisposition.STRETCH.value for row in rows
                )
                run_row.blocked_count = sum(
                    row.disposition == MatchDisposition.BLOCKED.value for row in rows
                )
            database_session.flush()
            return self._to_run(database_session, run_row)

    def get_run(self, run_id: UUID) -> StoredMatchRun | None:
        with self.session_factory() as database_session:
            row = database_session.get(MatchRunRow, str(run_id))
            return self._to_run(database_session, row) if row else None

    def latest_run(self, workspace_id: UUID) -> StoredMatchRun | None:
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(MatchRunRow)
                .where(MatchRunRow.workspace_id == str(workspace_id))
                .order_by(MatchRunRow.created_at.desc(), MatchRunRow.id.desc())
            )
            return self._to_run(database_session, row) if row else None

    def save_run_metrics(self, run_id: UUID, metrics: MatchRunMetrics) -> StoredMatchRun:
        with self.session_factory.begin() as database_session:
            row = database_session.get(MatchRunRow, str(run_id))
            if row is None:
                raise KeyError(f"unknown match run: {run_id}")
            for field, value in metrics.model_dump().items():
                setattr(row, field, value)
            database_session.flush()
            return self._to_run(database_session, row)

    def run_metrics_checkpoint(self, run_id: UUID) -> MatchRunMetrics | None:
        """Read pre-finalization metrics saved atomically with a match run."""

        with self.session_factory() as database_session:
            row = database_session.get(MatchRunRow, str(run_id))
            if row is None:
                raise KeyError(f"unknown match run: {run_id}")
            if row.latency_ms is None or row.finished_at is None:
                return None
            return MatchRunMetrics(
                finished_at=ensure_utc(row.finished_at),
                latency_ms=row.latency_ms,
                jobs_evaluated=row.jobs_evaluated or 0,
                exact_route_jobs=row.exact_route_jobs or 0,
                included_slots=0,
                top_count=row.top_count or 0,
                stretch_count=row.stretch_count or 0,
                blocked_count=row.blocked_count or 0,
                provider_operations=row.provider_operations or 0,
                provider_failures=row.provider_failures or 0,
                provider_results=row.provider_results or 0,
                provider_costed_operations=row.provider_costed_operations or 0,
                provider_unpriced_operations=row.provider_unpriced_operations or 0,
                estimated_cost_usd=row.estimated_cost_usd or 0,
            )

    def recent_run_metrics(self, *, limit: int = 10) -> list[MatchRunOperationsSnapshot]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(MatchRunRow)
                .where(MatchRunRow.latency_ms.is_not(None))
                .order_by(MatchRunRow.created_at.desc(), MatchRunRow.id.desc())
                .limit(limit)
            ).all()
            snapshots = []
            for row in rows:
                metrics = self._to_metrics(row)
                if metrics is None:
                    continue
                snapshots.append(
                    MatchRunOperationsSnapshot(
                        id=UUID(row.id),
                        created_at=ensure_utc(row.created_at),
                        algorithm_version=row.algorithm_version,
                        metrics=metrics,
                    )
                )
            return snapshots

    def grant_initial_results(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        limit: int,
    ) -> list[ResultAccessGrant]:
        if limit < 1:
            raise ValueError("free result limit must be positive")
        now = utc_now()
        with self.session_factory.begin() as database_session:
            workspace = database_session.scalar(
                select(ProfileWorkspaceRow)
                .where(ProfileWorkspaceRow.id == str(workspace_id))
                .with_for_update()
            )
            if workspace is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            run = database_session.get(MatchRunRow, str(run_id))
            if run is None or run.workspace_id != str(workspace_id):
                raise KeyError(f"unknown match run: {run_id}")
            existing_rows = database_session.scalars(
                select(ResultAccessGrantRow).where(
                    ResultAccessGrantRow.workspace_id == str(workspace_id)
                )
            ).all()
            existing_ids = {row.job_record_id for row in existing_rows}
            remaining = max(0, limit - len(existing_ids))
            if remaining:
                candidates = database_session.scalars(
                    select(MatchResultRow)
                    .where(
                        MatchResultRow.match_run_id == str(run_id),
                        MatchResultRow.disposition != MatchDisposition.BLOCKED.value,
                    )
                    .order_by(MatchResultRow.position.asc())
                ).all()
                for candidate in candidates:
                    if candidate.job_record_id in existing_ids:
                        continue
                    database_session.add(
                        ResultAccessGrantRow(
                            workspace_id=str(workspace_id),
                            job_record_id=candidate.job_record_id,
                            granted_at=now,
                        )
                    )
                    existing_ids.add(candidate.job_record_id)
                    remaining -= 1
                    if remaining == 0:
                        break
            database_session.flush()
            rows = database_session.scalars(
                select(ResultAccessGrantRow)
                .where(ResultAccessGrantRow.workspace_id == str(workspace_id))
                .order_by(ResultAccessGrantRow.granted_at.asc())
            ).all()
            return [self._to_grant(row) for row in rows]

    def access_grants(self, workspace_id: UUID) -> list[ResultAccessGrant]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ResultAccessGrantRow)
                .where(ResultAccessGrantRow.workspace_id == str(workspace_id))
                .order_by(ResultAccessGrantRow.granted_at.asc())
            ).all()
            return [self._to_grant(row) for row in rows]

    def grant_job(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> ResultAccessGrant:
        """Grant one private workspace access to a shared public job record."""

        now = utc_now()
        with self.session_factory.begin() as database_session:
            supplied = (
                commit_task_id is not None,
                expected_task_attempt is not None,
                task_claim_token is not None,
            )
            if any(supplied) and not all(supplied):
                raise ValueError("task id, attempt, and claim token must be supplied together")
            if all(supplied):
                fence_background_task_commit(
                    database_session,
                    commit_task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            if database_session.get(JobRecordRow, str(job_record_id)) is None:
                raise KeyError(f"unknown job record: {job_record_id}")
            key = {
                "workspace_id": str(workspace_id),
                "job_record_id": str(job_record_id),
            }
            row = database_session.get(ResultAccessGrantRow, key)
            if row is None:
                row = ResultAccessGrantRow(granted_at=now, **key)
                database_session.add(row)
                database_session.flush()
            return self._to_grant(row)

    def revoke_job(self, workspace_id: UUID, job_record_id: UUID) -> bool:
        """Remove a job from one workspace without deleting the shared source."""

        with self.session_factory.begin() as database_session:
            key = {
                "workspace_id": str(workspace_id),
                "job_record_id": str(job_record_id),
            }
            row = database_session.get(ResultAccessGrantRow, key)
            if row is None:
                return False
            database_session.execute(
                delete(JobInteractionEventRow).where(
                    JobInteractionEventRow.workspace_id == str(workspace_id),
                    JobInteractionEventRow.job_record_id == str(job_record_id),
                )
            )
            interaction = database_session.get(JobInteractionRow, key)
            if interaction is not None:
                database_session.delete(interaction)
            run_ids = select(MatchRunRow.id).where(MatchRunRow.workspace_id == str(workspace_id))
            database_session.execute(
                delete(MatchResultRow).where(
                    MatchResultRow.job_record_id == str(job_record_id),
                    MatchResultRow.match_run_id.in_(run_ids),
                )
            )
            database_session.delete(row)
            return True

    @staticmethod
    def _to_grant(row: ResultAccessGrantRow) -> ResultAccessGrant:
        return ResultAccessGrant(
            workspace_id=UUID(row.workspace_id),
            job_record_id=UUID(row.job_record_id),
            granted_at=ensure_utc(row.granted_at),
        )

    def get_interaction(self, workspace_id: UUID, job_record_id: UUID) -> JobInteraction | None:
        with self.session_factory() as database_session:
            row = database_session.get(
                JobInteractionRow,
                {"workspace_id": str(workspace_id), "job_record_id": str(job_record_id)},
            )
            return self._to_interaction(row) if row else None

    def interactions(self, workspace_id: UUID) -> dict[UUID, JobInteraction]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(JobInteractionRow).where(JobInteractionRow.workspace_id == str(workspace_id))
            ).all()
            return {UUID(row.job_record_id): self._to_interaction(row) for row in rows}

    def set_feedback(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        feedback: FeedbackState,
        *,
        note: str | None = None,
    ) -> JobInteraction:
        return self._set_interaction(
            workspace_id,
            job_record_id,
            kind=InteractionEventKind.FEEDBACK,
            value=feedback.value,
            note=note,
        )

    def set_application_state(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        state: ApplicationState,
    ) -> JobInteraction:
        return self._set_interaction(
            workspace_id,
            job_record_id,
            kind=InteractionEventKind.APPLICATION,
            value=state.value,
            note=None,
        )

    def _set_interaction(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        *,
        kind: InteractionEventKind,
        value: str,
        note: str | None,
    ) -> JobInteraction:
        now = utc_now()
        clean_note = note.strip() if note is not None else None
        clean_note = clean_note or None
        with self.session_factory.begin() as database_session:
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            if database_session.get(JobRecordRow, str(job_record_id)) is None:
                raise KeyError(f"unknown job record: {job_record_id}")
            key = {"workspace_id": str(workspace_id), "job_record_id": str(job_record_id)}
            row = database_session.get(JobInteractionRow, key)
            if row is None:
                row = JobInteractionRow(
                    workspace_id=str(workspace_id),
                    job_record_id=str(job_record_id),
                    feedback=FeedbackState.NONE.value,
                    application_state=ApplicationState.DISCOVERED.value,
                    note=None,
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
            if kind == InteractionEventKind.FEEDBACK:
                row.feedback = value
                row.note = clean_note
            else:
                row.application_state = value
            row.updated_at = now
            database_session.add(
                JobInteractionEventRow(
                    id=str(uuid4()),
                    workspace_id=str(workspace_id),
                    job_record_id=str(job_record_id),
                    kind=kind.value,
                    value=value,
                    note=clean_note,
                    created_at=now,
                )
            )
            database_session.flush()
            return self._to_interaction(row)

    @staticmethod
    def _to_interaction(row: JobInteractionRow) -> JobInteraction:
        return JobInteraction(
            workspace_id=UUID(row.workspace_id),
            job_record_id=UUID(row.job_record_id),
            feedback=FeedbackState(row.feedback),
            application_state=ApplicationState(row.application_state),
            note=row.note,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    def interaction_events(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
    ) -> list[JobInteractionEvent]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(JobInteractionEventRow)
                .where(
                    JobInteractionEventRow.workspace_id == str(workspace_id),
                    JobInteractionEventRow.job_record_id == str(job_record_id),
                )
                .order_by(JobInteractionEventRow.created_at.asc(), JobInteractionEventRow.id.asc())
            ).all()
            return [
                JobInteractionEvent(
                    id=UUID(row.id),
                    workspace_id=UUID(row.workspace_id),
                    job_record_id=UUID(row.job_record_id),
                    kind=InteractionEventKind(row.kind),
                    value=row.value,
                    note=row.note,
                    created_at=ensure_utc(row.created_at),
                )
                for row in rows
            ]

    def count_runs(self, workspace_id: UUID) -> int:
        with self.session_factory() as database_session:
            return int(
                database_session.scalar(
                    select(func.count(MatchRunRow.id)).where(
                        MatchRunRow.workspace_id == str(workspace_id)
                    )
                )
                or 0
            )
