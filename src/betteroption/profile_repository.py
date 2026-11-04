"""Database-backed profile workspaces and conversation history."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .profile import ProfileSection, StrictModel
from .profile_mobility import canonicalize_profile_mobility_facts
from .session import ProfileSession, load_session, new_session


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ConversationRole(StrEnum):
    ASSISTANT = "assistant"
    USER = "user"


class ProfileWorkspaceRow(Base):
    __tablename__ = "profile_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    persona_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("account_personas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_json: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationMessageRow(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileWorkspace(StrictModel):
    id: UUID
    account_id: UUID | None = None
    persona_id: UUID | None = None
    session: ProfileSession
    active: bool
    created_at: datetime
    updated_at: datetime


class ConversationMessage(StrictModel):
    id: UUID
    workspace_id: UUID
    section: ProfileSection | None = None
    role: ConversationRole
    content: str
    created_at: datetime


class ProfileWorkspaceRepository:
    """Persist the complete typed profile session and its conversational context."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_workspace(row: ProfileWorkspaceRow) -> ProfileWorkspace:
        workspace = ProfileWorkspace(
            id=UUID(row.id),
            account_id=UUID(row.account_id) if row.account_id else None,
            persona_id=UUID(row.persona_id) if row.persona_id else None,
            session=ProfileSession.model_validate_json(row.session_json),
            active=row.active,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )
        canonicalize_profile_mobility_facts(workspace.session.profile)
        return workspace

    @staticmethod
    def _to_message(row: ConversationMessageRow) -> ConversationMessage:
        return ConversationMessage(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            section=ProfileSection(row.section) if row.section else None,
            role=ConversationRole(row.role),
            content=row.content,
            created_at=ensure_utc(row.created_at),
        )

    def create(
        self,
        profile_session: ProfileSession | None = None,
        *,
        account_id: UUID | None = None,
        persona_id: UUID | None = None,
    ) -> ProfileWorkspace:
        profile_session = profile_session or new_session()
        now = utc_now()
        with self.session_factory.begin() as database_session:
            if persona_id is not None:
                from .personas import AccountPersonaRow

                persona = database_session.get(AccountPersonaRow, str(persona_id))
                if persona is None or account_id is None or persona.account_id != str(account_id):
                    raise ValueError("Persona does not belong to the selected account.")
            active_query = select(ProfileWorkspaceRow).where(ProfileWorkspaceRow.active.is_(True))
            if account_id is not None:
                active_query = active_query.where(ProfileWorkspaceRow.account_id == str(account_id))
            if persona_id is not None:
                active_query = active_query.where(ProfileWorkspaceRow.persona_id == str(persona_id))
            elif account_id is None:
                active_query = active_query.where(ProfileWorkspaceRow.persona_id.is_(None))
            for row in database_session.scalars(active_query):
                row.active = False
            row = ProfileWorkspaceRow(
                id=str(profile_session.id),
                account_id=str(account_id) if account_id else None,
                persona_id=str(persona_id) if persona_id else None,
                session_json=profile_session.model_dump_json(),
                active=True,
                created_at=now,
                updated_at=now,
            )
            database_session.add(row)
            database_session.flush()
            return self._to_workspace(row)

    def get(
        self,
        workspace_id: UUID,
        *,
        account_id: UUID | None = None,
        persona_id: UUID | None = None,
    ) -> ProfileWorkspace | None:
        with self.session_factory() as database_session:
            row = database_session.get(ProfileWorkspaceRow, str(workspace_id))
            if row is not None and account_id is not None and row.account_id != str(account_id):
                return None
            if row is not None and persona_id is not None and row.persona_id != str(persona_id):
                return None
            return self._to_workspace(row) if row else None

    def latest(
        self,
        *,
        account_id: UUID | None = None,
        persona_id: UUID | None = None,
    ) -> ProfileWorkspace | None:
        with self.session_factory() as database_session:
            query = select(ProfileWorkspaceRow)
            if account_id is not None:
                query = query.where(ProfileWorkspaceRow.account_id == str(account_id))
            if persona_id is not None:
                query = query.where(ProfileWorkspaceRow.persona_id == str(persona_id))
            row = database_session.scalar(
                query.order_by(
                    ProfileWorkspaceRow.active.desc(),
                    ProfileWorkspaceRow.updated_at.desc(),
                )
            )
            return self._to_workspace(row) if row else None

    def list_all(
        self,
        *,
        account_id: UUID | None = None,
        persona_id: UUID | None = None,
    ) -> list[ProfileWorkspace]:
        with self.session_factory() as database_session:
            query = select(ProfileWorkspaceRow)
            if account_id is not None:
                query = query.where(ProfileWorkspaceRow.account_id == str(account_id))
            if persona_id is not None:
                query = query.where(ProfileWorkspaceRow.persona_id == str(persona_id))
            rows = database_session.scalars(
                query.order_by(ProfileWorkspaceRow.created_at.asc())
            ).all()
            return [self._to_workspace(row) for row in rows]

    def save(self, workspace: ProfileWorkspace) -> ProfileWorkspace:
        with self.session_factory.begin() as database_session:
            row = database_session.get(ProfileWorkspaceRow, str(workspace.id))
            if row is None:
                raise KeyError(f"unknown profile workspace: {workspace.id}")
            row.session_json = workspace.session.model_dump_json()
            row.active = workspace.active
            row.updated_at = utc_now()
            database_session.flush()
            return self._to_workspace(row)

    def add_message(
        self,
        workspace_id: UUID,
        role: ConversationRole,
        content: str,
        *,
        section: ProfileSection | None = None,
    ) -> ConversationMessage:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("conversation content must not be empty")
        with self.session_factory.begin() as database_session:
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            row = ConversationMessageRow(
                id=str(uuid4()),
                workspace_id=str(workspace_id),
                section=section.value if section else None,
                role=role.value,
                content=clean_content,
                created_at=utc_now(),
            )
            database_session.add(row)
            database_session.flush()
            return self._to_message(row)

    def messages(self, workspace_id: UUID) -> list[ConversationMessage]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(ConversationMessageRow)
                .where(ConversationMessageRow.workspace_id == str(workspace_id))
                .order_by(ConversationMessageRow.created_at.asc())
            ).all()
            return [self._to_message(row) for row in rows]

    def adopt_latest_file(self, directory: Path) -> ProfileWorkspace | None:
        """Import one legacy JSON checkpoint only when the database has no profile."""

        existing = self.latest()
        if existing is not None:
            return existing
        paths = list(directory.glob("session-*.json")) if directory.exists() else []
        if not paths:
            return None
        latest_path = max(paths, key=lambda item: item.stat().st_mtime)
        workspace = self.create(load_session(latest_path))
        section = next(
            (
                progress.section
                for progress in workspace.session.sections
                if progress.status.value in {"pending", "review_pending"}
            ),
            None,
        )
        self.add_message(
            workspace.id,
            ConversationRole.ASSISTANT,
            "Your existing profile checkpoint is now safely stored in the database.",
            section=section,
        )
        return workspace
