"""Operator-entered billing periods correlated with privacy-safe provider metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator
from sqlalchemy import DateTime, Float, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .operations import ProviderOperationLedger, ProviderOperationSummary
from .profile import StrictModel


class ProviderBillingPeriodRow(Base):
    __tablename__ = "provider_billing_periods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    billed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderBillingPeriod(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    provider: str
    period_start: datetime
    period_end: datetime
    billed_amount: float = Field(ge=0)
    currency: str = "USD"
    source_label: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("provider")
    @classmethod
    def clean_provider(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Select or enter a provider.")
        return clean

    @field_validator("currency")
    @classmethod
    def clean_currency(cls, value: str) -> str:
        clean = value.strip().upper()
        if len(clean) != 3 or not clean.isalpha():
            raise ValueError("Currency must use a three-letter code such as EUR or USD.")
        return clean

    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end <= self.period_start:
            raise ValueError("Billing period end must be after its start.")
        return self


class BillingCalibrationReport(StrictModel):
    period: ProviderBillingPeriod
    usage: ProviderOperationSummary
    effective_cost_per_operation: float | None = None
    effective_cost_per_unit: float | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ProviderBillingPeriodRepository:
    def __init__(self, database: Database, ledger: ProviderOperationLedger) -> None:
        self.database = database
        self.ledger = ledger

    @staticmethod
    def _model(row: ProviderBillingPeriodRow) -> ProviderBillingPeriod:
        return ProviderBillingPeriod(
            id=UUID(row.id),
            provider=row.provider,
            period_start=_utc(row.period_start),
            period_end=_utc(row.period_end),
            billed_amount=row.billed_amount,
            currency=row.currency,
            source_label=row.source_label,
            created_at=_utc(row.created_at),
        )

    def add(self, period: ProviderBillingPeriod) -> ProviderBillingPeriod:
        with self.database.session_factory.begin() as session:
            session.add(
                ProviderBillingPeriodRow(
                    id=str(period.id),
                    provider=period.provider,
                    period_start=period.period_start,
                    period_end=period.period_end,
                    billed_amount=period.billed_amount,
                    currency=period.currency,
                    source_label=period.source_label,
                    created_at=period.created_at,
                )
            )
        return period

    def delete(self, period_id: UUID) -> bool:
        with self.database.session_factory.begin() as session:
            row = session.get(ProviderBillingPeriodRow, str(period_id))
            if row is None:
                return False
            session.delete(row)
            return True

    def list_reports(self, *, limit: int = 50) -> list[BillingCalibrationReport]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(ProviderBillingPeriodRow)
                .order_by(ProviderBillingPeriodRow.period_end.desc())
                .limit(limit)
            ).all()
        reports = []
        for row in rows:
            period = self._model(row)
            usage = self.ledger.summary_between(
                period.period_start,
                period.period_end,
                provider=period.provider,
            )
            reports.append(
                BillingCalibrationReport(
                    period=period,
                    usage=usage,
                    effective_cost_per_operation=(
                        period.billed_amount / usage.total_operations
                        if usage.total_operations
                        else None
                    ),
                    effective_cost_per_unit=(
                        period.billed_amount / usage.unit_count if usage.unit_count else None
                    ),
                )
            )
        return reports
