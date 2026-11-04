"""Private, persona-scoped application drafts and grounded generation service."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from .application_guidance import ApplicationGuidanceOverrideRepository
from .cv import detect_prohibited_categories
from .database import Base, Database
from .job_repository import JobRecordRow
from .jobs import JobPosting
from .llm import ApplicationDrafterPort
from .profile import EvidenceStatus, ProfileFact, ProfileSection, RequirementLevel, StrictModel
from .profile_repository import ProfileWorkspace, ProfileWorkspaceRow


MAX_APPLICATION_DRAFT_LENGTH = 12_000
MAX_APPLICATION_DRAFT_NAME_LENGTH = 120
MAX_APPLICATION_DRAFTS_PER_JOB = 3
SHORTER_DRAFT_WORD_REDUCTION = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def ensure_materially_shorter(existing_text: str, candidate_text: str) -> str:
    """Keep a provider's shorter rewrite, but enforce a visible reduction when it misses."""

    existing_words = existing_text.split()
    candidate = candidate_text.strip()
    candidate_words = candidate.split()
    if len(existing_words) < 2:
        return candidate
    reduction = (
        SHORTER_DRAFT_WORD_REDUCTION
        if len(existing_words) >= 70
        else max(1, min(30, len(existing_words) // 3))
    )
    maximum_words = max(1, len(existing_words) - reduction)
    if len(candidate_words) <= maximum_words:
        return candidate
    shortened = " ".join(candidate_words[:maximum_words]).rstrip(" ,;:-")
    if shortened and shortened[-1] not in ".!?":
        shortened += "…"
    return shortened


class DraftAction(StrEnum):
    CREATE = "create"
    RECREATE = "recreate"
    LONGER = "longer"
    SHORTER = "shorter"


class ApplicationDraftRow(Base):
    __tablename__ = "application_drafts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "job_record_id",
            "slot",
            name="uq_application_drafts_workspace_job_slot",
        ),
        CheckConstraint(
            "slot >= 1 AND slot <= 3",
            name="ck_application_drafts_slot_range",
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
    name: Mapped[str] = mapped_column(
        String(MAX_APPLICATION_DRAFT_NAME_LENGTH),
        nullable=False,
        default="Draft 1",
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generator_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generated_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    manually_edited: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApplicationDraft(StrictModel):
    id: UUID
    workspace_id: UUID
    job_record_id: UUID
    name: str
    slot: int = Field(ge=1, le=MAX_APPLICATION_DRAFTS_PER_JOB)
    content: str
    generator_model: str | None = None
    generated_action: DraftAction | None = None
    manually_edited: bool = False
    created_at: datetime
    updated_at: datetime


class ApplicationDraftError(RuntimeError):
    """Raised when a draft cannot be created or changed safely."""


class ApplicationDraftRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_draft(row: ApplicationDraftRow) -> ApplicationDraft:
        return ApplicationDraft(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            job_record_id=UUID(row.job_record_id),
            name=row.name,
            slot=row.slot,
            content=row.content,
            generator_model=row.generator_model,
            generated_action=(DraftAction(row.generated_action) if row.generated_action else None),
            manually_edited=row.manually_edited,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    def get(self, workspace_id: UUID, job_record_id: UUID) -> ApplicationDraft | None:
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(ApplicationDraftRow)
                .where(
                    ApplicationDraftRow.workspace_id == str(workspace_id),
                    ApplicationDraftRow.job_record_id == str(job_record_id),
                )
                .order_by(
                    ApplicationDraftRow.updated_at.desc(),
                    ApplicationDraftRow.slot.desc(),
                )
            )
            return self._to_draft(row) if row else None

    def get_by_id(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        draft_id: UUID,
    ) -> ApplicationDraft | None:
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(ApplicationDraftRow).where(
                    ApplicationDraftRow.id == str(draft_id),
                    ApplicationDraftRow.workspace_id == str(workspace_id),
                    ApplicationDraftRow.job_record_id == str(job_record_id),
                )
            )
            return self._to_draft(row) if row else None

    def list_for_job(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
    ) -> list[ApplicationDraft]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ApplicationDraftRow)
                .where(
                    ApplicationDraftRow.workspace_id == str(workspace_id),
                    ApplicationDraftRow.job_record_id == str(job_record_id),
                )
                .order_by(ApplicationDraftRow.slot.asc())
            ).all()
            return [self._to_draft(row) for row in rows]

    def count_for_job(self, workspace_id: UUID, job_record_id: UUID) -> int:
        with self.session_factory() as database_session:
            return int(
                database_session.scalar(
                    select(func.count(ApplicationDraftRow.id)).where(
                        ApplicationDraftRow.workspace_id == str(workspace_id),
                        ApplicationDraftRow.job_record_id == str(job_record_id),
                    )
                )
                or 0
            )

    def counts_for_workspace(self, workspace_id: UUID) -> dict[UUID, int]:
        with self.session_factory() as database_session:
            rows = database_session.execute(
                select(
                    ApplicationDraftRow.job_record_id,
                    func.count(ApplicationDraftRow.id),
                )
                .where(ApplicationDraftRow.workspace_id == str(workspace_id))
                .group_by(ApplicationDraftRow.job_record_id)
            ).all()
            return {UUID(job_record_id): int(count) for job_record_id, count in rows}

    def list_for_workspace(self, workspace_id: UUID) -> list[ApplicationDraft]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ApplicationDraftRow)
                .where(ApplicationDraftRow.workspace_id == str(workspace_id))
                .order_by(ApplicationDraftRow.updated_at.desc())
            ).all()
            return [self._to_draft(row) for row in rows]

    def save(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        content: str,
        *,
        generator_model: str | None,
        generated_action: DraftAction | None,
        manually_edited: bool,
        draft_id: UUID | None = None,
        name: str | None = None,
        create_new: bool = False,
    ) -> ApplicationDraft:
        clean = content.strip()
        if not clean:
            raise ApplicationDraftError("A cover letter cannot be empty.")
        if len(clean) > MAX_APPLICATION_DRAFT_LENGTH:
            raise ApplicationDraftError(
                f"Keep the cover letter under {MAX_APPLICATION_DRAFT_LENGTH} characters."
            )
        clean_name = " ".join((name or "").split())
        if len(clean_name) > MAX_APPLICATION_DRAFT_NAME_LENGTH:
            raise ApplicationDraftError(
                f"Keep the draft name under {MAX_APPLICATION_DRAFT_NAME_LENGTH} characters."
            )
        now = utc_now()
        with self.session_factory.begin() as database_session:
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise ApplicationDraftError("Persona not found.")
            if database_session.get(JobRecordRow, str(job_record_id)) is None:
                raise ApplicationDraftError("Job not found.")
            if draft_id is not None:
                row = database_session.scalar(
                    select(ApplicationDraftRow).where(
                        ApplicationDraftRow.id == str(draft_id),
                        ApplicationDraftRow.workspace_id == str(workspace_id),
                        ApplicationDraftRow.job_record_id == str(job_record_id),
                    )
                )
                if row is None:
                    raise ApplicationDraftError("Cover-letter draft not found.")
            elif create_new:
                row = None
            else:
                row = database_session.scalar(
                    select(ApplicationDraftRow)
                    .where(
                        ApplicationDraftRow.workspace_id == str(workspace_id),
                        ApplicationDraftRow.job_record_id == str(job_record_id),
                    )
                    .order_by(
                        ApplicationDraftRow.updated_at.desc(),
                        ApplicationDraftRow.slot.desc(),
                    )
                )
            if row is None:
                used_slots = set(
                    database_session.scalars(
                        select(ApplicationDraftRow.slot).where(
                            ApplicationDraftRow.workspace_id == str(workspace_id),
                            ApplicationDraftRow.job_record_id == str(job_record_id),
                        )
                    ).all()
                )
                slot = next(
                    (
                        candidate
                        for candidate in range(1, MAX_APPLICATION_DRAFTS_PER_JOB + 1)
                        if candidate not in used_slots
                    ),
                    None,
                )
                if slot is None:
                    raise ApplicationDraftError(
                        f"This job already has {MAX_APPLICATION_DRAFTS_PER_JOB} drafts. "
                        "Delete one before creating another."
                    )
                row = ApplicationDraftRow(
                    id=str(uuid4()),
                    workspace_id=str(workspace_id),
                    job_record_id=str(job_record_id),
                    name=clean_name or f"Draft {slot}",
                    slot=slot,
                    content=clean,
                    generator_model=generator_model,
                    generated_action=(generated_action.value if generated_action else None),
                    manually_edited=manually_edited,
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
            else:
                if clean_name:
                    row.name = clean_name
                row.content = clean
                row.generator_model = generator_model
                row.generated_action = generated_action.value if generated_action else None
                row.manually_edited = manually_edited
                row.updated_at = now
            database_session.flush()
            return self._to_draft(row)

    def delete(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        draft_id: UUID | None = None,
    ) -> bool:
        with self.session_factory.begin() as database_session:
            if draft_id is None:
                newest = database_session.scalar(
                    select(ApplicationDraftRow.id)
                    .where(
                        ApplicationDraftRow.workspace_id == str(workspace_id),
                        ApplicationDraftRow.job_record_id == str(job_record_id),
                    )
                    .order_by(
                        ApplicationDraftRow.updated_at.desc(),
                        ApplicationDraftRow.slot.desc(),
                    )
                )
                if newest is None:
                    return False
                draft_id = UUID(newest)
            result = database_session.execute(
                delete(ApplicationDraftRow).where(
                    ApplicationDraftRow.id == str(draft_id),
                    ApplicationDraftRow.workspace_id == str(workspace_id),
                    ApplicationDraftRow.job_record_id == str(job_record_id),
                )
            )
            return bool(result.rowcount)


APPLICATION_SECTIONS = {
    ProfileSection.DIRECTION,
    ProfileSection.MUST_HAVES,
    ProfileSection.PREFERENCES,
    ProfileSection.EXPERIENCE,
    ProfileSection.ENVIRONMENT_CULTURE,
}

_DIRECT_IDENTIFIER_KEY_PARTS = {
    "address",
    "birth",
    "contact",
    "email",
    "name",
    "phone",
}


def minimized_application_facts(workspace: ProfileWorkspace) -> list[ProfileFact]:
    """Select only confirmed, useful facts; raw and rejected Compass text never leaves."""

    return [
        fact
        for fact in workspace.session.profile.confirmed_facts
        if fact.evidence_status == EvidenceStatus.CONFIRMED
        and fact.level != RequirementLevel.EXCLUSION
        and fact.source.section in APPLICATION_SECTIONS
        and not _DIRECT_IDENTIFIER_KEY_PARTS.intersection(
            part.casefold() for part in fact.key.replace("-", ".").split(".")
        )
    ]


class ApplicationDraftService:
    def __init__(
        self,
        repository: ApplicationDraftRepository,
        drafter: ApplicationDrafterPort,
        guidance_repository: ApplicationGuidanceOverrideRepository | None = None,
    ) -> None:
        self.repository = repository
        self.drafter = drafter
        self.guidance_repository = guidance_repository

    def generate(
        self,
        workspace: ProfileWorkspace,
        job_record_id: UUID,
        job: JobPosting,
        action: DraftAction,
        *,
        draft_id: UUID | None = None,
        name: str | None = None,
    ) -> ApplicationDraft:
        if (
            action == DraftAction.CREATE
            and self.repository.count_for_job(workspace.id, job_record_id)
            >= MAX_APPLICATION_DRAFTS_PER_JOB
        ):
            raise ApplicationDraftError(
                f"This job already has {MAX_APPLICATION_DRAFTS_PER_JOB} drafts. "
                "Delete one before creating another."
            )
        existing = (
            self.repository.get_by_id(workspace.id, job_record_id, draft_id)
            if draft_id is not None
            else self.repository.get(workspace.id, job_record_id)
        )
        if action == DraftAction.CREATE:
            existing = None
        elif existing is None:
            raise ApplicationDraftError("Create a cover letter before changing its length.")
        facts = minimized_application_facts(workspace)
        if not facts:
            raise ApplicationDraftError(
                "Confirm at least one relevant Compass statement before creating a cover letter."
            )
        sensitive_material = "\n".join(f"{fact.key}: {fact.value}" for fact in facts)
        if existing is not None:
            sensitive_material = f"{sensitive_material}\n{existing.content}"
        blocked_categories = detect_prohibited_categories(sensitive_material)
        if blocked_categories:
            raise ApplicationDraftError(
                "Remove apparent special-category information before using OpenAI for this "
                "cover letter (" + ", ".join(blocked_categories) + ")."
            )
        try:
            effective_job = job
            if self.guidance_repository is not None:
                effective_job = job.model_copy(
                    update={
                        "application_guidance": self.guidance_repository.effective(
                            workspace.id,
                            job_record_id,
                            job.application_guidance,
                        )
                    }
                )
            content = self.drafter.draft(
                job=effective_job,
                confirmed_facts=facts,
                action=action.value,
                existing_text=existing.content if existing else None,
            )
            if action == DraftAction.SHORTER and existing is not None:
                content = ensure_materially_shorter(existing.content, content)
        except ApplicationDraftError:
            raise
        except Exception as exc:
            raise ApplicationDraftError(
                "The cover-letter provider could not complete this request. Retry later or "
                "check the secret-safe OpenAI diagnostic."
            ) from exc
        return self.repository.save(
            workspace.id,
            job_record_id,
            content,
            generator_model=self.drafter.model,
            generated_action=action,
            manually_edited=False,
            draft_id=existing.id if existing is not None else None,
            name=name,
            create_new=action == DraftAction.CREATE,
        )
