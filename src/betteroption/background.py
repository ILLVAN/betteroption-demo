"""Durable, privacy-safe background work with progress and retry state."""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import Event, Lock, Thread
from time import monotonic
from typing import TypeAlias
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    and_,
    or_,
    select,
    update,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from .concurrency import CooperativeControlFlow, cooperative_control
from .database import Base, Database
from .profile import StrictModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class BackgroundTaskKind(StrEnum):
    MATCH_RUN = "match_run"
    SINGLE_JOB_MATCH = "single_job_match"
    EXPLORE_SEARCH = "explore_search"
    JOB_IMPORT = "job_import"


class JobImportDestination(StrEnum):
    ARCHIVE = "archive"
    MATCHING = "matching"


class BackgroundTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundLeaseStatus(StrEnum):
    ACTIVE = "active"
    CANCEL_REQUESTED = "cancel_requested"
    LOST = "lost"


ACTIVE_TASK_STATUSES = {
    BackgroundTaskStatus.QUEUED,
    BackgroundTaskStatus.RUNNING,
    BackgroundTaskStatus.RETRY_WAIT,
}


class BackgroundTask(StrictModel):
    id: UUID
    workspace_id: UUID
    kind: BackgroundTaskKind
    status: BackgroundTaskStatus
    phase: str
    message: str
    completed_units: int
    total_units: int
    attempt: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    result_url: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    claim_token: UUID | None = None
    claim_owner: str | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None

    @property
    def progress_percent(self) -> int:
        if self.status == BackgroundTaskStatus.SUCCEEDED:
            return 100
        if self.total_units <= 0:
            return 0
        return min(99, max(0, round(self.completed_units * 100 / self.total_units)))

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            BackgroundTaskStatus.SUCCEEDED,
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.CANCELLED,
        }


class BackgroundTaskRow(Base):
    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    completed_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    result_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundTaskCommitRejected(RuntimeError):
    """A domain result tried to commit after its task claim was fenced."""


def fence_background_task_commit(
    session,
    task_id: UUID,
    *,
    expected_attempt: int,
    claim_token: UUID,
) -> None:
    """Lock/validate one active claim inside the caller's result transaction.

    A conditional no-op UPDATE is deliberate.  PostgreSQL locks the matching
    task row and SQLite obtains its write serialization before the domain rows
    are changed.  Cancel and result commit therefore have one database order:
    either the result transaction commits first, or cancellation wins and this
    transaction writes nothing.
    """

    result = session.execute(
        update(BackgroundTaskRow)
        .where(
            BackgroundTaskRow.id == str(task_id),
            BackgroundTaskRow.status == BackgroundTaskStatus.RUNNING.value,
            BackgroundTaskRow.attempt == expected_attempt,
            BackgroundTaskRow.claim_token == str(claim_token),
            BackgroundTaskRow.cancel_requested_at.is_(None),
            BackgroundTaskRow.lease_expires_at.is_not(None),
            BackgroundTaskRow.lease_expires_at > utc_now(),
        )
        .values(updated_at=BackgroundTaskRow.updated_at)
    )
    if result.rowcount != 1:
        raise BackgroundTaskCommitRejected(
            "The background task claim ended before its result could be committed."
        )


class BackgroundJobImportBatchRow(Base):
    """Private payload for one durable Explore import workflow."""

    __tablename__ = "background_job_import_batches"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("background_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    destination: Mapped[str] = mapped_column(String(24), nullable=False)
    source_explore_task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("explore_searches.task_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundJobImportItemRow(Base):
    __tablename__ = "background_job_import_items"
    __table_args__ = (
        UniqueConstraint("task_id", "position", name="uq_background_job_import_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("background_job_import_batches.task_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2_000), nullable=False)


class BackgroundSingleJobMatchRow(Base):
    """Durable, minimal payload for recomputing exactly one saved job."""

    __tablename__ = "background_single_job_matches"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("background_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundJobImportBatch(StrictModel):
    task_id: UUID
    destination: JobImportDestination
    source_urls: list[str]
    source_explore_task_id: UUID | None = None
    created_at: datetime


class BackgroundSingleJobMatch(StrictModel):
    task_id: UUID
    job_record_id: UUID
    created_at: datetime


class BackgroundTaskRepository:
    """Persist task state without storing candidate, prompt, or provider payloads."""

    def __init__(self, database: Database) -> None:
        self.database = database
        # The private-alpha web process can serve several browser tabs at once.
        # Keep the active-task check and insert together inside this process so
        # two near-simultaneous requests do not both enqueue the same workflow.
        self._active_create_lock = Lock()

    def create(
        self,
        workspace_id: UUID,
        kind: BackgroundTaskKind,
        *,
        max_attempts: int = 2,
        task_id: UUID | None = None,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> BackgroundTask:
        now = utc_now()
        row = BackgroundTaskRow(
            id=str(task_id or uuid4()),
            workspace_id=str(workspace_id),
            kind=kind.value,
            status=BackgroundTaskStatus.QUEUED.value,
            phase="queued",
            message="Waiting for the background worker.",
            completed_units=0,
            total_units=0,
            attempt=0,
            max_attempts=max(1, max_attempts),
            created_at=now,
            updated_at=now,
        )
        with self.database.session_factory.begin() as session:
            supplied = (
                commit_task_id is not None,
                expected_task_attempt is not None,
                task_claim_token is not None,
            )
            if any(supplied) and not all(supplied):
                raise ValueError("task id, attempt, and claim token must be supplied together")
            if all(supplied):
                fence_background_task_commit(
                    session,
                    commit_task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            session.add(row)
        return self._from_row(row)

    def get(self, task_id: UUID) -> BackgroundTask | None:
        with self.database.session_factory() as session:
            row = session.get(BackgroundTaskRow, str(task_id))
            return self._from_row(row) if row else None

    def find_active(
        self,
        workspace_id: UUID,
        kind: BackgroundTaskKind,
    ) -> BackgroundTask | None:
        with self.database.session_factory() as session:
            row = session.scalar(
                select(BackgroundTaskRow)
                .where(
                    BackgroundTaskRow.workspace_id == str(workspace_id),
                    BackgroundTaskRow.kind == kind.value,
                    BackgroundTaskRow.status.in_([status.value for status in ACTIVE_TASK_STATUSES]),
                )
                .order_by(BackgroundTaskRow.created_at.desc())
                .limit(1)
            )
            return self._from_row(row) if row else None

    def get_or_create_active(
        self,
        workspace_id: UUID,
        kind: BackgroundTaskKind,
        *,
        max_attempts: int = 2,
    ) -> tuple[BackgroundTask, bool]:
        """Return one active task, creating it once for concurrent local requests.

        The boolean is true only for the caller that inserted the task.  The
        current private-alpha deployment has one web process; a hosted
        multi-process worker should replace this in-process guard with a
        database lease or partial unique index.
        """

        with self._active_create_lock:
            active = self.find_active(workspace_id, kind)
            if active is not None:
                return active, False
            return (
                self.create(
                    workspace_id,
                    kind,
                    max_attempts=max_attempts,
                ),
                True,
            )

    def list_recent(self, *, limit: int = 20) -> list[BackgroundTask]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(BackgroundTaskRow)
                .order_by(
                    BackgroundTaskRow.updated_at.desc(),
                    BackgroundTaskRow.created_at.desc(),
                )
                .limit(max(1, limit))
            ).all()
            return [self._from_row(row) for row in rows]

    @staticmethod
    def _recoverable_claims(now: datetime):
        return (
            select(BackgroundTaskRow)
            .where(
                BackgroundTaskRow.status == BackgroundTaskStatus.RUNNING.value,
                or_(
                    BackgroundTaskRow.lease_expires_at.is_(None),
                    BackgroundTaskRow.lease_expires_at <= now,
                ),
            )
            .with_for_update(skip_locked=True)
        )

    def recover_interrupted(self, *, now: datetime | None = None) -> int:
        """Recover only abandoned claims whose lease is absent or expired."""

        now = ensure_utc(now) or utc_now()
        recovered = 0
        with self.database.session_factory.begin() as session:
            rows = session.scalars(self._recoverable_claims(now)).all()
            for row in rows:
                if row.cancel_requested_at is not None:
                    self._mark_cancelled(row, now)
                else:
                    row.status = BackgroundTaskStatus.QUEUED.value
                    row.phase = "recovered"
                    row.message = (
                        "The application restarted after this workflow's worker lease expired. "
                        "It is queued to resume."
                    )
                    row.next_attempt_at = None
                    row.updated_at = now
                    self._clear_claim(row)
                recovered += 1
        return recovered

    def requeue_interrupted(
        self,
        task_id: UUID,
        *,
        expected_attempt: int,
        claim_token: UUID,
    ) -> bool:
        """Requeue a cooperatively unwound claim, fenced against stale workers."""

        now = utc_now()
        with self.database.session_factory.begin() as session:
            row = self._lock_row(session, task_id)
            if row is None or row.status != BackgroundTaskStatus.RUNNING.value:
                return False
            if not self._claim_matches(row, expected_attempt, claim_token):
                return False
            if row.cancel_requested_at is not None:
                self._mark_cancelled(row, now)
                return True
            row.status = BackgroundTaskStatus.QUEUED.value
            row.phase = "paused_for_restart"
            row.message = (
                "Application shutdown paused this workflow. It is queued to resume after restart."
            )
            row.next_attempt_at = None
            row.updated_at = now
            self._clear_claim(row)
            return True

    def claim_next(
        self,
        *,
        claim_owner: str = "background-worker",
        lease_ttl_seconds: float = 30.0,
        now: datetime | None = None,
    ) -> BackgroundTask | None:
        now = ensure_utc(now) or utc_now()
        lease_ttl = timedelta(seconds=max(0.1, lease_ttl_seconds))
        with self.database.session_factory.begin() as session:
            row = session.scalar(
                select(BackgroundTaskRow)
                .where(
                    BackgroundTaskRow.cancel_requested_at.is_(None),
                    or_(
                        BackgroundTaskRow.status == BackgroundTaskStatus.QUEUED.value,
                        and_(
                            BackgroundTaskRow.status == BackgroundTaskStatus.RETRY_WAIT.value,
                            or_(
                                BackgroundTaskRow.next_attempt_at.is_(None),
                                BackgroundTaskRow.next_attempt_at <= now,
                            ),
                        ),
                    ),
                )
                .order_by(BackgroundTaskRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = BackgroundTaskStatus.RUNNING.value
            row.phase = "starting"
            row.message = "Preparing the workflow."
            row.attempt += 1
            row.started_at = row.started_at or now
            row.next_attempt_at = None
            row.updated_at = now
            row.claim_token = str(uuid4())
            row.claim_owner = claim_owner[:160]
            row.heartbeat_at = now
            row.lease_expires_at = now + lease_ttl
            session.flush()
            return self._from_row(row)

    def heartbeat(
        self,
        task_id: UUID,
        *,
        expected_attempt: int,
        claim_token: UUID,
        lease_ttl_seconds: float,
        now: datetime | None = None,
    ) -> BackgroundLeaseStatus:
        """Renew a claim and surface cancellation without touching progress."""

        now = ensure_utc(now) or utc_now()
        with self.database.session_factory.begin() as session:
            row = self._lock_row(session, task_id)
            if (
                row is None
                or row.status != BackgroundTaskStatus.RUNNING.value
                or not self._claim_matches(row, expected_attempt, claim_token)
                or row.lease_expires_at is None
                or ensure_utc(row.lease_expires_at) <= now
            ):
                return BackgroundLeaseStatus.LOST
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=max(0.1, lease_ttl_seconds))
            if row.cancel_requested_at is not None:
                return BackgroundLeaseStatus.CANCEL_REQUESTED
            return BackgroundLeaseStatus.ACTIVE

    def request_cancel(self, task_id: UUID) -> BackgroundTask:
        """Idempotently make cancellation terminal and fence in-flight output.

        A running external call cannot always be interrupted at the socket
        level, but retaining its RUNNING claim made the product look stuck and
        allowed the worker to keep its lease for minutes.  Clearing the claim
        here makes the user's decision authoritative immediately.  The owning
        worker observes the lost fence (or its local cancel event), unwinds at
        its next cooperative checkpoint, and cannot finish the terminal task.
        Claim-aware final Explore/Match snapshots use the same database fence.
        """

        now = utc_now()
        with self.database.session_factory.begin() as session:
            row = self._require_row(session, task_id)
            if row.status in {
                BackgroundTaskStatus.SUCCEEDED.value,
                BackgroundTaskStatus.FAILED.value,
                BackgroundTaskStatus.CANCELLED.value,
            }:
                return self._from_row(row)
            row.cancel_requested_at = row.cancel_requested_at or now
            self._mark_cancelled(row, now)
            session.flush()
            return self._from_row(row)

    def finalize_cancel(
        self,
        task_id: UUID,
        *,
        expected_attempt: int,
        claim_token: UUID,
    ) -> BackgroundTask:
        """Finish a running cancellation only for the worker holding the claim."""

        now = utc_now()
        with self.database.session_factory.begin() as session:
            row = self._require_row(session, task_id)
            if (
                row.status == BackgroundTaskStatus.RUNNING.value
                and row.cancel_requested_at is not None
                and self._claim_matches(row, expected_attempt, claim_token)
            ):
                self._mark_cancelled(row, now)
                session.flush()
            return self._from_row(row)

    def update_progress(
        self,
        task_id: UUID,
        *,
        phase: str,
        completed_units: int,
        total_units: int,
        message: str,
        expected_attempt: int,
        claim_token: UUID,
    ) -> BackgroundTask:
        with self.database.session_factory.begin() as session:
            row = self._require_row(session, task_id)
            if row.status != BackgroundTaskStatus.RUNNING.value:
                return self._from_row(row)
            if not self._claim_matches(row, expected_attempt, claim_token):
                return self._from_row(row)
            if row.cancel_requested_at is not None:
                return self._from_row(row)
            row.phase = phase[:64]
            row.completed_units = max(0, completed_units)
            row.total_units = max(0, total_units)
            row.message = message[:500]
            row.updated_at = utc_now()
            session.flush()
            return self._from_row(row)

    def succeed(
        self,
        task_id: UUID,
        *,
        result_url: str,
        expected_attempt: int,
        claim_token: UUID,
    ) -> BackgroundTask:
        now = utc_now()
        with self.database.session_factory.begin() as session:
            row = self._require_row(session, task_id)
            if row.status != BackgroundTaskStatus.RUNNING.value:
                return self._from_row(row)
            if not self._claim_matches(row, expected_attempt, claim_token):
                return self._from_row(row)
            if row.cancel_requested_at is not None:
                self._mark_cancelled(row, now)
                session.flush()
                return self._from_row(row)
            row.status = BackgroundTaskStatus.SUCCEEDED.value
            row.phase = "complete"
            row.message = "The workflow completed successfully."
            row.completed_units = max(row.completed_units, row.total_units, 1)
            row.total_units = max(row.total_units, row.completed_units, 1)
            row.result_url = result_url[:500]
            row.error_type = None
            row.error_message = None
            row.updated_at = now
            row.finished_at = now
            self._clear_claim(row)
            session.flush()
            return self._from_row(row)

    def retry_or_fail(
        self,
        task_id: UUID,
        *,
        error_type: str,
        public_message: str,
        retry_delay_seconds: float,
        permanent: bool = False,
        expected_attempt: int,
        claim_token: UUID,
    ) -> BackgroundTask:
        now = utc_now()
        with self.database.session_factory.begin() as session:
            row = self._require_row(session, task_id)
            if row.status != BackgroundTaskStatus.RUNNING.value:
                return self._from_row(row)
            if not self._claim_matches(row, expected_attempt, claim_token):
                return self._from_row(row)
            if row.cancel_requested_at is not None:
                self._mark_cancelled(row, now)
                session.flush()
                return self._from_row(row)
            should_retry = not permanent and row.attempt < row.max_attempts
            row.error_type = error_type[:160]
            row.error_message = public_message[:500]
            row.updated_at = now
            if should_retry:
                row.status = BackgroundTaskStatus.RETRY_WAIT.value
                row.phase = "retry_wait"
                row.message = "A temporary problem occurred. Retrying automatically."
                row.next_attempt_at = now + timedelta(seconds=max(0, retry_delay_seconds))
            else:
                row.status = BackgroundTaskStatus.FAILED.value
                row.phase = "failed"
                row.message = public_message[:500]
                row.next_attempt_at = None
                row.finished_at = now
            self._clear_claim(row)
            session.flush()
            return self._from_row(row)

    @staticmethod
    def _claim_matches(
        row: BackgroundTaskRow,
        expected_attempt: int,
        claim_token: UUID,
    ) -> bool:
        return row.attempt == expected_attempt and row.claim_token == str(claim_token)

    @staticmethod
    def _clear_claim(row: BackgroundTaskRow) -> None:
        row.claim_token = None
        row.claim_owner = None
        row.lease_expires_at = None

    @classmethod
    def _mark_cancelled(cls, row: BackgroundTaskRow, now: datetime) -> None:
        row.status = BackgroundTaskStatus.CANCELLED.value
        row.phase = "cancelled"
        row.message = (
            "This workflow was cancelled. Work committed before the safe stop remains saved."
        )
        row.next_attempt_at = None
        row.updated_at = now
        row.finished_at = now
        row.cancel_requested_at = row.cancel_requested_at or now
        row.cancelled_at = row.cancelled_at or now
        cls._clear_claim(row)

    @staticmethod
    def _lock_row(session, task_id: UUID) -> BackgroundTaskRow | None:
        return session.get(
            BackgroundTaskRow,
            str(task_id),
            with_for_update=True,
        )

    @classmethod
    def _require_row(cls, session, task_id: UUID) -> BackgroundTaskRow:
        row = cls._lock_row(session, task_id)
        if row is None:
            raise KeyError(f"unknown background task: {task_id}")
        return row

    @staticmethod
    def _from_row(row: BackgroundTaskRow) -> BackgroundTask:
        return BackgroundTask(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            kind=BackgroundTaskKind(row.kind),
            status=BackgroundTaskStatus(row.status),
            phase=row.phase,
            message=row.message,
            completed_units=row.completed_units,
            total_units=row.total_units,
            attempt=row.attempt,
            max_attempts=row.max_attempts,
            next_attempt_at=ensure_utc(row.next_attempt_at),
            result_url=row.result_url,
            error_type=row.error_type,
            error_message=row.error_message,
            claim_token=UUID(row.claim_token) if row.claim_token else None,
            claim_owner=row.claim_owner,
            heartbeat_at=ensure_utc(row.heartbeat_at),
            lease_expires_at=ensure_utc(row.lease_expires_at),
            cancel_requested_at=ensure_utc(row.cancel_requested_at),
            cancelled_at=ensure_utc(row.cancelled_at),
            created_at=ensure_utc(row.created_at),
            started_at=ensure_utc(row.started_at),
            updated_at=ensure_utc(row.updated_at),
            finished_at=ensure_utc(row.finished_at),
        )


class BackgroundJobImportRepository:
    """Store selected public URLs separately from sanitized task progress."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._active_create_lock = Lock()

    def create(
        self,
        workspace_id: UUID,
        source_urls: list[str],
        destination: JobImportDestination,
        *,
        source_explore_task_id: UUID | None = None,
        max_attempts: int = 2,
    ) -> BackgroundTask:
        selected = list(dict.fromkeys(url.strip() for url in source_urls if url.strip()))
        if not selected:
            raise ValueError("At least one source URL is required.")
        now = utc_now()
        task_id = uuid4()
        task_row = BackgroundTaskRow(
            id=str(task_id),
            workspace_id=str(workspace_id),
            kind=BackgroundTaskKind.JOB_IMPORT.value,
            status=BackgroundTaskStatus.QUEUED.value,
            phase="queued",
            message="Waiting to verify the selected job sources.",
            completed_units=0,
            total_units=len(selected),
            attempt=0,
            max_attempts=max(1, max_attempts),
            created_at=now,
            updated_at=now,
        )
        batch_row = BackgroundJobImportBatchRow(
            task_id=str(task_id),
            destination=destination.value,
            source_explore_task_id=(
                str(source_explore_task_id) if source_explore_task_id is not None else None
            ),
            created_at=now,
        )
        items = [
            BackgroundJobImportItemRow(
                id=str(uuid4()),
                task_id=str(task_id),
                position=position,
                source_url=url,
            )
            for position, url in enumerate(selected)
        ]
        with self.database.session_factory.begin() as session:
            session.add(task_row)
            session.flush()
            session.add(batch_row)
            session.flush()
            session.add_all(items)
        return BackgroundTaskRepository._from_row(task_row)

    def get(self, task_id: UUID) -> BackgroundJobImportBatch | None:
        with self.database.session_factory() as session:
            batch = session.get(BackgroundJobImportBatchRow, str(task_id))
            if batch is None:
                return None
            items = session.scalars(
                select(BackgroundJobImportItemRow)
                .where(BackgroundJobImportItemRow.task_id == str(task_id))
                .order_by(BackgroundJobImportItemRow.position)
            ).all()
            return BackgroundJobImportBatch(
                task_id=task_id,
                destination=JobImportDestination(batch.destination),
                source_urls=[item.source_url for item in items],
                source_explore_task_id=(
                    UUID(batch.source_explore_task_id)
                    if batch.source_explore_task_id is not None
                    else None
                ),
                created_at=ensure_utc(batch.created_at),
            )

    def get_or_create_active(
        self,
        workspace_id: UUID,
        source_urls: list[str],
        destination: JobImportDestination,
        *,
        source_explore_task_id: UUID | None = None,
        max_attempts: int = 2,
    ) -> tuple[BackgroundTask, bool]:
        """Deduplicate an identical active import submitted by another tab."""

        selected = list(dict.fromkeys(url.strip() for url in source_urls if url.strip()))
        if not selected:
            raise ValueError("At least one source URL is required.")
        with self._active_create_lock:
            active = self.find_active(workspace_id, destination)
            if active is not None:
                batch = self.get(active.id)
                if (
                    batch is not None
                    and batch.source_urls == selected
                    and batch.source_explore_task_id == source_explore_task_id
                ):
                    return active, False
            return (
                self.create(
                    workspace_id,
                    selected,
                    destination,
                    source_explore_task_id=source_explore_task_id,
                    max_attempts=max_attempts,
                ),
                True,
            )

    def find_active(
        self,
        workspace_id: UUID,
        destination: JobImportDestination,
    ) -> BackgroundTask | None:
        """Return the newest active import feeding the requested product page."""

        with self.database.session_factory() as session:
            row = session.scalar(
                select(BackgroundTaskRow)
                .join(
                    BackgroundJobImportBatchRow,
                    BackgroundJobImportBatchRow.task_id == BackgroundTaskRow.id,
                )
                .where(
                    BackgroundTaskRow.workspace_id == str(workspace_id),
                    BackgroundTaskRow.kind == BackgroundTaskKind.JOB_IMPORT.value,
                    BackgroundTaskRow.status.in_([status.value for status in ACTIVE_TASK_STATUSES]),
                    BackgroundJobImportBatchRow.destination == destination.value,
                )
                .order_by(BackgroundTaskRow.created_at.desc())
                .limit(1)
            )
            return BackgroundTaskRepository._from_row(row) if row else None

    def delete(self, task_id: UUID) -> None:
        with self.database.session_factory.begin() as session:
            batch = session.get(BackgroundJobImportBatchRow, str(task_id))
            if batch is not None:
                session.delete(batch)

    def delete_terminal(self) -> int:
        """Delete private URL payloads whose task can no longer retry."""

        with self.database.session_factory.begin() as session:
            batches = session.scalars(
                select(BackgroundJobImportBatchRow)
                .join(
                    BackgroundTaskRow,
                    BackgroundTaskRow.id == BackgroundJobImportBatchRow.task_id,
                )
                .where(
                    BackgroundTaskRow.status.in_(
                        [
                            BackgroundTaskStatus.SUCCEEDED.value,
                            BackgroundTaskStatus.FAILED.value,
                            BackgroundTaskStatus.CANCELLED.value,
                        ]
                    )
                )
            ).all()
            for batch in batches:
                session.delete(batch)
            return len(batches)


class BackgroundSingleJobMatchRepository:
    """Create and resolve durable single-job Match requests.

    Only record identifiers are persisted. Candidate data, provider prompts,
    and derived evidence remain in their existing owner-scoped stores.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self._active_create_lock = Lock()

    def create(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        *,
        max_attempts: int = 2,
    ) -> BackgroundTask:
        now = utc_now()
        task_id = uuid4()
        task_row = BackgroundTaskRow(
            id=str(task_id),
            workspace_id=str(workspace_id),
            kind=BackgroundTaskKind.SINGLE_JOB_MATCH.value,
            status=BackgroundTaskStatus.QUEUED.value,
            phase="queued",
            message="Waiting to recompute this job in the background.",
            completed_units=0,
            total_units=1,
            attempt=0,
            max_attempts=max(1, max_attempts),
            created_at=now,
            updated_at=now,
        )
        payload_row = BackgroundSingleJobMatchRow(
            task_id=str(task_id),
            job_record_id=str(job_record_id),
            created_at=now,
        )
        with self.database.session_factory.begin() as session:
            session.add(task_row)
            session.flush()
            session.add(payload_row)
        return BackgroundTaskRepository._from_row(task_row)

    def get(self, task_id: UUID) -> BackgroundSingleJobMatch | None:
        with self.database.session_factory() as session:
            row = session.get(BackgroundSingleJobMatchRow, str(task_id))
            if row is None:
                return None
            return BackgroundSingleJobMatch(
                task_id=task_id,
                job_record_id=UUID(row.job_record_id),
                created_at=ensure_utc(row.created_at),
            )

    def get_or_create_active(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        *,
        max_attempts: int = 2,
    ) -> tuple[BackgroundTask, bool]:
        """Deduplicate one active single-job rematch across browser tabs."""

        with self._active_create_lock:
            with self.database.session_factory() as session:
                row = session.scalar(
                    select(BackgroundTaskRow)
                    .join(
                        BackgroundSingleJobMatchRow,
                        BackgroundSingleJobMatchRow.task_id == BackgroundTaskRow.id,
                    )
                    .where(
                        BackgroundTaskRow.workspace_id == str(workspace_id),
                        BackgroundTaskRow.kind == BackgroundTaskKind.SINGLE_JOB_MATCH.value,
                        BackgroundTaskRow.status.in_(
                            [status.value for status in ACTIVE_TASK_STATUSES]
                        ),
                        BackgroundSingleJobMatchRow.job_record_id == str(job_record_id),
                    )
                    .order_by(BackgroundTaskRow.created_at.desc())
                    .limit(1)
                )
                if row is not None:
                    return BackgroundTaskRepository._from_row(row), False
            return (
                self.create(
                    workspace_id,
                    job_record_id,
                    max_attempts=max_attempts,
                ),
                True,
            )


ProgressReporter: TypeAlias = Callable[[str, int, int, str], None]
TaskHandler: TypeAlias = Callable[[BackgroundTask, ProgressReporter], str]
MaintenanceHandler: TypeAlias = Callable[[], None]


class BackgroundTaskPermanentError(RuntimeError):
    """A user-correctable task failure that should not consume a retry."""


class _BackgroundControlFlow(CooperativeControlFlow):
    """Worker control signal which broad application error guards must not swallow."""


class _BackgroundWorkerStopping(_BackgroundControlFlow):
    """Internal cooperative cancellation raised at the next progress report."""


class _BackgroundTaskCancelled(_BackgroundControlFlow):
    """Internal cancellation raised after the owning worker observes the request."""


class _BackgroundLeaseLost(_BackgroundControlFlow):
    """Internal fence failure: this worker must stop writing task state."""


class BackgroundWorker:
    """Lease-backed worker usable in-process or in a standalone process."""

    def __init__(
        self,
        repository: BackgroundTaskRepository,
        handlers: dict[BackgroundTaskKind, TaskHandler],
        *,
        maintenance_handlers: tuple[MaintenanceHandler, ...] = (),
        poll_interval_seconds: float = 0.5,
        retry_base_seconds: float = 2.0,
        lease_ttl_seconds: float = 30.0,
        heartbeat_interval_seconds: float = 5.0,
        claim_owner: str | None = None,
    ) -> None:
        self.repository = repository
        self.handlers = handlers
        self.maintenance_handlers = maintenance_handlers
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.retry_base_seconds = max(0, retry_base_seconds)
        self.lease_ttl_seconds = max(0.1, lease_ttl_seconds)
        self.heartbeat_interval_seconds = min(
            max(0.05, heartbeat_interval_seconds),
            self.lease_ttl_seconds / 2,
        )
        self.claim_owner = (
            claim_owner or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        )[:160]
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._last_loop_error: str | None = None
        self._state_lock = Lock()
        self._current_task: tuple[UUID, int, UUID] | None = None
        self._current_lease_stop: Event | None = None
        self._current_cancel: Event | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_loop_error(self) -> str | None:
        return self._last_loop_error

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.repository.recover_interrupted()
            self._last_loop_error = None
            self._stop.clear()
            self._wake.clear()
            self._thread = Thread(
                target=self._loop,
                name="betteroption-background-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(
        self,
        *,
        timeout_seconds: float = 5.0,
        cancel_running: bool = False,
    ) -> None:
        """Stop accepting work and cooperatively unwind the current handler.

        Embedded/local app shutdown passes ``cancel_running=True`` so Ctrl+C
        honours the user's request to end local work.  The standalone durable
        worker keeps the default: it requeues a cooperatively paused task, or
        lets its lease expire if an external socket cannot return in time.
        """

        self._stop.set()
        self._wake.set()
        with self._state_lock:
            thread = self._thread
            current = self._current_task
            current_cancel = self._current_cancel
        if cancel_running and current is not None:
            try:
                self.repository.request_cancel(current[0])
            except (OSError, SQLAlchemyError) as exc:
                # Shutdown must remain bounded even when persistence is the
                # component being stopped.  The existing lease still fences
                # late output and will expire for recovery.
                self._last_loop_error = type(exc).__name__
            if current_cancel is not None:
                current_cancel.set()
        if thread is not None:
            thread.join(timeout=max(0, timeout_seconds))
            if not thread.is_alive():
                with self._state_lock:
                    if self._thread is thread:
                        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def cancel(self, task_id: UUID) -> bool:
        """Wake the in-process owner of a terminally cancelled task now."""

        with self._state_lock:
            current = self._current_task
            current_cancel = self._current_cancel
        if current is None or current[0] != task_id or current_cancel is None:
            return False
        current_cancel.set()
        self._wake.set()
        return True

    def run_once(self) -> bool:
        self._run_maintenance()
        if self._stop.is_set():
            return False
        task = self.repository.claim_next(
            claim_owner=self.claim_owner,
            lease_ttl_seconds=self.lease_ttl_seconds,
        )
        if task is None:
            return False
        if task.claim_token is None:
            raise RuntimeError("claimed background task has no lease token")
        claim_token = task.claim_token
        lease_stop = Event()
        local_cancel = Event()
        cancellation_seen = Event()
        lease_lost = Event()
        lease_deadline = monotonic() + self.lease_ttl_seconds
        with self._state_lock:
            self._current_task = (task.id, task.attempt, claim_token)
            self._current_lease_stop = lease_stop
            self._current_cancel = local_cancel
        if self._stop.is_set():
            self.repository.requeue_interrupted(
                task.id,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
            self._clear_current(task)
            return True
        handler = self.handlers.get(task.kind)
        if handler is None:
            self.repository.retry_or_fail(
                task.id,
                error_type="UnsupportedTaskKind",
                public_message="This background workflow is not supported by this release.",
                retry_delay_seconds=0,
                permanent=True,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
            self._clear_current(task)
            return True

        def observe_lease() -> BackgroundLeaseStatus:
            nonlocal lease_deadline
            state = self.repository.heartbeat(
                task.id,
                expected_attempt=task.attempt,
                claim_token=claim_token,
                lease_ttl_seconds=self.lease_ttl_seconds,
            )
            if state != BackgroundLeaseStatus.LOST:
                lease_deadline = monotonic() + self.lease_ttl_seconds
            if state == BackgroundLeaseStatus.CANCEL_REQUESTED:
                cancellation_seen.set()
            elif state == BackgroundLeaseStatus.LOST:
                lease_lost.set()
            return state

        def heartbeat_loop() -> None:
            while not lease_stop.wait(self.heartbeat_interval_seconds):
                try:
                    state = observe_lease()
                except (OSError, SQLAlchemyError) as exc:
                    # Keep retrying while the handler lives. Once persistence
                    # returns, heartbeat() rejects an already expired fence.
                    # If it never returns, stop trusting this claim locally at
                    # the last known deadline so the handler cannot finish it.
                    self._last_loop_error = type(exc).__name__
                    if monotonic() >= lease_deadline:
                        lease_lost.set()
                        return
                    continue
                if state == BackgroundLeaseStatus.LOST:
                    return

        heartbeat_thread = Thread(
            target=heartbeat_loop,
            name=f"betteroption-task-heartbeat-{str(task.id)[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()

        def check_control() -> None:
            if self._stop.is_set():
                raise _BackgroundWorkerStopping
            if local_cancel.is_set():
                raise _BackgroundTaskCancelled
            if lease_lost.is_set():
                raise _BackgroundLeaseLost
            if cancellation_seen.is_set():
                raise _BackgroundTaskCancelled
            state = observe_lease()
            if state == BackgroundLeaseStatus.CANCEL_REQUESTED:
                raise _BackgroundTaskCancelled
            if state == BackgroundLeaseStatus.LOST:
                raise _BackgroundLeaseLost

        def report(phase: str, completed: int, total: int, message: str) -> None:
            check_control()
            try:
                updated = self.repository.update_progress(
                    task.id,
                    phase=phase,
                    completed_units=completed,
                    total_units=total,
                    message=message,
                    expected_attempt=task.attempt,
                    claim_token=claim_token,
                )
            except (OSError, SQLAlchemyError):
                if phase != "ranking_preview":
                    raise
                # Preview status is optional. Re-check the lease so a failed
                # cosmetic write can never hide cancellation or a stale claim.
                check_control()
                return
            if updated.cancel_requested_at is not None:
                raise _BackgroundTaskCancelled
            if updated.status != BackgroundTaskStatus.RUNNING or updated.claim_token != claim_token:
                raise _BackgroundLeaseLost

        # Long provider waits poll this checkpoint without writing cosmetic
        # progress rows.  A plain callable remains fully backward compatible
        # with injected handlers and older ResultService tests.
        report.checkpoint = check_control  # type: ignore[attr-defined]

        try:
            with cooperative_control(check_control):
                result_url = handler(task, report)
            check_control()
        except _BackgroundTaskCancelled:
            self.repository.finalize_cancel(
                task.id,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
        except _BackgroundWorkerStopping:
            self.repository.requeue_interrupted(
                task.id,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
        except _BackgroundLeaseLost:
            # A newer claim owns the row. Any output from this handler is stale.
            pass
        except BackgroundTaskPermanentError as exc:
            self.repository.retry_or_fail(
                task.id,
                error_type=type(exc).__name__,
                public_message=str(exc) or "This workflow needs your attention before retrying.",
                retry_delay_seconds=0,
                permanent=True,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
        except Exception as exc:
            delay = self.retry_base_seconds * (2 ** max(0, task.attempt - 1))
            self.repository.retry_or_fail(
                task.id,
                error_type=type(exc).__name__,
                public_message="The workflow could not complete after automatic retries.",
                retry_delay_seconds=delay,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
        else:
            self.repository.succeed(
                task.id,
                result_url=result_url,
                expected_attempt=task.attempt,
                claim_token=claim_token,
            )
        finally:
            lease_stop.set()
            heartbeat_thread.join(timeout=max(0.1, self.heartbeat_interval_seconds * 2))
            self._clear_current(task)
        self._run_maintenance()
        return True

    def _run_maintenance(self) -> None:
        for handler in self.maintenance_handlers:
            try:
                handler()
            except Exception as exc:
                # Cleanup is idempotent and retried on every later worker pass.
                self._last_loop_error = type(exc).__name__

    def _clear_current(self, task: BackgroundTask) -> None:
        with self._state_lock:
            if self._current_task is not None and self._current_task[:2] == (
                task.id,
                task.attempt,
            ):
                self._current_task = None
                self._current_lease_stop = None
                self._current_cancel = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._last_loop_error = None
                worked = self.run_once()
            except Exception as exc:
                # Repository failures used to terminate the only worker thread,
                # leaving its claimed task permanently RUNNING. The task has no
                # provider or candidate payload, so returning it to the queue is
                # safe and keeps the private-alpha worker self-healing.
                self._last_loop_error = type(exc).__name__
                self.repository.recover_interrupted()
                worked = False
            if worked:
                continue
            try:
                if self.repository.recover_interrupted():
                    continue
            except Exception as exc:
                self._last_loop_error = type(exc).__name__
            self._wake.wait(self.poll_interval_seconds)
            self._wake.clear()
