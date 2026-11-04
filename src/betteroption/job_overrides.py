"""Persona-scoped, typed corrections to automatically derived job evidence.

Overrides never mutate the public job source or a candidate's Compass.  They are
kept as a small private layer that is reapplied whenever the persona runs Match.
Deleting an override therefore restores the normal automatic calculation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .job_repository import JobRecordRow
from .profile import StrictModel
from .profile_repository import ProfileWorkspaceRow


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class JobEvidenceOverrideKind(StrEnum):
    REASON = "reason"
    COMMUTE_MINUTES = "commute_minutes"
    SKILL = "skill"
    POSTING_DATE = "posting_date"
    CONTEXT = "context"


class ReasonOverrideValue(StrEnum):
    POSITIVE = "positive"
    VIOLATED = "violated"
    UNKNOWN = "unknown"


class SkillOverrideValue(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"


class JobEvidenceOverride(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    job_record_id: UUID
    kind: JobEvidenceOverrideKind
    target_key: str = Field(min_length=1, max_length=500)
    target_label: str = Field(min_length=1, max_length=500)
    reason_value: ReasonOverrideValue | None = None
    skill_value: SkillOverrideValue | None = None
    commute_minutes: int | None = Field(default=None, ge=1, le=360)
    posting_date: date | None = None
    text_value: str | None = Field(default=None, min_length=1, max_length=2_000)
    note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def exactly_one_typed_value(self) -> JobEvidenceOverride:
        values = {
            JobEvidenceOverrideKind.REASON: self.reason_value,
            JobEvidenceOverrideKind.SKILL: self.skill_value,
            JobEvidenceOverrideKind.COMMUTE_MINUTES: self.commute_minutes,
            JobEvidenceOverrideKind.POSTING_DATE: self.posting_date,
            JobEvidenceOverrideKind.CONTEXT: self.text_value,
        }
        if values[self.kind] is None:
            raise ValueError(f"{self.kind.value} override requires its typed value")
        if any(value is not None for kind, value in values.items() if kind != self.kind):
            raise ValueError("job evidence override contains a value for another kind")
        return self


class JobEvidenceOverrideRow(Base):
    __tablename__ = "job_evidence_overrides"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "job_record_id",
            "kind",
            "target_key",
            name="uq_job_evidence_overrides_target",
        ),
    )

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
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_key: Mapped[str] = mapped_column(String(500), nullable=False)
    target_label: Mapped[str] = mapped_column(String(500), nullable=False)
    reason_value: Mapped[str | None] = mapped_column(String(16), nullable=True)
    skill_value: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commute_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posting_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobEvidenceOverrideRepository:
    """Persist private evidence corrections for one persona and job.

    A persona can receive a replacement Compass workspace over time.  Rows keep
    their original workspace foreign key for backwards compatibility, while
    reads, updates, and deletes follow the persona across all of its workspaces.
    Legacy/local workspaces without a persona remain isolated by workspace.
    """

    def __init__(self, database: Database) -> None:
        self.session_factory = database.session_factory

    @staticmethod
    def _to_model(row: JobEvidenceOverrideRow) -> JobEvidenceOverride:
        return JobEvidenceOverride(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            job_record_id=UUID(row.job_record_id),
            kind=JobEvidenceOverrideKind(row.kind),
            target_key=row.target_key,
            target_label=row.target_label,
            reason_value=ReasonOverrideValue(row.reason_value) if row.reason_value else None,
            skill_value=SkillOverrideValue(row.skill_value) if row.skill_value else None,
            commute_minutes=row.commute_minutes,
            posting_date=row.posting_date,
            text_value=row.text_value,
            note=row.note,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    @staticmethod
    def _scope_workspace_ids(database_session, workspace_id: UUID) -> list[str]:
        workspace = database_session.get(ProfileWorkspaceRow, str(workspace_id))
        if workspace is None:
            raise KeyError(f"unknown profile workspace: {workspace_id}")
        if workspace.persona_id is None:
            return [workspace.id]
        return list(
            database_session.scalars(
                select(ProfileWorkspaceRow.id).where(
                    ProfileWorkspaceRow.persona_id == workspace.persona_id
                )
            ).all()
        )

    def list_for_job(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
    ) -> list[JobEvidenceOverride]:
        with self.session_factory() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            rows = database_session.scalars(
                select(JobEvidenceOverrideRow)
                .where(
                    JobEvidenceOverrideRow.workspace_id.in_(workspace_ids),
                    JobEvidenceOverrideRow.job_record_id == str(job_record_id),
                )
                .order_by(
                    JobEvidenceOverrideRow.kind.asc(),
                    JobEvidenceOverrideRow.target_label.asc(),
                )
            ).all()
            return [self._to_model(row) for row in rows]

    def list_for_jobs(
        self,
        workspace_id: UUID,
        job_record_ids: set[UUID],
    ) -> dict[UUID, list[JobEvidenceOverride]]:
        if not job_record_ids:
            return {}
        with self.session_factory() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            rows = database_session.scalars(
                select(JobEvidenceOverrideRow)
                .where(
                    JobEvidenceOverrideRow.workspace_id.in_(workspace_ids),
                    JobEvidenceOverrideRow.job_record_id.in_(
                        [str(value) for value in job_record_ids]
                    ),
                )
                .order_by(JobEvidenceOverrideRow.updated_at.asc())
            ).all()
            grouped: dict[UUID, list[JobEvidenceOverride]] = {}
            for row in rows:
                grouped.setdefault(UUID(row.job_record_id), []).append(self._to_model(row))
            return grouped

    def upsert(self, override: JobEvidenceOverride) -> JobEvidenceOverride:
        return self.upsert_many([override])[0]

    def upsert_many(
        self,
        overrides: list[JobEvidenceOverride],
    ) -> list[JobEvidenceOverride]:
        """Validate and store one bulk edit in a single database transaction.

        The web editor builds every typed model before calling this method.  The
        repository then fails the whole write if the scope is mixed, a target is
        duplicated, or any referenced workspace/job is missing.
        """

        if not overrides:
            return []
        workspace_id = overrides[0].workspace_id
        job_record_id = overrides[0].job_record_id
        if any(
            item.workspace_id != workspace_id or item.job_record_id != job_record_id
            for item in overrides
        ):
            raise ValueError("bulk evidence overrides must share one workspace and job")
        targets = [(item.kind, item.target_key) for item in overrides]
        if len(set(targets)) != len(targets):
            raise ValueError("bulk evidence overrides contain a duplicate target")

        stored: list[JobEvidenceOverride] = []
        with self.session_factory.begin() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            if database_session.get(JobRecordRow, str(job_record_id)) is None:
                raise KeyError(f"unknown job record: {job_record_id}")
            for override in overrides:
                now = utc_now()
                clean_note = override.note.strip() if override.note else None
                row = database_session.scalar(
                    select(JobEvidenceOverrideRow).where(
                        JobEvidenceOverrideRow.workspace_id.in_(workspace_ids),
                        JobEvidenceOverrideRow.job_record_id == str(job_record_id),
                        JobEvidenceOverrideRow.kind == override.kind.value,
                        JobEvidenceOverrideRow.target_key == override.target_key,
                    )
                )
                if row is None:
                    row = JobEvidenceOverrideRow(
                        id=str(override.id),
                        workspace_id=str(workspace_id),
                        job_record_id=str(job_record_id),
                        kind=override.kind.value,
                        target_key=override.target_key,
                        target_label=override.target_label,
                        created_at=now,
                        updated_at=now,
                    )
                    database_session.add(row)
                row.target_label = override.target_label
                row.reason_value = override.reason_value.value if override.reason_value else None
                row.skill_value = override.skill_value.value if override.skill_value else None
                row.commute_minutes = override.commute_minutes
                row.posting_date = override.posting_date
                row.text_value = override.text_value.strip() if override.text_value else None
                row.note = clean_note
                row.updated_at = now
                database_session.flush()
                stored.append(self._to_model(row))
            database_session.flush()
        return stored

    def delete(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        kind: JobEvidenceOverrideKind,
        target_key: str,
    ) -> bool:
        with self.session_factory.begin() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            result = database_session.execute(
                delete(JobEvidenceOverrideRow).where(
                    JobEvidenceOverrideRow.workspace_id.in_(workspace_ids),
                    JobEvidenceOverrideRow.job_record_id == str(job_record_id),
                    JobEvidenceOverrideRow.kind == kind.value,
                    JobEvidenceOverrideRow.target_key == target_key,
                )
            )
            return bool(result.rowcount)
