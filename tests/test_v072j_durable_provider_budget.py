from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from betteroption.company_intelligence import CompanyResearchHit
from betteroption.concurrency import CooperativeControlFlow, cooperative_control
from betteroption.database import Database
from betteroption.discovery import DiscoveryError, DiscoveryQuery
from betteroption.extraction import SectionExtraction
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.llm import LLMTask, ModelRoute
from betteroption.mobility import CommuteStatus, MobilityService, TravelEstimate, TravelQuery
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationOutcome,
    ProviderOperationRow,
    RecordingCompanyResearchProvider,
    RecordingDiscoveryProvider,
    RecordingSalaryBenchmarkProvider,
    provider_operation_scope,
)
from betteroption.profile import ProfileSection, TravelMode
from betteroption.providers.openai import OpenAIProfileExtractor, ProfileExtractionError
from betteroption.providers.openai_job import JobExtractionError, OpenAIJobExtractor
from betteroption.salary import SalaryResearchResult
from betteroption.telemetry import ModelInvocationRow, SqlAlchemyInvocationRecorder


NOW = datetime.now(timezone.utc).replace(microsecond=0)


class _OneRequestProvider:
    name = "durable-test-provider"
    attribution = "Test"
    attribution_url = "https://example.com/provider"

    def __init__(self) -> None:
        self.calls = 0
        self.last_request_count = 0
        self._lock = Lock()

    @staticmethod
    def maximum_request_count(_query: DiscoveryQuery) -> int:
        return 1

    def search(self, _query: DiscoveryQuery) -> list:
        with self._lock:
            self.calls += 1
        self.last_request_count = 1
        return []


class _CancelledProvider(_OneRequestProvider):
    @staticmethod
    def maximum_request_count(_query: DiscoveryQuery) -> int:
        return 3

    def search(self, _query: DiscoveryQuery) -> list:
        self.calls += 1
        raise CooperativeControlFlow


def test_cancelled_unknown_discovery_usage_keeps_reserved_maximum(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'cancelled-max.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    raw = _CancelledProvider()
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0.10,
        cost_is_per_request=True,
    )

    with pytest.raises(CooperativeControlFlow):
        provider.search(DiscoveryQuery(text="embedded engineer"))

    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.outcome == ProviderOperationOutcome.FAILED.value
    assert row.unit_count == 3
    assert row.estimated_cost_usd == pytest.approx(0.30)


def test_cancel_after_pending_commit_releases_reservation_before_outbound(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'post-reserve-cancel.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    raw = _OneRequestProvider()
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger, daily_operation_limit=1),
    )
    checkpoints = 0

    def cancel_after_reserve() -> None:
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 2:
            raise CooperativeControlFlow

    with cooperative_control(cancel_after_reserve), pytest.raises(CooperativeControlFlow):
        provider.search(DiscoveryQuery(text="embedded engineer"))

    assert raw.calls == 0
    assert ledger.budget_usage_today().operation_count == 0
    with database.session_factory() as session:
        assert session.scalar(select(ProviderOperationRow)) is None


class _CompanyProvider:
    name = "paid-company"

    def __init__(self) -> None:
        self.calls = 0

    def research(self, _company: str) -> list[CompanyResearchHit]:
        self.calls += 1
        return [CompanyResearchHit(title="Acme", url="https://example.com/acme")]


class _SalaryProvider:
    name = "paid-salary"

    def __init__(self) -> None:
        self.calls = 0

    def research(self, _jobs) -> SalaryResearchResult:
        self.calls += 1
        return SalaryResearchResult()


class _RouteProvider:
    name = "paid-route"

    def __init__(self) -> None:
        self.calls = 0

    def estimate(self, _query: TravelQuery) -> TravelEstimate:
        self.calls += 1
        return TravelEstimate(
            status=CommuteStatus.AVAILABLE,
            provider=self.name,
            duration_minutes=30,
        )


@pytest.mark.parametrize("kind", ["company", "salary"])
def test_research_wrappers_share_durable_budget_across_policy_instances(
    tmp_path: Path,
    kind: str,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / f'{kind}.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    raw = _CompanyProvider() if kind == "company" else _SalaryProvider()

    def wrapper(policy: ProviderBudgetPolicy):
        if kind == "company":
            return RecordingCompanyResearchProvider(
                raw,  # type: ignore[arg-type]
                ledger,
                policy,
                estimated_cost_usd=0.25,
            )
        return RecordingSalaryBenchmarkProvider(
            raw,  # type: ignore[arg-type]
            ledger,
            policy,
            estimated_cost_usd=0.25,
        )

    first = wrapper(ProviderBudgetPolicy(ledger, daily_operation_limit=1))
    second = wrapper(
        ProviderBudgetPolicy(ProviderOperationLedger(database), daily_operation_limit=1)
    )
    if kind == "company":
        assert first.research("Acme")
        assert second.research("Acme") == []
    else:
        assert first.research([]) == SalaryResearchResult()
        assert second.research([]) == SalaryResearchResult()

    assert raw.calls == 1
    with database.session_factory() as session:
        outcomes = sorted(session.scalars(select(ProviderOperationRow.outcome)).all())
    assert outcomes == ["blocked", "succeeded"]


def test_mobility_reserves_durably_before_route_provider_call(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'mobility.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    raw = _RouteProvider()
    query = TravelQuery(
        origin="Berlin",
        destination="Potsdam",
        mode=TravelMode.CAR,
    )

    first = MobilityService(
        None,  # type: ignore[arg-type]
        raw,
        operation_ledger=ledger,
        operation_budget=ProviderBudgetPolicy(ledger, daily_operation_limit=1),
        estimated_costs={raw.name: 0.20},
        enforce_provider_permissions=False,
    )
    restarted = MobilityService(
        None,  # type: ignore[arg-type]
        raw,
        operation_ledger=ledger,
        operation_budget=ProviderBudgetPolicy(
            ProviderOperationLedger(database),
            daily_operation_limit=1,
        ),
        estimated_costs={raw.name: 0.20},
        enforce_provider_permissions=False,
    )

    assert first._provider_estimate(raw, query).status == CommuteStatus.AVAILABLE  # noqa: SLF001
    assert (  # noqa: SLF001
        restarted._provider_estimate(raw, query).status == CommuteStatus.PROVIDER_UNAVAILABLE
    )
    assert raw.calls == 1
    with database.session_factory() as session:
        outcomes = sorted(session.scalars(select(ProviderOperationRow.outcome)).all())
    assert outcomes == ["blocked", "succeeded"]


def test_two_policy_instances_cannot_both_spend_the_same_sqlite_budget(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'multi-policy.db').as_posix()}")
    ledger_one = ProviderOperationLedger(database)
    ledger_two = ProviderOperationLedger(database)
    raw_one = _OneRequestProvider()
    raw_two = _OneRequestProvider()
    provider_one = RecordingDiscoveryProvider(
        raw_one,
        ledger_one,
        ProviderBudgetPolicy(ledger_one, daily_operation_limit=1),
    )
    provider_two = RecordingDiscoveryProvider(
        raw_two,
        ledger_two,
        ProviderBudgetPolicy(ledger_two, daily_operation_limit=1),
    )
    start = Barrier(2)

    def run(provider: RecordingDiscoveryProvider) -> str:
        start.wait(timeout=2)
        try:
            provider.search(DiscoveryQuery(text="embedded engineer"))
        except DiscoveryError:
            return "blocked"
        return "called"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(run, (provider_one, provider_two)))

    assert sorted(outcomes) == ["blocked", "called"]
    assert raw_one.calls + raw_two.calls == 1
    assert ledger_one.budget_usage_today().operation_count == 1
    with database.session_factory() as session:
        rows = list(session.scalars(select(ProviderOperationRow)).all())
    assert sorted(row.outcome for row in rows) == ["blocked", "succeeded"]


def test_pending_reservation_survives_policy_restart_and_keeps_maximum(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'pending-restart.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    first = ProviderBudgetPolicy(
        ledger,
        daily_operation_limit=1,
        daily_cost_limit_usd=0.40,
    )
    operation_id = uuid4()

    reservation = first.reserve(
        operation_id=operation_id,
        provider="paid-provider",
        purpose="job-discovery",
        started_at=NOW,
        unit_count=1,
        unit_name="external request",
        estimated_cost_usd=0.40,
    )

    assert reservation is not None
    restarted = ProviderBudgetPolicy(
        ProviderOperationLedger(database),
        daily_operation_limit=1,
        daily_cost_limit_usd=0.40,
    )
    assert (
        restarted.reserve(
            operation_id=uuid4(),
            provider="paid-provider",
            purpose="job-discovery",
            started_at=NOW,
            unit_count=1,
            unit_name="external request",
            estimated_cost_usd=0.40,
        )
        is None
    )
    with database.session_factory() as session:
        pending = session.get(ProviderOperationRow, str(operation_id))
    assert pending is not None
    assert pending.outcome == ProviderOperationOutcome.PENDING.value
    assert pending.estimated_cost_usd == pytest.approx(0.40)


def test_reservation_finalization_is_same_uuid_and_idempotent(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'finalize.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    reservation = ProviderBudgetPolicy(ledger).reserve(
        operation_id=uuid4(),
        provider="paid-provider",
        purpose="job-discovery",
        started_at=NOW,
        unit_count=5,
        unit_name="external request",
        estimated_cost_usd=0.50,
        proposed_operation_count=5,
    )
    assert reservation is not None

    assert ledger.finalize_reservation(
        reservation,
        outcome=ProviderOperationOutcome.SUCCEEDED,
        finished_at=NOW,
        latency_ms=4,
        result_count=2,
        actual_unit_count=2,
        actual_cost_usd=0.20,
        usage_known=True,
    )
    assert not ledger.finalize_reservation(
        reservation,
        outcome=ProviderOperationOutcome.FAILED,
        finished_at=NOW,
        latency_ms=9,
        usage_known=False,
        error_type="LateFailure",
    )
    with database.session_factory() as session:
        rows = list(session.scalars(select(ProviderOperationRow)).all())
    assert len(rows) == 1
    assert rows[0].id == str(reservation.id)
    assert rows[0].outcome == ProviderOperationOutcome.SUCCEEDED.value
    assert rows[0].unit_count == 2
    assert rows[0].estimated_cost_usd == pytest.approx(0.20)


class _ProfileResponses:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            output_parsed=SectionExtraction(
                summary="Embedded systems preference.",
                facts=[],
                follow_up_question=None,
            ),
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def test_profile_llm_attempt_reserves_before_parse_and_finalizes_same_uuid(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'profile-llm.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    policy = ProviderBudgetPolicy(ledger, daily_operation_limit=1)
    recorder = SqlAlchemyInvocationRecorder(
        database,
        operation_ledger=ledger,
        operation_budget=policy,
    )
    responses = _ProfileResponses()
    extractor = OpenAIProfileExtractor(
        route=ModelRoute(
            task=LLMTask.PROFILE_EXTRACTION,
            provider="openai",
            model="test-model",
            prompt_version="test",
            input_cost_per_million_usd=1,
            output_cost_per_million_usd=2,
        ),
        client=SimpleNamespace(responses=responses),
        recorder=recorder,
    )

    with provider_operation_scope(uuid4(), "profile-extraction"):
        extractor.extract(ProfileSection.DIRECTION, "I prefer embedded systems work.")
    with pytest.raises(ProfileExtractionError, match="limit was reached"):
        with provider_operation_scope(uuid4(), "profile-extraction"):
            extractor.extract(ProfileSection.DIRECTION, "I also like firmware.")

    assert responses.calls == 1
    with database.session_factory() as session:
        invocation = session.scalar(select(ModelInvocationRow))
        rows = list(
            session.scalars(
                select(ProviderOperationRow).order_by(ProviderOperationRow.started_at)
            ).all()
        )
    assert invocation is not None
    assert len(rows) == 2
    succeeded = next(row for row in rows if row.outcome == "succeeded")
    assert succeeded.id == invocation.id
    assert succeeded.unit_count == 15
    assert sum(row.outcome == "blocked" for row in rows) == 1


class _JobResponses:
    def __init__(self, extraction: JobExtraction) -> None:
        self.extraction = extraction
        self.calls = 0

    def parse(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(output_parsed=self.extraction)


def test_job_evidence_retry_requires_a_second_durable_authorization(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'job-retry.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    recorder = SqlAlchemyInvocationRecorder(
        database,
        operation_ledger=ledger,
        operation_budget=ProviderBudgetPolicy(ledger, action_operation_limit=1),
    )
    responses = _JobResponses(
        JobExtraction(
            title="Embedded Engineer",
            company="Acme",
            location="Berlin",
            summary="Embedded role.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="Python",
                    kind="requirement",
                    evidence_quote="advanced Python expertise",
                )
            ],
        )
    )
    extractor = OpenAIJobExtractor(
        client=SimpleNamespace(responses=responses),
        recorder=recorder,
    )

    with provider_operation_scope(uuid4(), "job-import"):
        with pytest.raises(JobExtractionError, match="limit was reached"):
            extractor.extract(
                "Acme requires Python for an embedded role in Berlin.",
                source_name="manual",
                source_url="https://example.com/jobs/1",
                requested_url="https://example.com/jobs/1",
                url_http_status=200,
                url_checked_at=NOW,
            )

    assert responses.calls == 1
    with database.session_factory() as session:
        rows = list(session.scalars(select(ProviderOperationRow)).all())
    assert sorted(row.outcome for row in rows) == ["blocked", "succeeded"]


def test_all_direct_openai_and_import_entrypoints_declare_durable_scopes() -> None:
    app_source = Path("src/betteroption/web/app.py").read_text(encoding="utf-8")

    assert app_source.count('provider_operation_scope(uuid4(), "profile-extraction")') >= 4
    assert app_source.count('provider_operation_scope(uuid4(), "job-import")') >= 5
    assert 'provider_operation_scope(task.id, "job-import")' in app_source
    assert "cooperative_control(checkpoint if callable(checkpoint) else None)" in app_source
