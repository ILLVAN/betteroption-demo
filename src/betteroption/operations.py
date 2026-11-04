"""Privacy-safe provider operation accounting and private-alpha budgets."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import StrEnum
from threading import Lock
from time import perf_counter
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    case,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from .company_intelligence import CompanyResearchHit, CompanyResearchProvider
from .concurrency import CooperativeControlFlow, check_cooperative_control
from .database import Base, Database
from .discovery import (
    DiscoveredJob,
    DiscoveryError,
    DiscoveryQuery,
    JobDiscoveryProvider,
)
from .profile import StrictModel
from .jobs import JobPosting
from .provider_permissions import current_provider_account_id, provider_permission_allowed
from .salary import SalaryBenchmarkProvider, SalaryResearchResult


_workflow_id: ContextVar[UUID | None] = ContextVar("provider_workflow_id", default=None)
_workflow_type: ContextVar[str | None] = ContextVar("provider_workflow_type", default=None)
_USE_CONFIGURED_COST = object()
_BUDGET_ADVISORY_LOCK_KEY = 7_204_617_096_823_911_337
_sqlite_lock_registry_guard = Lock()
_sqlite_locks: dict[str, Lock] = {}


@contextmanager
def provider_operation_scope(workflow_id: UUID, workflow_type: str):
    """Correlate metadata-only provider work without retaining workflow payloads."""

    id_token = _workflow_id.set(workflow_id)
    type_token = _workflow_type.set(workflow_type)
    try:
        yield
    finally:
        _workflow_type.reset(type_token)
        _workflow_id.reset(id_token)


def current_provider_workflow_id() -> UUID | None:
    """Return the opaque workflow correlation id without exposing its payload."""

    return _workflow_id.get()


class ProviderOperationOutcome(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class BudgetDecision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class ProviderBudgetPersistenceError(RuntimeError):
    """Fail-closed signal when durable pre-call authorization cannot be stored."""


class ProviderOperationReservation(StrictModel):
    """Opaque handle for finalizing one durable pre-call reservation."""

    id: UUID
    reserved_unit_count: int = Field(ge=0)
    reserved_cost_usd: float | None = Field(default=None, ge=0)


class ProviderOperation(StrictModel):
    """Operational metadata only; request and response contents are forbidden."""

    id: UUID = Field(default_factory=uuid4)
    provider: str
    purpose: str
    outcome: ProviderOperationOutcome
    budget_decision: BudgetDecision = BudgetDecision.ALLOWED
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    unit_count: int = 1
    unit_name: str = "operation"
    result_count: int = 0
    estimated_cost_usd: float | None = None
    error_type: str | None = None
    cache_hit: bool = False
    workflow_id: UUID | None = None
    workflow_type: str | None = None
    account_id: UUID | None = None


class ProviderOperationRow(Base):
    __tablename__ = "provider_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    budget_decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_name: Mapped[str] = mapped_column(String(40), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    workflow_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)


class ProviderOperationSummary(StrictModel):
    total_operations: int = 0
    failed_operations: int = 0
    blocked_operations: int = 0
    pending_operations: int = 0
    unit_count: int = 0
    result_count: int = 0
    estimated_cost_usd: float = 0
    costed_operations: int = 0
    unpriced_operations: int = 0


class ProviderBudgetUsage(StrictModel):
    """Provider calls and priced usage that consume configured budget rails.

    Public operation summaries deliberately retain their historical row and
    provider-unit semantics.  Budget authorization needs a different measure:
    one external HTTP request consumes one operation, while token and batch
    telemetry rows consume one operation regardless of their provider units.
    """

    operation_count: int = 0
    estimated_cost_usd: float = 0


class ProviderOperationBreakdown(ProviderOperationSummary):
    """Aggregated operational facts for one provider and purpose."""

    provider: str
    purpose: str
    average_latency_ms: int = 0
    cache_hits: int = 0
    failure_types: list[str] = Field(default_factory=list)


class ProviderOperationLedger:
    """Privacy-safe provider accounting without request or response payloads.

    Pre-call reservation is fail-closed. Terminal telemetry remains fail-open:
    if its UPDATE cannot commit, the already durable Pending maximum stays in
    force instead of making a completed user workflow fail.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        dialect = self.database.engine.dialect.name
        if dialect == "sqlite":
            lock_key = str(self.database.engine.url)
            with _sqlite_lock_registry_guard:
                self._reservation_lock = _sqlite_locks.setdefault(lock_key, Lock())
        else:
            self._reservation_lock = Lock()

    def record(self, operation: ProviderOperation) -> None:
        if operation.workflow_id is None or operation.account_id is None:
            operation = operation.model_copy(
                update={
                    "workflow_id": operation.workflow_id or _workflow_id.get(),
                    "workflow_type": operation.workflow_type or _workflow_type.get(),
                    "account_id": operation.account_id or current_provider_account_id(),
                }
            )
        row = ProviderOperationRow(
            id=str(operation.id),
            account_id=str(operation.account_id) if operation.account_id else None,
            provider=operation.provider,
            purpose=operation.purpose,
            outcome=operation.outcome.value,
            budget_decision=operation.budget_decision.value,
            started_at=operation.started_at,
            finished_at=operation.finished_at,
            latency_ms=operation.latency_ms,
            unit_count=operation.unit_count,
            unit_name=operation.unit_name,
            result_count=operation.result_count,
            estimated_cost_usd=operation.estimated_cost_usd,
            error_type=operation.error_type,
            cache_hit=operation.cache_hit,
            workflow_id=str(operation.workflow_id) if operation.workflow_id else None,
            workflow_type=operation.workflow_type,
        )
        try:
            with self.database.session_factory.begin() as session:
                session.add(row)
        except Exception:
            # Accounting must not take down a job-search workflow.
            return

    def reserve_pending(
        self,
        *,
        operation_id: UUID,
        provider: str,
        purpose: str,
        started_at: datetime,
        unit_count: int,
        unit_name: str,
        estimated_cost_usd: float | None,
        proposed_operation_count: int,
        daily_operation_limit: int,
        daily_cost_limit_usd: float,
        action_operation_limit: int,
        action_cost_limit_usd: float,
        additional_daily_operations: int = 0,
        additional_daily_cost_usd: float = 0,
        additional_workflow_operations: int = 0,
        additional_workflow_cost_usd: float = 0,
    ) -> ProviderOperationReservation | None:
        """Atomically check durable totals and insert a pre-call reservation.

        PostgreSQL processes rendezvous on one transaction-scoped advisory
        lock. Local SQLite policies share a process lock and acquire an
        immediate write transaction before reading totals. A persistence or
        locking failure is deliberately fatal to authorization: no external
        provider call may start without its durable row.
        """

        workflow_id = _workflow_id.get()
        workflow_type = _workflow_type.get()
        account_id = current_provider_account_id()
        reserved_cost = (
            max(0.0, float(estimated_cost_usd)) if estimated_cost_usd is not None else None
        )
        reserved_units = max(0, int(unit_count))
        proposed_operations = max(1, int(proposed_operation_count))
        day_start = datetime(
            started_at.year,
            started_at.month,
            started_at.day,
            tzinfo=timezone.utc,
        )
        dialect = self.database.engine.dialect.name

        with self._reservation_lock:
            session = self.database.session_factory()
            try:
                if dialect == "sqlite":
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    session.begin()
                    if dialect == "postgresql":
                        session.execute(
                            text("SELECT pg_advisory_xact_lock(:lock_key)"),
                            {"lock_key": _BUDGET_ADVISORY_LOCK_KEY},
                        )

                if session.get(ProviderOperationRow, str(operation_id)) is not None:
                    raise ProviderBudgetPersistenceError("provider reservation id was already used")

                daily = self._budget_usage_in_session(session, since=day_start)
                workflow = (
                    self._budget_usage_in_session(session, workflow_id=workflow_id)
                    if workflow_id is not None
                    else ProviderBudgetUsage()
                )
                proposed_cost = reserved_cost or 0.0
                blocked = bool(
                    (
                        daily_operation_limit
                        and daily.operation_count
                        + additional_daily_operations
                        + proposed_operations
                        > daily_operation_limit
                    )
                    or (
                        daily_cost_limit_usd
                        and daily.estimated_cost_usd + additional_daily_cost_usd + proposed_cost
                        > daily_cost_limit_usd
                    )
                    or (
                        workflow_id is not None
                        and action_operation_limit
                        and workflow.operation_count
                        + additional_workflow_operations
                        + proposed_operations
                        > action_operation_limit
                    )
                    or (
                        workflow_id is not None
                        and action_cost_limit_usd
                        and workflow.estimated_cost_usd
                        + additional_workflow_cost_usd
                        + proposed_cost
                        > action_cost_limit_usd
                    )
                )
                session.add(
                    ProviderOperationRow(
                        id=str(operation_id),
                        account_id=str(account_id) if account_id else None,
                        provider=provider,
                        purpose=purpose,
                        outcome=(
                            ProviderOperationOutcome.BLOCKED.value
                            if blocked
                            else ProviderOperationOutcome.PENDING.value
                        ),
                        budget_decision=(
                            BudgetDecision.BLOCKED.value
                            if blocked
                            else BudgetDecision.ALLOWED.value
                        ),
                        started_at=started_at,
                        finished_at=started_at,
                        latency_ms=0,
                        unit_count=0 if blocked else reserved_units,
                        unit_name=unit_name,
                        result_count=0,
                        estimated_cost_usd=None if blocked else reserved_cost,
                        error_type="ProviderBudgetExceeded" if blocked else None,
                        cache_hit=False,
                        workflow_id=str(workflow_id) if workflow_id else None,
                        workflow_type=workflow_type,
                    )
                )
                session.commit()
            except ProviderBudgetPersistenceError:
                session.rollback()
                raise
            except Exception as exc:
                session.rollback()
                raise ProviderBudgetPersistenceError(
                    "provider budget authorization could not be persisted"
                ) from exc
            finally:
                session.close()

        if blocked:
            return None
        return ProviderOperationReservation(
            id=operation_id,
            reserved_unit_count=reserved_units,
            reserved_cost_usd=reserved_cost,
        )

    def finalize_reservation(
        self,
        reservation: ProviderOperationReservation,
        *,
        outcome: ProviderOperationOutcome,
        finished_at: datetime,
        latency_ms: int,
        result_count: int = 0,
        actual_unit_count: int | None = None,
        actual_cost_usd: float | None = None,
        usage_known: bool,
        error_type: str | None = None,
        cache_hit: bool = False,
    ) -> bool:
        """Idempotently replace one Pending row with its terminal accounting.

        When usage is unknown (including cancellation or a lost daemon thread),
        the UPDATE intentionally retains the maximum units and cost written by
        the reservation. If the process disappears before this method runs, the
        Pending row itself remains the same conservative durable charge.
        """

        if outcome not in {
            ProviderOperationOutcome.SUCCEEDED,
            ProviderOperationOutcome.FAILED,
        }:
            raise ValueError("a provider reservation requires a terminal outcome")
        values: dict[str, object] = {
            "outcome": outcome.value,
            "finished_at": finished_at,
            "latency_ms": max(0, int(latency_ms)),
            "result_count": max(0, int(result_count)),
            "error_type": error_type,
            "cache_hit": cache_hit,
        }
        if usage_known:
            values["unit_count"] = max(0, int(actual_unit_count or 0))
            values["estimated_cost_usd"] = (
                max(0.0, float(actual_cost_usd)) if actual_cost_usd is not None else None
            )
        try:
            with self.database.session_factory.begin() as session:
                result = session.execute(
                    update(ProviderOperationRow)
                    .where(
                        ProviderOperationRow.id == str(reservation.id),
                        ProviderOperationRow.outcome == ProviderOperationOutcome.PENDING.value,
                    )
                    .values(**values)
                )
                return bool(result.rowcount)
        except Exception:
            # The already committed Pending row is safer than losing the
            # reservation or taking down a completed user workflow.
            return False

    def release_pending(self, reservation: ProviderOperationReservation) -> bool:
        """Release a call that cooperative cancellation stopped before outbound I/O."""

        try:
            with self.database.session_factory.begin() as session:
                result = session.execute(
                    delete(ProviderOperationRow).where(
                        ProviderOperationRow.id == str(reservation.id),
                        ProviderOperationRow.outcome == ProviderOperationOutcome.PENDING.value,
                    )
                )
                return bool(result.rowcount)
        except Exception:
            # Fail closed: the Pending maximum stays durable, and the control
            # exception still prevents the external request from starting.
            return False

    @staticmethod
    def _budget_usage_in_session(
        session,
        *,
        since: datetime | None = None,
        workflow_id: UUID | None = None,
    ) -> ProviderBudgetUsage:
        filters = []
        if since is not None:
            filters.append(ProviderOperationRow.started_at >= since)
        if workflow_id is not None:
            filters.append(ProviderOperationRow.workflow_id == str(workflow_id))
        request_units = case(
            (ProviderOperationRow.unit_count > 0, ProviderOperationRow.unit_count),
            else_=0,
        )
        row = session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.BLOCKED.value,
                                0,
                            ),
                            (
                                ProviderOperationRow.unit_name.in_(("external request", "request")),
                                request_units,
                            ),
                            else_=1,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.BLOCKED.value,
                                0.0,
                            ),
                            else_=func.coalesce(
                                ProviderOperationRow.estimated_cost_usd,
                                0.0,
                            ),
                        )
                    ),
                    0.0,
                ),
            ).where(*filters)
        ).one()
        return ProviderBudgetUsage(
            operation_count=int(row[0] or 0),
            estimated_cost_usd=float(row[1] or 0),
        )

    def summary_since(
        self,
        since: datetime | None = None,
        *,
        provider: str | None = None,
        workflow_id: UUID | None = None,
        account_id: UUID | None = None,
    ) -> ProviderOperationSummary:
        filters = []
        if since is not None:
            filters.append(ProviderOperationRow.started_at >= since)
        if provider is not None:
            filters.append(ProviderOperationRow.provider == provider)
        if workflow_id is not None:
            filters.append(ProviderOperationRow.workflow_id == str(workflow_id))
        if account_id is not None:
            filters.append(ProviderOperationRow.account_id == str(account_id))
        with self.database.session_factory() as session:
            row = session.execute(
                select(
                    func.count(ProviderOperationRow.id),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.FAILED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.BLOCKED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.PENDING.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.coalesce(func.sum(ProviderOperationRow.unit_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.result_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.estimated_cost_usd), 0.0),
                    func.sum(
                        case(
                            (ProviderOperationRow.estimated_cost_usd.is_not(None), 1),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (ProviderOperationRow.estimated_cost_usd.is_(None))
                                & (
                                    ProviderOperationRow.outcome
                                    != ProviderOperationOutcome.BLOCKED.value
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                ).where(*filters)
            ).one()
        return ProviderOperationSummary(
            total_operations=int(row[0] or 0),
            failed_operations=int(row[1] or 0),
            blocked_operations=int(row[2] or 0),
            pending_operations=int(row[3] or 0),
            unit_count=int(row[4] or 0),
            result_count=int(row[5] or 0),
            estimated_cost_usd=float(row[6] or 0),
            costed_operations=int(row[7] or 0),
            unpriced_operations=int(row[8] or 0),
        )

    def summary_between(
        self,
        period_start: datetime,
        period_end: datetime,
        *,
        provider: str | None = None,
        account_id: UUID | None = None,
    ) -> ProviderOperationSummary:
        """Summarize an invoice window using metadata-only operation rows."""

        filters = [
            ProviderOperationRow.started_at >= period_start,
            ProviderOperationRow.started_at < period_end,
        ]
        if provider is not None:
            filters.append(ProviderOperationRow.provider == provider)
        if account_id is not None:
            filters.append(ProviderOperationRow.account_id == str(account_id))
        with self.database.session_factory() as session:
            row = session.execute(
                select(
                    func.count(ProviderOperationRow.id),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.FAILED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.BLOCKED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.PENDING.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.coalesce(func.sum(ProviderOperationRow.unit_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.result_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.estimated_cost_usd), 0.0),
                    func.sum(
                        case(
                            (ProviderOperationRow.estimated_cost_usd.is_not(None), 1),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (ProviderOperationRow.estimated_cost_usd.is_(None))
                                & (
                                    ProviderOperationRow.outcome
                                    != ProviderOperationOutcome.BLOCKED.value
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                ).where(*filters)
            ).one()
        return ProviderOperationSummary(
            total_operations=int(row[0] or 0),
            failed_operations=int(row[1] or 0),
            blocked_operations=int(row[2] or 0),
            pending_operations=int(row[3] or 0),
            unit_count=int(row[4] or 0),
            result_count=int(row[5] or 0),
            estimated_cost_usd=float(row[6] or 0),
            costed_operations=int(row[7] or 0),
            unpriced_operations=int(row[8] or 0),
        )

    def provider_names(self) -> list[str]:
        """Return provider identifiers that already occur in the ledger."""

        with self.database.session_factory() as session:
            return list(
                session.scalars(
                    select(ProviderOperationRow.provider)
                    .distinct()
                    .order_by(ProviderOperationRow.provider)
                ).all()
            )

    def summary_today(self) -> ProviderOperationSummary:
        now = datetime.now(timezone.utc)
        return self.summary_since(datetime(now.year, now.month, now.day, tzinfo=timezone.utc))

    def budget_usage_since(
        self,
        since: datetime | None = None,
        *,
        workflow_id: UUID | None = None,
        account_id: UUID | None = None,
    ) -> ProviderBudgetUsage:
        """Aggregate only the units that consume an operation or cost budget.

        A discovery ledger row may represent several external HTTP requests,
        whereas an LLM row stores token units but is still one provider
        operation.  Blocked rows represent calls that never happened and must
        not consume either rail, including after a process restart.
        """

        filters = []
        if since is not None:
            filters.append(ProviderOperationRow.started_at >= since)
        if workflow_id is not None:
            filters.append(ProviderOperationRow.workflow_id == str(workflow_id))
        if account_id is not None:
            filters.append(ProviderOperationRow.account_id == str(account_id))
        request_units = case(
            (ProviderOperationRow.unit_count > 0, ProviderOperationRow.unit_count),
            else_=0,
        )
        with self.database.session_factory() as session:
            row = session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    ProviderOperationRow.outcome
                                    == ProviderOperationOutcome.BLOCKED.value,
                                    0,
                                ),
                                (
                                    ProviderOperationRow.unit_name.in_(
                                        ("external request", "request")
                                    ),
                                    request_units,
                                ),
                                else_=1,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    ProviderOperationRow.outcome
                                    == ProviderOperationOutcome.BLOCKED.value,
                                    0.0,
                                ),
                                else_=func.coalesce(
                                    ProviderOperationRow.estimated_cost_usd,
                                    0.0,
                                ),
                            )
                        ),
                        0.0,
                    ),
                ).where(*filters)
            ).one()
        return ProviderBudgetUsage(
            operation_count=int(row[0] or 0),
            estimated_cost_usd=float(row[1] or 0),
        )

    def budget_usage_today(self) -> ProviderBudgetUsage:
        now = datetime.now(timezone.utc)
        return self.budget_usage_since(datetime(now.year, now.month, now.day, tzinfo=timezone.utc))

    def breakdown_since(
        self,
        since: datetime | None = None,
        *,
        workflow_id: UUID | None = None,
        account_id: UUID | None = None,
    ) -> list[ProviderOperationBreakdown]:
        """Return privacy-safe grouped usage without request or response material."""

        filters = []
        if since is not None:
            filters.append(ProviderOperationRow.started_at >= since)
        if workflow_id is not None:
            filters.append(ProviderOperationRow.workflow_id == str(workflow_id))
        if account_id is not None:
            filters.append(ProviderOperationRow.account_id == str(account_id))
        with self.database.session_factory() as session:
            rows = session.execute(
                select(
                    ProviderOperationRow.provider,
                    ProviderOperationRow.purpose,
                    func.count(ProviderOperationRow.id),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.FAILED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.BLOCKED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                ProviderOperationRow.outcome
                                == ProviderOperationOutcome.PENDING.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.coalesce(func.sum(ProviderOperationRow.unit_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.result_count), 0),
                    func.coalesce(func.sum(ProviderOperationRow.estimated_cost_usd), 0.0),
                    func.sum(
                        case(
                            (ProviderOperationRow.estimated_cost_usd.is_not(None), 1),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (ProviderOperationRow.estimated_cost_usd.is_(None))
                                & (
                                    ProviderOperationRow.outcome
                                    != ProviderOperationOutcome.BLOCKED.value
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.coalesce(func.avg(ProviderOperationRow.latency_ms), 0),
                    func.sum(case((ProviderOperationRow.cache_hit.is_(True), 1), else_=0)),
                )
                .where(*filters)
                .group_by(ProviderOperationRow.provider, ProviderOperationRow.purpose)
                .order_by(
                    func.count(ProviderOperationRow.id).desc(),
                    ProviderOperationRow.provider,
                    ProviderOperationRow.purpose,
                )
            ).all()
            failure_rows = session.execute(
                select(
                    ProviderOperationRow.provider,
                    ProviderOperationRow.purpose,
                    ProviderOperationRow.error_type,
                )
                .where(
                    *filters,
                    ProviderOperationRow.error_type.is_not(None),
                )
                .distinct()
                .order_by(
                    ProviderOperationRow.provider,
                    ProviderOperationRow.purpose,
                    ProviderOperationRow.error_type,
                )
            ).all()
        failure_types: dict[tuple[str, str], list[str]] = {}
        for provider, purpose, error_type in failure_rows:
            if error_type is not None:
                failure_types.setdefault((str(provider), str(purpose)), []).append(str(error_type))
        return [
            ProviderOperationBreakdown(
                provider=str(row[0]),
                purpose=str(row[1]),
                total_operations=int(row[2] or 0),
                failed_operations=int(row[3] or 0),
                blocked_operations=int(row[4] or 0),
                pending_operations=int(row[5] or 0),
                unit_count=int(row[6] or 0),
                result_count=int(row[7] or 0),
                estimated_cost_usd=float(row[8] or 0),
                costed_operations=int(row[9] or 0),
                unpriced_operations=int(row[10] or 0),
                average_latency_ms=round(float(row[11] or 0)),
                cache_hits=int(row[12] or 0),
                failure_types=failure_types.get((str(row[0]), str(row[1])), []),
            )
            for row in rows
        ]


class ProviderBudgetPolicy:
    """Daily and per-workflow provider authorization guard.

    Production callers use ``reserve``: its database-serialized check and
    Pending INSERT are the cross-process source of truth. The older in-memory
    ``allows``/reconcile helpers remain only for compatibility with adapters
    outside the composition root and must not authorize real product calls.
    """

    def __init__(
        self,
        ledger: ProviderOperationLedger,
        *,
        daily_operation_limit: int = 0,
        daily_cost_limit_usd: float = 0,
        action_operation_limit: int = 0,
        action_cost_limit_usd: float = 0,
    ) -> None:
        self.ledger = ledger
        self.daily_operation_limit = daily_operation_limit
        self.daily_cost_limit_usd = daily_cost_limit_usd
        self.action_operation_limit = action_operation_limit
        self.action_cost_limit_usd = action_cost_limit_usd
        self._lock = Lock()
        self._day = None
        self._daily_baseline = ProviderBudgetUsage()
        self._daily_authorized_operations = 0
        self._daily_authorized_cost = 0.0
        self._workflow_baselines: dict[UUID, ProviderBudgetUsage] = {}
        self._workflow_authorized_operations: dict[UUID, int] = {}
        self._workflow_authorized_cost: dict[UUID, float] = {}

    def reserve(
        self,
        *,
        operation_id: UUID,
        provider: str,
        purpose: str,
        started_at: datetime,
        unit_count: int = 1,
        unit_name: str = "operation",
        estimated_cost_usd: float | None = None,
        proposed_operation_count: int = 1,
    ) -> ProviderOperationReservation | None:
        """Durably authorize one external call before it can begin.

        Unlike the legacy in-memory ``allows`` helper, this path is safe across
        the web and worker processes and survives an immediate daemon exit.
        Callers must finalize the returned handle after the provider returns.
        """

        workflow_id = current_provider_workflow_id()
        with self._lock:
            self._refresh_day_if_needed()
            reservation = self.ledger.reserve_pending(
                operation_id=operation_id,
                provider=provider,
                purpose=purpose,
                started_at=started_at,
                unit_count=unit_count,
                unit_name=unit_name,
                estimated_cost_usd=estimated_cost_usd,
                proposed_operation_count=proposed_operation_count,
                daily_operation_limit=self.daily_operation_limit,
                daily_cost_limit_usd=self.daily_cost_limit_usd,
                action_operation_limit=self.action_operation_limit,
                action_cost_limit_usd=self.action_cost_limit_usd,
                additional_daily_operations=self._daily_authorized_operations,
                additional_daily_cost_usd=self._daily_authorized_cost,
                additional_workflow_operations=(
                    self._workflow_authorized_operations.get(workflow_id, 0)
                    if workflow_id is not None
                    else 0
                ),
                additional_workflow_cost_usd=(
                    self._workflow_authorized_cost.get(workflow_id, 0.0)
                    if workflow_id is not None
                    else 0.0
                ),
            )
        if reservation is None:
            return None
        try:
            check_cooperative_control()
        except CooperativeControlFlow:
            self.ledger.release_pending(reservation)
            raise
        return reservation

    def allows(
        self,
        *,
        proposed_cost_usd: float | None = None,
        proposed_operation_count: int = 1,
    ) -> bool:
        proposed_cost = max(0.0, proposed_cost_usd or 0.0)
        try:
            proposed_operations = max(1, int(proposed_operation_count))
        except (TypeError, ValueError):
            proposed_operations = 1
        workflow_id = current_provider_workflow_id()
        with self._lock:
            self._refresh_day_if_needed()
            projected_daily_operations = (
                self._daily_baseline.operation_count
                + self._daily_authorized_operations
                + proposed_operations
            )
            projected_daily_cost = (
                self._daily_baseline.estimated_cost_usd
                + self._daily_authorized_cost
                + proposed_cost
            )
            if (
                self.daily_operation_limit
                and projected_daily_operations > self.daily_operation_limit
            ):
                return False
            if self.daily_cost_limit_usd and projected_daily_cost > self.daily_cost_limit_usd:
                return False

            if workflow_id is not None:
                baseline = self._workflow_baselines.get(workflow_id)
                if baseline is None:
                    baseline = self.ledger.budget_usage_since(workflow_id=workflow_id)
                    self._workflow_baselines[workflow_id] = baseline
                projected_action_operations = (
                    baseline.operation_count
                    + self._workflow_authorized_operations.get(workflow_id, 0)
                    + proposed_operations
                )
                projected_action_cost = (
                    baseline.estimated_cost_usd
                    + self._workflow_authorized_cost.get(workflow_id, 0.0)
                    + proposed_cost
                )
                if (
                    self.action_operation_limit
                    and projected_action_operations > self.action_operation_limit
                ):
                    return False
                if (
                    self.action_cost_limit_usd
                    and projected_action_cost > self.action_cost_limit_usd
                ):
                    return False

            self._daily_authorized_operations += proposed_operations
            self._daily_authorized_cost += proposed_cost
            if workflow_id is not None:
                self._workflow_authorized_operations[workflow_id] = (
                    self._workflow_authorized_operations.get(workflow_id, 0) + proposed_operations
                )
                self._workflow_authorized_cost[workflow_id] = (
                    self._workflow_authorized_cost.get(workflow_id, 0.0) + proposed_cost
                )
            return True

    def reconcile_authorized_usage(
        self,
        *,
        reserved_operation_count: int,
        actual_operation_count: int,
        reserved_cost_usd: float | None,
        actual_cost_usd: float | None,
    ) -> None:
        """Replace a conservative provider reservation with observed usage."""

        try:
            reserved_operations = max(1, int(reserved_operation_count))
        except (TypeError, ValueError):
            reserved_operations = 1
        try:
            actual_operations = max(0, int(actual_operation_count))
        except (TypeError, ValueError):
            actual_operations = reserved_operations
        reserved_cost = max(0.0, reserved_cost_usd or 0.0)
        actual_cost = max(0.0, actual_cost_usd or 0.0)
        operation_adjustment = actual_operations - reserved_operations
        cost_adjustment = actual_cost - reserved_cost
        if operation_adjustment == 0 and cost_adjustment == 0:
            return
        workflow_id = current_provider_workflow_id()
        with self._lock:
            self._refresh_day_if_needed()
            self._daily_authorized_operations = max(
                0,
                self._daily_authorized_operations + operation_adjustment,
            )
            self._daily_authorized_cost = max(
                0.0,
                self._daily_authorized_cost + cost_adjustment,
            )
            if workflow_id is not None:
                self._workflow_authorized_operations[workflow_id] = max(
                    0,
                    self._workflow_authorized_operations.get(workflow_id, 0) + operation_adjustment,
                )
                self._workflow_authorized_cost[workflow_id] = max(
                    0.0,
                    self._workflow_authorized_cost.get(workflow_id, 0.0) + cost_adjustment,
                )

    def reconcile_authorized_cost(
        self,
        *,
        reserved_cost_usd: float | None,
        actual_cost_usd: float | None,
    ) -> None:
        """Replace a conservative pre-call reservation with the observed cost.

        Discovery providers can fan one logical search out into several HTTP
        requests.  They reserve their documented maximum before starting, then
        reconcile that reservation after the provider reports how many calls it
        actually attempted.  The in-process counters continue to cover the
        newly persisted ledger row without permanently charging the maximum.
        """

        self.reconcile_authorized_usage(
            reserved_operation_count=1,
            actual_operation_count=1,
            reserved_cost_usd=reserved_cost_usd,
            actual_cost_usd=actual_cost_usd,
        )

    def _refresh_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._day == today:
            return
        self._day = today
        self._daily_baseline = self.ledger.budget_usage_today()
        self._daily_authorized_operations = 0
        self._daily_authorized_cost = 0.0
        self._workflow_baselines.clear()
        self._workflow_authorized_operations.clear()
        self._workflow_authorized_cost.clear()


class RecordingDiscoveryProvider:
    """Account for a complete source-mesh search without retaining its query."""

    def __init__(
        self,
        provider: JobDiscoveryProvider,
        ledger: ProviderOperationLedger,
        budget: ProviderBudgetPolicy,
        *,
        estimated_cost_usd: float | None = None,
        cost_is_per_request: bool = False,
    ) -> None:
        self.provider = provider
        self.ledger = ledger
        self.budget = budget
        self.estimated_cost_usd = (
            estimated_cost_usd
            if estimated_cost_usd is not None and estimated_cost_usd > 0
            else None
        )
        self.cost_is_per_request = cost_is_per_request
        self.name = provider.name
        self.attribution = provider.attribution
        self.attribution_url = provider.attribution_url
        self._call_lock = Lock()

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        while not self._call_lock.acquire(timeout=0.1):
            check_cooperative_control()
        try:
            return self._search_serialized(query)
        finally:
            self._call_lock.release()

    def _search_serialized(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        check_cooperative_control()
        if not provider_permission_allowed(self.name):
            self._record(
                started_at,
                started,
                ProviderOperationOutcome.BLOCKED,
                BudgetDecision.BLOCKED,
                error_type="AccountProviderDisabled",
                cost_override=None,
                unit_count=0,
            )
            raise DiscoveryError(f"{self.name} is disabled under Account → provider choices.")
        maximum_request_count = self._maximum_request_count(query)
        reserved_cost = self._cost_for_request_count(maximum_request_count)
        reservation = self.budget.reserve(
            operation_id=uuid4(),
            provider=self.provider.name,
            purpose="job-discovery",
            started_at=started_at,
            unit_count=maximum_request_count,
            unit_name="external request",
            estimated_cost_usd=reserved_cost,
            proposed_operation_count=maximum_request_count,
        )
        if reservation is None:
            raise DiscoveryError(
                "The private-alpha provider budget has been reached. Try again tomorrow or ask the operator to review the configured limit."
            )
        try:
            setattr(self.provider, "last_request_count", 0)
        except Exception:
            pass
        try:
            results = self.provider.search(query)
        except CooperativeControlFlow:
            actual_request_count = self._actual_request_count()
            actual_cost = self._cost_for_request_count(actual_request_count)
            self._finalize(
                reservation,
                started,
                ProviderOperationOutcome.FAILED,
                error_type="TaskCancelledDuringProviderCall",
                actual_cost=actual_cost,
                actual_unit_count=actual_request_count,
                usage_known=False,
            )
            raise
        except Exception as exc:
            actual_request_count = self._actual_request_count()
            actual_cost = self._cost_for_request_count(actual_request_count)
            try:
                check_cooperative_control()
            except CooperativeControlFlow:
                self._finalize(
                    reservation,
                    started,
                    ProviderOperationOutcome.FAILED,
                    error_type="TaskCancelledAfterProviderFailure",
                    actual_cost=actual_cost,
                    actual_unit_count=actual_request_count,
                    usage_known=False,
                )
                raise
            self._finalize(
                reservation,
                started,
                ProviderOperationOutcome.FAILED,
                error_type=type(exc).__name__,
                actual_cost=actual_cost,
                actual_unit_count=actual_request_count,
                usage_known=actual_request_count > 0,
            )
            raise
        actual_request_count = self._actual_request_count()
        actual_cost = self._cost_for_request_count(actual_request_count)
        try:
            check_cooperative_control()
        except CooperativeControlFlow:
            # Cancellation fences product output, not real provider usage. A
            # paid call which returned after abort must still count against the
            # durable ledger and deployment budget.
            self._finalize(
                reservation,
                started,
                ProviderOperationOutcome.FAILED,
                error_type="TaskCancelledAfterProviderCall",
                actual_cost=actual_cost,
                actual_unit_count=actual_request_count,
                usage_known=False,
            )
            raise
        self._finalize(
            reservation,
            started,
            ProviderOperationOutcome.SUCCEEDED,
            result_count=len(results),
            actual_cost=actual_cost,
            actual_unit_count=actual_request_count,
            usage_known=True,
        )
        return results

    def _finalize(
        self,
        reservation: ProviderOperationReservation,
        started: float,
        outcome: ProviderOperationOutcome,
        *,
        result_count: int = 0,
        error_type: str | None = None,
        actual_cost: float | None,
        actual_unit_count: int,
        usage_known: bool,
    ) -> None:
        self.ledger.finalize_reservation(
            reservation,
            outcome=outcome,
            finished_at=datetime.now(timezone.utc),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            result_count=result_count,
            actual_unit_count=actual_unit_count,
            actual_cost_usd=actual_cost,
            usage_known=usage_known,
            error_type=error_type,
        )

    def _maximum_request_count(self, query: DiscoveryQuery) -> int:
        counter = getattr(self.provider, "maximum_request_count", None)
        if not callable(counter):
            return 1
        try:
            return max(1, int(counter(query)))
        except (TypeError, ValueError):
            return 1

    def _actual_request_count(self) -> int:
        count = getattr(self.provider, "last_request_count", None)
        if count is None:
            return 1
        try:
            return max(0, int(count))
        except (TypeError, ValueError):
            return 1

    def _cost_for_request_count(self, request_count: int) -> float | None:
        if self.estimated_cost_usd is None or request_count <= 0:
            return None
        if self.cost_is_per_request:
            return self.estimated_cost_usd * request_count
        return self.estimated_cost_usd

    def _record(
        self,
        started_at: datetime,
        started: float,
        outcome: ProviderOperationOutcome,
        budget_decision: BudgetDecision = BudgetDecision.ALLOWED,
        *,
        result_count: int = 0,
        error_type: str | None = None,
        cost_override: float | None | object = _USE_CONFIGURED_COST,
        unit_count: int = 1,
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        self.ledger.record(
            ProviderOperation(
                provider=self.provider.name,
                purpose="job-discovery",
                outcome=outcome,
                budget_decision=budget_decision,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                unit_count=unit_count,
                unit_name="external request",
                result_count=result_count,
                estimated_cost_usd=(
                    self.estimated_cost_usd
                    if cost_override is _USE_CONFIGURED_COST
                    else cost_override
                ),
                error_type=error_type,
            )
        )


class RecordingCompanyResearchProvider:
    """Account for employer research while treating a budget block as unavailable evidence."""

    def __init__(
        self,
        provider: CompanyResearchProvider,
        ledger: ProviderOperationLedger,
        budget: ProviderBudgetPolicy,
        *,
        estimated_cost_usd: float | None = None,
    ) -> None:
        self.provider = provider
        self.ledger = ledger
        self.budget = budget
        self.estimated_cost_usd = estimated_cost_usd
        self.name = getattr(provider, "name", provider.__class__.__name__.casefold())

    def research(self, company: str) -> list[CompanyResearchHit]:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        permission_allowed = provider_permission_allowed(self.name)
        if not permission_allowed:
            outcome = ProviderOperationOutcome.BLOCKED
            decision = BudgetDecision.BLOCKED
            results: list[CompanyResearchHit] = []
            error_type = "AccountProviderDisabled"
            estimated_cost_usd = None
            reservation = None
        else:
            reservation = self.budget.reserve(
                operation_id=uuid4(),
                provider=self.name,
                purpose="company-research",
                started_at=started_at,
                unit_count=1,
                unit_name="operation",
                estimated_cost_usd=self.estimated_cost_usd,
            )
        if permission_allowed and reservation is None:
            return []
        elif reservation is not None:
            decision = BudgetDecision.ALLOWED
            error_type = None
            estimated_cost_usd = self.estimated_cost_usd
            try:
                results = self.provider.research(company)
                outcome = ProviderOperationOutcome.SUCCEEDED
            except BaseException as exc:
                results = []
                outcome = ProviderOperationOutcome.FAILED
                error_type = type(exc).__name__
                self.ledger.finalize_reservation(
                    reservation,
                    outcome=outcome,
                    finished_at=datetime.now(timezone.utc),
                    latency_ms=max(0, round((perf_counter() - started) * 1000)),
                    result_count=0,
                    usage_known=False,
                    error_type=error_type,
                )
                if not isinstance(exc, Exception):
                    raise
                return results
            self.ledger.finalize_reservation(
                reservation,
                outcome=outcome,
                finished_at=datetime.now(timezone.utc),
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                result_count=len(results),
                actual_unit_count=1,
                actual_cost_usd=estimated_cost_usd,
                usage_known=True,
            )
            return results
        finished_at = datetime.now(timezone.utc)
        self.ledger.record(
            ProviderOperation(
                provider=self.name,
                purpose="company-research",
                outcome=outcome,
                budget_decision=decision,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                result_count=len(results),
                estimated_cost_usd=estimated_cost_usd,
                error_type=error_type,
            )
        )
        return results


class RecordingSalaryBenchmarkProvider:
    """Budget and account for one optional salary-research batch."""

    def __init__(
        self,
        provider: SalaryBenchmarkProvider,
        ledger: ProviderOperationLedger,
        budget: ProviderBudgetPolicy,
        *,
        estimated_cost_usd: float | None = None,
        tool_cost_per_call_usd: float | None = None,
    ) -> None:
        self.provider = provider
        self.ledger = ledger
        self.budget = budget
        self.estimated_cost_usd = estimated_cost_usd
        self.tool_cost_per_call_usd = tool_cost_per_call_usd
        self.name = provider.name
        self._call_lock = Lock()

    def research(self, jobs: list[JobPosting]) -> SalaryResearchResult:
        while not self._call_lock.acquire(timeout=0.1):
            check_cooperative_control()
        try:
            return self._research_serialized(jobs)
        finally:
            self._call_lock.release()

    def _research_serialized(self, jobs: list[JobPosting]) -> SalaryResearchResult:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        if not provider_permission_allowed(self.name):
            results = SalaryResearchResult()
            self._record_legacy(
                started_at,
                started,
                results,
                ProviderOperationOutcome.BLOCKED,
                budget_decision=BudgetDecision.BLOCKED,
                estimated_cost_usd=None,
                error_type="AccountProviderDisabled",
            )
            return results

        reserve = getattr(self.budget, "reserve", None)
        reservation = None
        maximum_cost = self._maximum_cost(jobs)
        if callable(reserve):
            reservation = reserve(
                operation_id=uuid4(),
                provider=self.name,
                purpose="salary-research",
                started_at=started_at,
                unit_count=1,
                unit_name="batch",
                estimated_cost_usd=maximum_cost,
            )
            if reservation is None:
                return SalaryResearchResult()
            assign_operation_id = getattr(self.provider, "assign_operation_id", None)
            if callable(assign_operation_id):
                assign_operation_id(reservation.id)
        else:
            legacy_allows = getattr(self.budget, "allows", None)
            legacy_allowed = bool(
                callable(legacy_allows) and legacy_allows(proposed_cost_usd=maximum_cost)
            )
        if not callable(reserve) and not legacy_allowed:
            results = SalaryResearchResult()
            self._record_legacy(
                started_at,
                started,
                results,
                ProviderOperationOutcome.BLOCKED,
                budget_decision=BudgetDecision.BLOCKED,
                estimated_cost_usd=None,
                error_type="ProviderBudgetExceeded",
            )
            return results

        try:
            raw_results = self.provider.research(jobs)
            results = (
                raw_results
                if isinstance(raw_results, SalaryResearchResult)
                else SalaryResearchResult(evidence=raw_results)
            )
        except BaseException as exc:
            results = SalaryResearchResult()
            if reservation is not None:
                actual_cost, usage_known = self._actual_cost()
                self.ledger.finalize_reservation(
                    reservation,
                    outcome=ProviderOperationOutcome.FAILED,
                    finished_at=datetime.now(timezone.utc),
                    latency_ms=max(0, round((perf_counter() - started) * 1_000)),
                    result_count=0,
                    actual_unit_count=1,
                    actual_cost_usd=actual_cost,
                    usage_known=usage_known,
                    error_type=type(exc).__name__,
                )
            else:
                self._record_legacy(
                    started_at,
                    started,
                    results,
                    ProviderOperationOutcome.FAILED,
                    estimated_cost_usd=self.estimated_cost_usd,
                    error_type=type(exc).__name__,
                )
            if not isinstance(exc, Exception):
                raise
            return results

        if reservation is not None:
            actual_cost, usage_known = self._actual_cost()
            self.ledger.finalize_reservation(
                reservation,
                outcome=ProviderOperationOutcome.SUCCEEDED,
                finished_at=datetime.now(timezone.utc),
                latency_ms=max(0, round((perf_counter() - started) * 1_000)),
                result_count=(
                    sum(len(items) for items in results.evidence.values()) + len(results.guesses)
                ),
                actual_unit_count=1,
                actual_cost_usd=actual_cost,
                usage_known=usage_known,
            )
            return results
        self._record_legacy(
            started_at,
            started,
            results,
            ProviderOperationOutcome.SUCCEEDED,
            estimated_cost_usd=self.estimated_cost_usd,
        )
        return results

    def _maximum_cost(self, jobs: list[JobPosting]) -> float | None:
        combined_cost = getattr(self.provider, "maximum_combined_cost_usd", None)
        if not callable(combined_cost):
            return self.estimated_cost_usd
        return combined_cost(
            jobs,
            tool_cost_per_call_usd=self.tool_cost_per_call_usd,
        )

    def _actual_cost(self) -> tuple[float | None, bool]:
        combined_cost = getattr(self.provider, "actual_combined_cost_usd", None)
        if not callable(combined_cost):
            return self.estimated_cost_usd, True
        return combined_cost(tool_cost_per_call_usd=self.tool_cost_per_call_usd)

    def _record_legacy(
        self,
        started_at: datetime,
        started: float,
        results: SalaryResearchResult,
        outcome: ProviderOperationOutcome,
        *,
        budget_decision: BudgetDecision = BudgetDecision.ALLOWED,
        estimated_cost_usd: float | None,
        error_type: str | None = None,
    ) -> None:
        self.ledger.record(
            ProviderOperation(
                provider=self.name,
                purpose="salary-research",
                outcome=outcome,
                budget_decision=budget_decision,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                latency_ms=max(0, round((perf_counter() - started) * 1_000)),
                unit_count=1,
                unit_name="batch",
                result_count=(
                    sum(len(items) for items in results.evidence.values()) + len(results.guesses)
                ),
                estimated_cost_usd=estimated_cost_usd,
                error_type=error_type,
            )
        )
