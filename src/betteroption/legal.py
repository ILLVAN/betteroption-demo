"""Versioned legal-document acknowledgements for controlled account registration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .profile import StrictModel


class LegalDocumentKind(StrEnum):
    TERMS = "terms"
    PRIVACY_NOTICE = "privacy_notice"


class LegalAcceptanceRow(Base):
    __tablename__ = "legal_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "document_kind",
            "document_version",
            name="uq_legal_acceptance_account_document_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    document_version: Mapped[str] = mapped_column(String(80), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LegalAcceptance(StrictModel):
    id: UUID
    account_id: UUID
    document_kind: LegalDocumentKind
    document_version: str
    accepted_at: datetime


class LegalStatus(StrictModel):
    terms_version: str
    privacy_version: str
    terms_accepted: bool
    privacy_acknowledged: bool
    acceptances: list[LegalAcceptance] = Field(default_factory=list)

    @property
    def current(self) -> bool:
        return self.terms_accepted and self.privacy_acknowledged


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class LegalAcceptanceRepository:
    """Store document versions without IP addresses, user agents, or profile content."""

    def __init__(
        self,
        database: Database,
        *,
        terms_version: str,
        privacy_version: str,
    ) -> None:
        self.database = database
        self.terms_version = terms_version
        self.privacy_version = privacy_version

    @staticmethod
    def _model(row: LegalAcceptanceRow) -> LegalAcceptance:
        return LegalAcceptance(
            id=UUID(row.id),
            account_id=UUID(row.account_id),
            document_kind=LegalDocumentKind(row.document_kind),
            document_version=row.document_version,
            accepted_at=_utc(row.accepted_at),
        )

    def record_current(self, account_id: UUID) -> LegalStatus:
        """Record acceptance of Terms and acknowledgement of the Privacy Notice."""

        now = datetime.now(timezone.utc)
        documents = (
            (LegalDocumentKind.TERMS, self.terms_version),
            (LegalDocumentKind.PRIVACY_NOTICE, self.privacy_version),
        )
        with self.database.session_factory.begin() as session:
            for kind, version in documents:
                existing = session.scalar(
                    select(LegalAcceptanceRow.id).where(
                        LegalAcceptanceRow.account_id == str(account_id),
                        LegalAcceptanceRow.document_kind == kind.value,
                        LegalAcceptanceRow.document_version == version,
                    )
                )
                if existing is None:
                    session.add(
                        LegalAcceptanceRow(
                            id=str(uuid4()),
                            account_id=str(account_id),
                            document_kind=kind.value,
                            document_version=version,
                            accepted_at=now,
                        )
                    )
        return self.status(account_id)

    def list_for_account(self, account_id: UUID) -> list[LegalAcceptance]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(LegalAcceptanceRow)
                .where(LegalAcceptanceRow.account_id == str(account_id))
                .order_by(LegalAcceptanceRow.accepted_at, LegalAcceptanceRow.document_kind)
            ).all()
        return [self._model(row) for row in rows]

    def status(self, account_id: UUID) -> LegalStatus:
        acceptances = self.list_for_account(account_id)
        return LegalStatus(
            terms_version=self.terms_version,
            privacy_version=self.privacy_version,
            terms_accepted=any(
                item.document_kind == LegalDocumentKind.TERMS
                and item.document_version == self.terms_version
                for item in acceptances
            ),
            privacy_acknowledged=any(
                item.document_kind == LegalDocumentKind.PRIVACY_NOTICE
                and item.document_version == self.privacy_version
                for item in acceptances
            ),
            acceptances=acceptances,
        )
