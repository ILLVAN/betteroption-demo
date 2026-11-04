"""Persona-owned employer reputation ratings.

The public company research result remains attributed evidence.  This module
stores a separate, private assessment chosen directly by a candidate.  A
rating follows the normalized employer name across all jobs owned by the same
persona and is never shared with another persona or account.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .personas import AccountPersonaRow
from .profile import StrictModel


EMPLOYER_NAME_MAX_LENGTH = 300
UNRESOLVED_EMPLOYER_KEYS = frozenset(
    {
        "unknown",
        "not stated",
        "company not stated",
        "employer not stated",
        "traceable company",
        "external source",
        "career portal",
        "custom portal",
        "job portal",
        "manual input",
        "manual source",
        "portal source",
        "public source",
        "saved employer portal",
        "source website",
        "unavailable",
        "n a",
        "none",
    }
)


class EmployerReputationError(ValueError):
    """Raised for invalid ratings or access outside the owning account."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_employer_name(value: str) -> tuple[str, str]:
    """Return a safe display name and stable equality key.

    This is intentionally normalization rather than entity resolution: case,
    Unicode presentation, whitespace, punctuation, and dotted legal forms are
    made stable, but distinct legal names are not guessed to be the same
    company.  For example, ``othermo GmbH`` and ``OTHERMO G.m.b.H.`` share a
    key, while ``Example GmbH`` and ``Example AG`` do not.
    """

    display = " ".join(unicodedata.normalize("NFKC", value).split())
    if not display:
        raise EmployerReputationError("Employer name is required.")
    if len(display) > EMPLOYER_NAME_MAX_LENGTH:
        raise EmployerReputationError(
            f"Employer names may contain at most {EMPLOYER_NAME_MAX_LENGTH} characters."
        )
    if any(unicodedata.category(character).startswith("C") for character in display):
        raise EmployerReputationError("Employer name contains unsupported control characters.")

    # Treat punctuation and symbols as token boundaries.  The ampersand is a
    # meaningful word so A&B and A & B converge without being collapsed to AB.
    normalized = display.casefold().replace("&", " and ")
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    key = " ".join(tokens)
    # Corporate forms are frequently written with or without dots.  Compact
    # only exact trailing legal-form token sequences; arbitrary words remain
    # untouched to avoid speculative company/entity matching.
    legal_forms = {
        ("g", "m", "b", "h"): "gmbh",
        ("a", "g"): "ag",
        ("s", "e"): "se",
        ("u", "g"): "ug",
        ("l", "l", "c"): "llc",
        ("l", "t", "d"): "ltd",
        ("i", "n", "c"): "inc",
    }
    for parts, compact in legal_forms.items():
        if tuple(tokens[-len(parts) :]) == parts:
            tokens[-len(parts) :] = [compact]
            key = " ".join(tokens)
            break
    if not key:
        raise EmployerReputationError("Employer name must contain letters or numbers.")
    return display, key


def resolved_employer_name(value: str | None) -> str | None:
    """Return a rateable employer name, excluding generic source placeholders."""

    if not value:
        return None
    try:
        display, key = normalize_employer_name(value)
    except EmployerReputationError:
        return None
    if (
        key in UNRESOLVED_EMPLOYER_KEYS
        or key.startswith("unknown ")
        or key.endswith(" not stated")
        or re.fullmatch(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+", display.casefold())
    ):
        return None
    return display


class EmployerReputationRatingRow(Base):
    __tablename__ = "persona_employer_reputation_ratings"
    __table_args__ = (
        UniqueConstraint(
            "persona_id",
            "employer_key",
            name="uq_persona_employer_reputation_ratings_company",
        ),
        CheckConstraint(
            "stars >= 0 AND stars <= 5",
            name="ck_persona_employer_reputation_ratings_stars",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    persona_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employer_key: Mapped[str] = mapped_column(String(EMPLOYER_NAME_MAX_LENGTH), nullable=False)
    employer_name: Mapped[str] = mapped_column(String(EMPLOYER_NAME_MAX_LENGTH), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployerReputationRating(StrictModel):
    id: UUID
    persona_id: UUID
    employer_key: str
    employer_name: str
    stars: int = Field(ge=0, le=5)
    created_at: datetime
    updated_at: datetime


class EmployerReputationRepository:
    """Store one private 0–5 star company rating per persona.

    Every method checks that ``persona_id`` belongs to ``account_id``. Zero is
    an explicit candidate judgement and therefore remains stored; callers use
    :meth:`clear` to return the employer to the distinct unrated state.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_rating(row: EmployerReputationRatingRow) -> EmployerReputationRating:
        return EmployerReputationRating(
            id=UUID(row.id),
            persona_id=UUID(row.persona_id),
            employer_key=row.employer_key,
            employer_name=row.employer_name,
            stars=row.stars,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    @staticmethod
    def _owned_persona(session, persona_id: UUID, account_id: UUID) -> AccountPersonaRow:
        persona = session.get(AccountPersonaRow, str(persona_id))
        if persona is None or persona.account_id != str(account_id):
            raise EmployerReputationError("Persona not found.")
        return persona

    def get(
        self,
        persona_id: UUID,
        employer_name: str,
        *,
        account_id: UUID,
    ) -> EmployerReputationRating | None:
        _, employer_key = normalize_employer_name(employer_name)
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.scalar(
                select(EmployerReputationRatingRow).where(
                    EmployerReputationRatingRow.persona_id == str(persona_id),
                    EmployerReputationRatingRow.employer_key == employer_key,
                )
            )
            return self._to_rating(row) if row is not None else None

    def list_for_persona(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
    ) -> list[EmployerReputationRating]:
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            rows = session.scalars(
                select(EmployerReputationRatingRow)
                .where(EmployerReputationRatingRow.persona_id == str(persona_id))
                .order_by(
                    EmployerReputationRatingRow.employer_name.asc(),
                    EmployerReputationRatingRow.id.asc(),
                )
            ).all()
            return [self._to_rating(row) for row in rows]

    def set_rating(
        self,
        persona_id: UUID,
        employer_name: str,
        stars: int,
        *,
        account_id: UUID,
    ) -> EmployerReputationRating:
        """Create or update an explicit 0–5 star rating."""

        if isinstance(stars, bool) or not isinstance(stars, int) or not 0 <= stars <= 5:
            raise EmployerReputationError("Choose an employer rating from 0 to 5 stars.")
        display_name, employer_key = normalize_employer_name(employer_name)
        now = utc_now()
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.scalar(
                select(EmployerReputationRatingRow).where(
                    EmployerReputationRatingRow.persona_id == str(persona_id),
                    EmployerReputationRatingRow.employer_key == employer_key,
                )
            )
            if row is None:
                row = EmployerReputationRatingRow(
                    id=str(uuid4()),
                    persona_id=str(persona_id),
                    employer_key=employer_key,
                    employer_name=display_name,
                    stars=stars,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                # Keep the latest human-readable spelling from a current job,
                # while preserving the stable normalized identity and row id.
                row.employer_name = display_name
                row.stars = stars
                row.updated_at = now
            session.flush()
            return self._to_rating(row)

    def clear(
        self,
        persona_id: UUID,
        employer_name: str,
        *,
        account_id: UUID,
    ) -> bool:
        _, employer_key = normalize_employer_name(employer_name)
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.scalar(
                select(EmployerReputationRatingRow).where(
                    EmployerReputationRatingRow.persona_id == str(persona_id),
                    EmployerReputationRatingRow.employer_key == employer_key,
                )
            )
            if row is None:
                return False
            session.delete(row)
            return True
