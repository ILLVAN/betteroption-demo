"""Persona-owned ratings of individual saved jobs.

These judgements are distinct from employer reputation: a candidate may like a
company but dislike one role, or vice versa. Zero is an explicit rating;
absence of a row is the separate neutral/unrated state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .job_repository import JobRecordRow
from .personas import AccountPersonaRow
from .profile import StrictModel


class PersonaJobRatingError(ValueError):
    """Raised for invalid ratings or access outside the owning account."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PersonaJobRatingRow(Base):
    __tablename__ = "persona_job_ratings"
    __table_args__ = (
        UniqueConstraint(
            "persona_id",
            "job_record_id",
            name="uq_persona_job_ratings_job",
        ),
        CheckConstraint(
            "stars >= 0 AND stars <= 5",
            name="ck_persona_job_ratings_stars",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    persona_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonaJobRating(StrictModel):
    id: UUID
    persona_id: UUID
    job_record_id: UUID
    stars: int = Field(ge=0, le=5)
    created_at: datetime
    updated_at: datetime


class PersonaJobRatingRepository:
    """Store an explicit 0–5 rating per persona and saved job."""

    def __init__(self, database: Database) -> None:
        self.session_factory = database.session_factory

    @staticmethod
    def _owned_persona(session, persona_id: UUID, account_id: UUID) -> None:
        persona = session.get(AccountPersonaRow, str(persona_id))
        if persona is None or persona.account_id != str(account_id):
            raise PersonaJobRatingError("Persona not found.")

    @staticmethod
    def _to_model(row: PersonaJobRatingRow) -> PersonaJobRating:
        return PersonaJobRating(
            id=UUID(row.id),
            persona_id=UUID(row.persona_id),
            job_record_id=UUID(row.job_record_id),
            stars=row.stars,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    def get(
        self,
        persona_id: UUID,
        job_record_id: UUID,
        *,
        account_id: UUID,
    ) -> PersonaJobRating | None:
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.scalar(
                select(PersonaJobRatingRow).where(
                    PersonaJobRatingRow.persona_id == str(persona_id),
                    PersonaJobRatingRow.job_record_id == str(job_record_id),
                )
            )
            return self._to_model(row) if row is not None else None

    def list_for_jobs(
        self,
        persona_id: UUID,
        job_record_ids: set[UUID],
        *,
        account_id: UUID,
    ) -> dict[UUID, PersonaJobRating]:
        if not job_record_ids:
            return {}
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            rows = session.scalars(
                select(PersonaJobRatingRow).where(
                    PersonaJobRatingRow.persona_id == str(persona_id),
                    PersonaJobRatingRow.job_record_id.in_([str(value) for value in job_record_ids]),
                )
            ).all()
            return {UUID(row.job_record_id): self._to_model(row) for row in rows}

    def list_for_persona(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
    ) -> list[PersonaJobRating]:
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            rows = session.scalars(
                select(PersonaJobRatingRow)
                .where(PersonaJobRatingRow.persona_id == str(persona_id))
                .order_by(PersonaJobRatingRow.updated_at.desc())
            ).all()
            return [self._to_model(row) for row in rows]

    def set_rating(
        self,
        persona_id: UUID,
        job_record_id: UUID,
        stars: int,
        *,
        account_id: UUID,
    ) -> PersonaJobRating:
        if isinstance(stars, bool) or not isinstance(stars, int) or not 0 <= stars <= 5:
            raise PersonaJobRatingError("Choose a job rating from 0 to 5 stars.")
        now = utc_now()
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            if session.get(JobRecordRow, str(job_record_id)) is None:
                raise PersonaJobRatingError("Job not found.")
            row = session.scalar(
                select(PersonaJobRatingRow).where(
                    PersonaJobRatingRow.persona_id == str(persona_id),
                    PersonaJobRatingRow.job_record_id == str(job_record_id),
                )
            )
            if row is None:
                row = PersonaJobRatingRow(
                    id=str(uuid4()),
                    persona_id=str(persona_id),
                    job_record_id=str(job_record_id),
                    stars=stars,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.stars = stars
                row.updated_at = now
            session.flush()
            return self._to_model(row)

    def clear(
        self,
        persona_id: UUID,
        job_record_id: UUID,
        *,
        account_id: UUID,
    ) -> bool:
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.scalar(
                select(PersonaJobRatingRow).where(
                    PersonaJobRatingRow.persona_id == str(persona_id),
                    PersonaJobRatingRow.job_record_id == str(job_record_id),
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True
