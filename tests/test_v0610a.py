from __future__ import annotations

from datetime import datetime, timezone

from betteroption.database import Database
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.matching import MatchDisposition, MatchOutcome, match_job
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperation,
    ProviderOperationLedger,
    ProviderOperationOutcome,
    RecordingDiscoveryProvider,
)
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.llm import LLMTask
from betteroption.settings import Settings


def _exclusion(value: str) -> ProfileFact:
    return ProfileFact(
        key="role.level",
        value=value,
        level=RequirementLevel.EXCLUSION,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.WORKING_MODEL, text=f"no {value}"),
        needs_confirmation=False,
    )


def _job(title: str, source_text: str) -> JobPosting:
    return JobPosting(
        title=title,
        company="Example Employer",
        location="Frankfurt am Main",
        summary=source_text,
        source_type=JobSourceType.SAMPLE,
        source_name="v0.6.10a regression",
        source_text=source_text,
    )


def test_internship_exclusion_does_not_block_an_ordinary_junior_role() -> None:
    result = match_job(
        CandidateProfile(facts=[_exclusion("internship")]),
        _job(
            "Junior Test Automation Engineer",
            "Junior individual-contributor role with no leadership responsibility.",
        ),
    )

    reason = result.reasons[0]
    assert reason.profile_value == "internship"
    assert reason.outcome == MatchOutcome.SATISFIED
    assert result.disposition != MatchDisposition.BLOCKED


def test_internship_exclusion_blocks_an_actual_internship() -> None:
    result = match_job(
        CandidateProfile(facts=[_exclusion("internship")]),
        _job(
            "Test Automation Intern",
            "A six-month internship in test automation.",
        ),
    )

    reason = result.reasons[0]
    assert reason.profile_value == "internship"
    assert reason.outcome == MatchOutcome.VIOLATED
    assert result.disposition == MatchDisposition.BLOCKED


def test_provider_operation_schema_cannot_hold_sensitive_payloads() -> None:
    fields = set(ProviderOperation.model_fields)

    assert not fields.intersection(
        {"query", "url", "prompt", "response", "job_text", "cv_text", "api_key"}
    )


def test_provider_operation_ledger_summarizes_usage_and_budget() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    now = datetime.now(timezone.utc)
    ledger.record(
        ProviderOperation(
            provider="example",
            purpose="job-discovery",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=now,
            finished_at=now,
            latency_ms=12,
            result_count=17,
            estimated_cost_usd=0.02,
        )
    )

    summary = ledger.summary_today()
    budget = ProviderBudgetPolicy(
        ledger,
        daily_operation_limit=1,
        daily_cost_limit_usd=0.03,
    )

    assert summary.total_operations == 1
    assert summary.result_count == 17
    assert summary.estimated_cost_usd == 0.02
    assert not budget.allows(proposed_cost_usd=0.001)


class _DiscoveryStub:
    name = "stub"
    attribution = "Stub feed"
    attribution_url = "https://example.com/feed"

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        del query
        return [
            DiscoveredJob(
                provider="stub",
                external_id="job-1",
                title="Test Engineer",
                company="Example",
                source_url="https://example.com/jobs/1",
            )
        ]


def test_recording_discovery_provider_counts_results_without_query_content() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    provider = RecordingDiscoveryProvider(
        _DiscoveryStub(),
        ledger,
        ProviderBudgetPolicy(ledger),
    )

    results = provider.search(DiscoveryQuery(text="private candidate phrase"))
    summary = ledger.summary_today()

    assert len(results) == 1
    assert summary.total_operations == 1
    assert summary.result_count == 1


def test_openai_pricing_configuration_reaches_each_model_route() -> None:
    policy = Settings(
        database_url="sqlite:///:memory:",
        openai_input_cost_per_million_usd=1.25,
        openai_output_cost_per_million_usd=5.0,
    ).model_policy()

    for task in (LLMTask.PROFILE_EXTRACTION, LLMTask.JOB_EXTRACTION):
        route = policy.route(task)
        assert route.input_cost_per_million_usd == 1.25
        assert route.output_cost_per_million_usd == 5.0
