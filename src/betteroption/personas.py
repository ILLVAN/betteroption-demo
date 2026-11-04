"""Account-owned, passwordless persona slots."""

from __future__ import annotations

from datetime import datetime, timezone
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .profile import StrictModel


PERSONA_NAME_MAX_LENGTH = 40


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PersonaError(ValueError):
    """Raised when an account-owned persona action is invalid."""


def normalize_persona_name(value: str) -> tuple[str, str]:
    display = " ".join(unicodedata.normalize("NFKC", value).split())
    if not display:
        raise PersonaError("Enter a persona name.")
    if len(display) > PERSONA_NAME_MAX_LENGTH:
        raise PersonaError(f"Use at most {PERSONA_NAME_MAX_LENGTH} characters for a persona name.")
    if any(unicodedata.category(character).startswith("C") for character in display):
        raise PersonaError("That persona name contains unsupported control characters.")
    return display, display.casefold()


class AccountPersonaRow(Base):
    __tablename__ = "account_personas"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "name_normalized",
            name="uq_account_personas_account_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(PERSONA_NAME_MAX_LENGTH), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(PERSONA_NAME_MAX_LENGTH), nullable=False)
    also_update_compass_skills: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountPersona(StrictModel):
    id: UUID
    account_id: UUID
    name: str
    also_update_compass_skills: bool = True
    created_at: datetime
    updated_at: datetime


class PersonaRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_persona(row: AccountPersonaRow) -> AccountPersona:
        return AccountPersona(
            id=UUID(row.id),
            account_id=UUID(row.account_id),
            name=row.name,
            also_update_compass_skills=row.also_update_compass_skills,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    def list_for_account(self, account_id: UUID) -> list[AccountPersona]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(AccountPersonaRow)
                .where(AccountPersonaRow.account_id == str(account_id))
                .order_by(AccountPersonaRow.created_at.asc())
            ).all()
            return [self._to_persona(row) for row in rows]

    def get(self, persona_id: UUID, *, account_id: UUID) -> AccountPersona | None:
        with self.session_factory() as database_session:
            row = database_session.get(AccountPersonaRow, str(persona_id))
            if row is None or row.account_id != str(account_id):
                return None
            return self._to_persona(row)

    def first(self, account_id: UUID) -> AccountPersona | None:
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(AccountPersonaRow)
                .where(AccountPersonaRow.account_id == str(account_id))
                .order_by(AccountPersonaRow.created_at.asc())
            )
            return self._to_persona(row) if row else None

    def create(
        self,
        account_id: UUID,
        name: str,
        *,
        maximum_personas: int,
    ) -> AccountPersona:
        display_name, normalized_name = normalize_persona_name(name)
        now = utc_now()
        try:
            with self.session_factory.begin() as database_session:
                # Serialize slot allocation per account on databases that support
                # row locks, so two concurrent requests cannot both create slot 5.
                from .accounts import AccountRow

                owner = database_session.scalar(
                    select(AccountRow).where(AccountRow.id == str(account_id)).with_for_update()
                )
                if owner is None:
                    raise PersonaError("Account not found.")
                count = int(
                    database_session.scalar(
                        select(func.count(AccountPersonaRow.id)).where(
                            AccountPersonaRow.account_id == str(account_id)
                        )
                    )
                    or 0
                )
                if count >= maximum_personas:
                    raise PersonaError(
                        f"This account can keep up to {maximum_personas} personas. "
                        "Delete one before creating another."
                    )
                row = AccountPersonaRow(
                    id=str(uuid4()),
                    account_id=str(account_id),
                    name=display_name,
                    name_normalized=normalized_name,
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
                database_session.flush()
                if count == 0:
                    from .profile_repository import ProfileWorkspaceRow

                    database_session.execute(
                        update(ProfileWorkspaceRow)
                        .where(
                            ProfileWorkspaceRow.account_id == str(account_id),
                            ProfileWorkspaceRow.persona_id.is_(None),
                        )
                        .values(persona_id=row.id)
                    )
                return self._to_persona(row)
        except IntegrityError as exc:
            raise PersonaError("That persona name is already in use for this account.") from exc

    def ensure_main(self, account_id: UUID, *, maximum_personas: int) -> AccountPersona:
        existing = self.first(account_id)
        if existing is not None:
            return existing
        return self.create(account_id, "Main", maximum_personas=maximum_personas)

    def rename(
        self,
        persona_id: UUID,
        name: str,
        *,
        account_id: UUID,
    ) -> AccountPersona:
        display_name, normalized_name = normalize_persona_name(name)
        try:
            with self.session_factory.begin() as database_session:
                row = database_session.get(AccountPersonaRow, str(persona_id))
                if row is None or row.account_id != str(account_id):
                    raise PersonaError("Persona not found.")
                row.name = display_name
                row.name_normalized = normalized_name
                row.updated_at = utc_now()
                database_session.flush()
                return self._to_persona(row)
        except IntegrityError as exc:
            raise PersonaError("That persona name is already in use for this account.") from exc

    def set_skill_compass_update_preference(
        self,
        persona_id: UUID,
        enabled: bool,
        *,
        account_id: UUID,
    ) -> AccountPersona:
        """Persist the required-skill-to-Compass choice for one owned persona."""

        with self.session_factory.begin() as database_session:
            row = database_session.get(AccountPersonaRow, str(persona_id))
            if row is None or row.account_id != str(account_id):
                raise PersonaError("Persona not found.")
            row.also_update_compass_skills = enabled
            row.updated_at = utc_now()
            database_session.flush()
            return self._to_persona(row)

    def delete(self, persona_id: UUID, *, account_id: UUID) -> AccountPersona | None:
        with self.session_factory.begin() as database_session:
            rows = database_session.scalars(
                select(AccountPersonaRow)
                .where(AccountPersonaRow.account_id == str(account_id))
                .order_by(AccountPersonaRow.created_at.asc())
            ).all()
            target = next((row for row in rows if row.id == str(persona_id)), None)
            if target is None:
                raise PersonaError("Persona not found.")
            if len(rows) <= 1:
                raise PersonaError(
                    "An account must keep at least one persona. Delete the account instead."
                )
            replacement = next(row for row in rows if row.id != target.id)
            database_session.execute(
                delete(AccountPersonaRow).where(AccountPersonaRow.id == target.id)
            )
            return self._to_persona(replacement)
