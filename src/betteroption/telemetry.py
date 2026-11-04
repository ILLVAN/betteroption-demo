"""Privacy-conscious persistence for language-model invocation metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .llm import InvocationOutcome, LLMTask, ModelInvocation, TokenUsage
from .operations import (
    ProviderBudgetPolicy,
    ProviderOperation,
    ProviderOperationLedger,
    ProviderOperationOutcome,
    ProviderOperationReservation,
)
from .llm import ModelRoute
from .profile import StrictModel


class ModelInvocationRow(Base):
    __tablename__ = "model_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)


class InvocationSummary(StrictModel):
    total_calls: int
    failed_calls: int
    total_tokens: int
    estimated_cost_usd: float


class SqlAlchemyInvocationRecorder:
    """Records operational metadata but never prompt or response content."""

    def __init__(
        self,
        database: Database,
        *,
        operation_ledger: ProviderOperationLedger | None = None,
        operation_budget: ProviderBudgetPolicy | None = None,
    ) -> None:
        self.database = database
        self.operation_budget = operation_budget
        self.operation_ledger = operation_ledger or (
            operation_budget.ledger if operation_budget is not None else None
        )

    def reserve(
        self,
        *,
        invocation_id: UUID,
        route: ModelRoute,
        attempt: int,
        started_at: datetime,
        input_token_ceiling: int,
        output_token_ceiling: int,
    ) -> bool:
        """Persist the maximum priced/token usage before one model attempt."""

        del attempt  # The stable invocation UUID distinguishes retry attempts.
        if self.operation_budget is None:
            return True
        input_ceiling = max(1, int(input_token_ceiling))
        output_ceiling = max(1, int(output_token_ceiling))
        maximum_cost: float | None = None
        if (
            route.input_cost_per_million_usd is not None
            and route.output_cost_per_million_usd is not None
            and route.input_cost_per_million_usd > 0
            and route.output_cost_per_million_usd > 0
        ):
            maximum_cost = round(
                input_ceiling * route.input_cost_per_million_usd / 1_000_000
                + output_ceiling * route.output_cost_per_million_usd / 1_000_000,
                8,
            )
        return (
            self.operation_budget.reserve(
                operation_id=invocation_id,
                provider=route.provider,
                purpose=f"llm:{route.task.value}",
                started_at=started_at,
                unit_count=input_ceiling + output_ceiling,
                unit_name="token",
                estimated_cost_usd=maximum_cost,
                proposed_operation_count=1,
            )
            is not None
        )

    def record(self, invocation: ModelInvocation) -> None:
        usage = invocation.usage
        row = ModelInvocationRow(
            id=str(invocation.id),
            task=invocation.task.value,
            provider=invocation.provider,
            model=invocation.model,
            prompt_version=invocation.prompt_version,
            attempt=invocation.attempt,
            outcome=invocation.outcome.value,
            started_at=invocation.started_at,
            finished_at=invocation.finished_at,
            latency_ms=invocation.latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            estimated_cost_usd=invocation.estimated_cost_usd,
            error_type=invocation.error_type,
        )
        try:
            with self.database.session_factory.begin() as session:
                session.add(row)
        except Exception:
            # Telemetry is intentionally fail-open and must never block a user workflow.
            pass
        if self.operation_ledger is not None:
            outcome = (
                ProviderOperationOutcome.SUCCEEDED
                if invocation.outcome == InvocationOutcome.SUCCEEDED
                else ProviderOperationOutcome.FAILED
            )
            finalized = self.operation_ledger.finalize_reservation(
                ProviderOperationReservation(
                    id=invocation.id,
                    reserved_unit_count=0,
                ),
                outcome=outcome,
                finished_at=invocation.finished_at,
                latency_ms=invocation.latency_ms,
                actual_unit_count=usage.total_tokens,
                actual_cost_usd=invocation.estimated_cost_usd,
                usage_known=usage.total_tokens is not None,
                result_count=(1 if invocation.outcome == InvocationOutcome.SUCCEEDED else 0),
                error_type=invocation.error_type,
            )
            if not finalized:
                # Compatibility path for non-authorizing recorders and older
                # direct tests. A still-Pending row rejects this duplicate id
                # and therefore conservatively keeps its maximum reservation.
                self.operation_ledger.record(
                    ProviderOperation(
                        id=invocation.id,
                        provider=invocation.provider,
                        purpose=f"llm:{invocation.task.value}",
                        outcome=outcome,
                        started_at=invocation.started_at,
                        finished_at=invocation.finished_at,
                        latency_ms=invocation.latency_ms,
                        unit_count=usage.total_tokens or 0,
                        unit_name="token",
                        result_count=(
                            1 if invocation.outcome == InvocationOutcome.SUCCEEDED else 0
                        ),
                        estimated_cost_usd=invocation.estimated_cost_usd,
                        error_type=invocation.error_type,
                    )
                )

    def list_recent(self, *, limit: int = 50) -> list[ModelInvocation]:
        with self.database.session_factory() as session:
            rows = session.scalars(
                select(ModelInvocationRow)
                .order_by(ModelInvocationRow.started_at.desc())
                .limit(limit)
            ).all()
        return [self._to_domain(row) for row in rows]

    def summary(self) -> InvocationSummary:
        with self.database.session_factory() as session:
            total_calls = session.scalar(select(func.count(ModelInvocationRow.id))) or 0
            failed_calls = (
                session.scalar(
                    select(func.count(ModelInvocationRow.id)).where(
                        ModelInvocationRow.outcome == InvocationOutcome.FAILED.value
                    )
                )
                or 0
            )
            total_tokens = session.scalar(
                select(func.coalesce(func.sum(ModelInvocationRow.total_tokens), 0))
            )
            estimated_cost = session.scalar(
                select(func.coalesce(func.sum(ModelInvocationRow.estimated_cost_usd), 0.0))
            )
        return InvocationSummary(
            total_calls=int(total_calls),
            failed_calls=int(failed_calls),
            total_tokens=int(total_tokens or 0),
            estimated_cost_usd=float(estimated_cost or 0),
        )

    @staticmethod
    def _to_domain(row: ModelInvocationRow) -> ModelInvocation:
        return ModelInvocation(
            id=UUID(row.id),
            task=LLMTask(row.task),
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            attempt=row.attempt,
            outcome=InvocationOutcome(row.outcome),
            started_at=row.started_at,
            finished_at=row.finished_at,
            latency_ms=row.latency_ms,
            usage=TokenUsage(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.total_tokens,
            ),
            estimated_cost_usd=row.estimated_cost_usd,
            error_type=row.error_type,
        )
