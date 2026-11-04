from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

import betteroption.discovery as discovery_module
import betteroption.discovery_sources as discovery_sources_module
from betteroption.database import Database
from betteroption.discovery import (
    ArbeitnowDiscoveryProvider,
    BraveWebDiscoveryProvider,
    DiscoveryError,
    DiscoveryQuery,
)
from betteroption.discovery_sources import ExaFallbackDiscoveryProvider
from betteroption.mobility import MobilityService, TravelQuery
from betteroption.operations import (
    BudgetDecision,
    ProviderBudgetPolicy,
    ProviderOperation,
    ProviderOperationLedger,
    ProviderOperationOutcome,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
    provider_operation_scope,
)
from betteroption.profile import TravelMode


def _now() -> datetime:
    """Keep daily-budget assertions stable across UTC midnight."""

    return datetime.now(timezone.utc)


class _MultiRequestProvider:
    name = "exa-fallback"
    attribution = "Test provider"
    attribution_url = "https://example.com"

    def __init__(
        self,
        *,
        maximum_requests: int,
        actual_requests: int,
        fail: bool = False,
    ) -> None:
        self.maximum_requests = maximum_requests
        self.actual_requests = actual_requests
        self.fail = fail
        self.last_request_count = 0
        self.search_calls = 0

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        del query
        return self.maximum_requests

    def search(self, query: DiscoveryQuery) -> list:
        del query
        self.search_calls += 1
        self.last_request_count = self.actual_requests
        if self.fail:
            raise DiscoveryError("provider failed after requests")
        return []


def _recording_provider(
    raw: _MultiRequestProvider,
    ledger: ProviderOperationLedger,
    policy: ProviderBudgetPolicy,
) -> RecordingDiscoveryProvider:
    return RecordingDiscoveryProvider(raw, ledger, policy)


def test_daily_operation_budget_blocks_maximum_fanout_before_provider_call() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = _MultiRequestProvider(maximum_requests=5, actual_requests=3)
    provider = _recording_provider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger, daily_operation_limit=4),
    )

    with pytest.raises(DiscoveryError, match="provider budget"):
        provider.search(DiscoveryQuery(text="engineer"))

    assert raw.search_calls == 0
    assert ledger.budget_usage_today().operation_count == 0


def test_action_operation_budget_blocks_maximum_fanout_before_provider_call() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = _MultiRequestProvider(maximum_requests=5, actual_requests=3)
    provider = _recording_provider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger, action_operation_limit=4),
    )

    with provider_operation_scope(uuid4(), "explore"):
        with pytest.raises(DiscoveryError, match="provider budget"):
            provider.search(DiscoveryQuery(text="engineer"))

    assert raw.search_calls == 0


def test_discovery_releases_unused_operation_reservations() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    policy = ProviderBudgetPolicy(ledger, daily_operation_limit=6)
    first = _MultiRequestProvider(maximum_requests=5, actual_requests=3)
    second = _MultiRequestProvider(maximum_requests=3, actual_requests=2)
    blocked = _MultiRequestProvider(maximum_requests=2, actual_requests=1)

    assert _recording_provider(first, ledger, policy).search(DiscoveryQuery(text="one")) == []
    assert _recording_provider(second, ledger, policy).search(DiscoveryQuery(text="two")) == []
    with pytest.raises(DiscoveryError, match="provider budget"):
        _recording_provider(blocked, ledger, policy).search(DiscoveryQuery(text="three"))

    assert first.search_calls == 1
    assert second.search_calls == 1
    assert blocked.search_calls == 0
    assert ledger.budget_usage_today().operation_count == 5


def test_failed_discovery_reconciles_to_requests_actually_attempted() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    policy = ProviderBudgetPolicy(ledger, daily_operation_limit=6)
    failed = _MultiRequestProvider(maximum_requests=5, actual_requests=2, fail=True)
    follow_up = _MultiRequestProvider(maximum_requests=4, actual_requests=1)

    with pytest.raises(DiscoveryError, match="failed after requests"):
        _recording_provider(failed, ledger, policy).search(DiscoveryQuery(text="one"))
    assert _recording_provider(follow_up, ledger, policy).search(DiscoveryQuery(text="two")) == []

    assert ledger.budget_usage_today().operation_count == 3


def test_budget_aggregate_counts_requests_not_tokens_and_ignores_blocks() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    rows = (
        ProviderOperation(
            provider="one",
            purpose="search",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=_now(),
            finished_at=_now(),
            latency_ms=1,
            unit_count=2,
            unit_name="request",
            estimated_cost_usd=0.01,
        ),
        ProviderOperation(
            provider="two",
            purpose="search",
            outcome=ProviderOperationOutcome.FAILED,
            started_at=_now(),
            finished_at=_now(),
            latency_ms=1,
            unit_count=3,
            unit_name="external request",
            estimated_cost_usd=0.02,
        ),
        ProviderOperation(
            provider="openai",
            purpose="generation",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=_now(),
            finished_at=_now(),
            latency_ms=1,
            unit_count=999,
            unit_name="token",
            estimated_cost_usd=0.03,
        ),
        ProviderOperation(
            provider="blocked",
            purpose="search",
            outcome=ProviderOperationOutcome.BLOCKED,
            budget_decision=BudgetDecision.BLOCKED,
            started_at=_now(),
            finished_at=_now(),
            latency_ms=0,
            unit_count=42,
            unit_name="external request",
            estimated_cost_usd=0.99,
        ),
    )
    for operation in rows:
        ledger.record(operation)

    usage = ledger.budget_usage_since()
    summary = ledger.summary_since()

    assert usage.operation_count == 6
    assert usage.estimated_cost_usd == pytest.approx(0.06)
    assert summary.total_operations == 4
    assert summary.unit_count == 1_046
    assert summary.estimated_cost_usd == pytest.approx(1.05)
    # A fresh policy must use the durable budget aggregate rather than reset
    # blocked calls or interpret 999 tokens as 999 operations.
    assert not ProviderBudgetPolicy(ledger, daily_operation_limit=6).allows()


def test_arbeitnow_reports_page_requests_and_zero_for_a_cache_hit() -> None:
    requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requests.append(page)
        rows = (
            [
                {
                    "slug": "engineer",
                    "title": "Software Engineer",
                    "company_name": "Example",
                    "location": "Berlin",
                    "description": "Build software.",
                    "url": "https://example.com/jobs/engineer",
                }
            ]
            if page == 1
            else []
        )
        return httpx.Response(200, request=request, json={"data": rows})

    provider = ArbeitnowDiscoveryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_pages=5,
        cache_seconds=300,
    )
    query = DiscoveryQuery(text="software engineer")

    assert provider.maximum_request_count(query) == 5
    assert len(provider.search(query)) == 1
    assert provider.last_request_count == 2
    assert provider.maximum_request_count(query) == 1
    assert len(provider.search(query)) == 1
    assert provider.last_request_count == 0
    assert requests == [1, 2]


class _UncancellableFuture:
    def cancel(self) -> bool:
        return False


class _NonRunningExecutor:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def submit(self, function, *args, **kwargs):
        del function, args, kwargs
        return _UncancellableFuture()

    def shutdown(self, *args, **kwargs) -> None:
        del args, kwargs


def _all_pending(futures, timeout):
    del timeout
    return set(), set(futures)


def test_brave_timeout_counts_every_non_cancellable_request(monkeypatch) -> None:
    monkeypatch.setattr(discovery_module, "DaemonThreadPoolExecutor", _NonRunningExecutor)
    monkeypatch.setattr(discovery_module, "wait", _all_pending)
    provider = BraveWebDiscoveryProvider("key")
    query = DiscoveryQuery(text="software engineer", location="Berlin")

    with pytest.raises(Exception, match="search budget"):
        provider.search(query)

    # Page two is reserved for budget purposes but cannot start until a real
    # page-one response advertises more results.
    assert provider.last_request_count + 1 == provider.maximum_request_count(query)


def test_exa_timeout_counts_every_non_cancellable_request(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery_sources_module,
        "DaemonThreadPoolExecutor",
        _NonRunningExecutor,
    )
    monkeypatch.setattr(discovery_sources_module, "wait", _all_pending)
    provider = ExaFallbackDiscoveryProvider("key")
    query = DiscoveryQuery(text="software engineer", location="Berlin")

    with pytest.raises(DiscoveryError, match="unavailable"):
        provider.search(query)

    assert provider.last_request_count == provider.maximum_request_count(query)


class _PaidTravelProvider:
    name = "paid-route"

    def estimate(self, query: TravelQuery):  # pragma: no cover - budget must block first
        del query
        raise AssertionError("provider should not be called")


def test_mobility_budget_block_records_no_provider_cost() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    budget = ProviderBudgetPolicy(ledger, daily_operation_limit=1)
    assert budget.allows()
    service = MobilityService(
        None,  # type: ignore[arg-type]
        _PaidTravelProvider(),
        operation_ledger=ledger,
        operation_budget=budget,
        estimated_costs={"paid-route": 0.25},
        enforce_provider_permissions=False,
    )

    service._provider_estimate(  # noqa: SLF001 - focused accounting regression
        service.provider,
        TravelQuery(
            origin="Berlin",
            destination="Potsdam",
            mode=TravelMode.CAR,
        ),
    )

    with database.session_factory() as session:
        row = session.scalar(
            select(ProviderOperationRow).where(ProviderOperationRow.provider == "paid-route")
        )
    assert row is not None
    assert row.outcome == ProviderOperationOutcome.BLOCKED.value
    assert row.estimated_cost_usd is None
