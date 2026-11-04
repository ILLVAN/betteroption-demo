"""Account-owned product feedback for the private alpha."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .profile import StrictModel

MAX_FEEDBACK_MESSAGE_LENGTH = 5_000
MAX_FEEDBACK_NOTE_LENGTH = 2_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FeedbackCategory(StrEnum):
    EXPERIENCE = "experience"
    ACCURACY = "accuracy"
    IDEA = "idea"
    PROBLEM = "problem"
    OTHER = "other"


class FeedbackSurface(StrEnum):
    GENERAL = "general"
    COMPASS = "compass"
    ADD = "add"
    EXPLORE = "explore"
    MATCHING = "matching"
    APPLY = "apply"
    ARCHIVE = "archive"
    ACCOUNT = "account"


class FeedbackStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    PLANNED = "planned"
    RESOLVED = "resolved"


class ProductFeedbackRow(Base):
    __tablename__ = "product_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    contact_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=FeedbackStatus.NEW.value,
        index=True,
    )
    operator_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )


class ProductFeedback(StrictModel):
    id: UUID
    account_id: UUID
    category: FeedbackCategory
    surface: FeedbackSurface
    rating: int | None
    message: str
    contact_allowed: bool
    status: FeedbackStatus
    operator_note: str
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    reviewed_by_account_id: UUID | None


class ProductFeedbackError(ValueError):
    """Raised when product feedback is invalid or not owned by the caller."""


class ProductFeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_feedback(row: ProductFeedbackRow) -> ProductFeedback:
        return ProductFeedback(
            id=UUID(row.id),
            account_id=UUID(row.account_id),
            category=FeedbackCategory(row.category),
            surface=FeedbackSurface(row.surface),
            rating=row.rating,
            message=row.message,
            contact_allowed=row.contact_allowed,
            status=FeedbackStatus(row.status),
            operator_note=row.operator_note,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
            reviewed_at=ensure_utc(row.reviewed_at) if row.reviewed_at else None,
            reviewed_by_account_id=(
                UUID(row.reviewed_by_account_id) if row.reviewed_by_account_id else None
            ),
        )

    def submit(
        self,
        account_id: UUID,
        *,
        category: FeedbackCategory,
        surface: FeedbackSurface,
        rating: int | None,
        message: str,
        contact_allowed: bool,
    ) -> ProductFeedback:
        clean_message = " ".join(message.split())
        if not clean_message:
            raise ProductFeedbackError("Tell us what you noticed before sending feedback.")
        if len(clean_message) > MAX_FEEDBACK_MESSAGE_LENGTH:
            raise ProductFeedbackError(
                f"Keep feedback to {MAX_FEEDBACK_MESSAGE_LENGTH:,} characters or fewer."
            )
        if rating is not None and rating not in range(1, 6):
            raise ProductFeedbackError("Choose a rating from 1 to 5, or leave it blank.")
        now = utc_now()
        row = ProductFeedbackRow(
            id=str(uuid4()),
            account_id=str(account_id),
            category=category.value,
            surface=surface.value,
            rating=rating,
            message=clean_message,
            contact_allowed=contact_allowed,
            status=FeedbackStatus.NEW.value,
            operator_note="",
            created_at=now,
            updated_at=now,
            reviewed_at=None,
            reviewed_by_account_id=None,
        )
        with self.session_factory.begin() as database_session:
            database_session.add(row)
            database_session.flush()
            return self._to_feedback(row)

    def get_owned(self, feedback_id: UUID, *, account_id: UUID) -> ProductFeedback | None:
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(ProductFeedbackRow).where(
                    ProductFeedbackRow.id == str(feedback_id),
                    ProductFeedbackRow.account_id == str(account_id),
                )
            )
            return self._to_feedback(row) if row else None

    def list_for_account(self, account_id: UUID, *, limit: int = 100) -> list[ProductFeedback]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ProductFeedbackRow)
                .where(ProductFeedbackRow.account_id == str(account_id))
                .order_by(ProductFeedbackRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._to_feedback(row) for row in rows]

    def list_recent(self, *, limit: int = 200) -> list[ProductFeedback]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ProductFeedbackRow)
                .order_by(ProductFeedbackRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._to_feedback(row) for row in rows]

    def counts_by_account(self) -> dict[UUID, int]:
        with self.session_factory() as database_session:
            rows = database_session.execute(
                select(ProductFeedbackRow.account_id, func.count(ProductFeedbackRow.id)).group_by(
                    ProductFeedbackRow.account_id
                )
            ).all()
            return {UUID(account_id): int(count) for account_id, count in rows}

    def review(
        self,
        feedback_id: UUID,
        *,
        status: FeedbackStatus,
        reviewer_account_id: UUID,
        operator_note: str,
    ) -> ProductFeedback:
        clean_note = " ".join(operator_note.split())
        if len(clean_note) > MAX_FEEDBACK_NOTE_LENGTH:
            raise ProductFeedbackError(
                f"Keep the internal note to {MAX_FEEDBACK_NOTE_LENGTH:,} characters or fewer."
            )
        now = utc_now()
        with self.session_factory.begin() as database_session:
            row = database_session.scalar(
                select(ProductFeedbackRow)
                .where(ProductFeedbackRow.id == str(feedback_id))
                .with_for_update()
            )
            if row is None:
                raise ProductFeedbackError("Feedback not found.")
            row.status = status.value
            row.operator_note = clean_note
            row.updated_at = now
            row.reviewed_at = now
            row.reviewed_by_account_id = str(reviewer_account_id)
            database_session.flush()
            return self._to_feedback(row)

    def delete_owned(self, feedback_id: UUID, *, account_id: UUID) -> bool:
        with self.session_factory.begin() as database_session:
            result = database_session.execute(
                delete(ProductFeedbackRow).where(
                    ProductFeedbackRow.id == str(feedback_id),
                    ProductFeedbackRow.account_id == str(account_id),
                )
            )
            return bool(result.rowcount)
