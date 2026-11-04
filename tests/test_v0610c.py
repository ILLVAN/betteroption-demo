from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from betteroption.brave_search import BraveSearchPlanError
from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperation,
    ProviderOperationOutcome,
    RecordingDiscoveryProvider,
    provider_operation_scope,
)
from betteroption.settings import Settings
from betteroption.web import create_app


def _now() -> datetime:
    """Keep date-window assertions stable when a full test run crosses UTC midnight."""

    return datetime.now(timezone.utc)


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'v0610c.db').as_posix()}",
            auth_mode="local",
            brave_search_api_key="brave-secret-value",
            exa_search_api_key="exa-secret-value",
            brave_search_estimated_cost_per_call_usd=0.003,
            exa_search_estimated_cost_per_call_usd=0.007,
        )
    )


def test_provider_operations_are_correlated_without_retaining_payloads(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workflow_id = uuid4()
    with provider_operation_scope(workflow_id, "match-run"):
        container.operations.record(
            ProviderOperation(
                provider="brave-search",
                purpose="company-research",
                outcome=ProviderOperationOutcome.SUCCEEDED,
                started_at=_now(),
                finished_at=_now(),
                latency_ms=42,
                result_count=3,
                estimated_cost_usd=0.003,
            )
        )

    summary = container.operations.summary_since(workflow_id=workflow_id)
    breakdown = container.operations.breakdown_since(workflow_id=workflow_id)

    assert summary.total_operations == 1
    assert summary.result_count == 3
    assert summary.estimated_cost_usd == 0.003
    assert [(row.provider, row.purpose) for row in breakdown] == [
        ("brave-search", "company-research")
    ]


def test_pending_provider_operation_is_distinct_in_summaries_and_operations_page(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workflow_id = uuid4()
    started_at = _now()
    budget = ProviderBudgetPolicy(container.operations)
    with provider_operation_scope(workflow_id, "explore-search"):
        reservation = budget.reserve(
            operation_id=uuid4(),
            provider="pending-provider",
            purpose="job-discovery",
            started_at=started_at,
            unit_count=1,
            unit_name="request",
            estimated_cost_usd=0.02,
        )

    assert reservation is not None
    summary = container.operations.summary_since(workflow_id=workflow_id)
    period = container.operations.summary_between(
        started_at - timedelta(seconds=1),
        started_at + timedelta(seconds=1),
        provider="pending-provider",
    )
    (breakdown,) = container.operations.breakdown_since(workflow_id=workflow_id)

    for item in (summary, period, breakdown):
        assert item.total_operations == 1
        assert item.pending_operations == 1
        assert item.failed_operations == 0
        assert item.blocked_operations == 0

    page = TestClient(create_app(container, data_directory=tmp_path / "data")).get("/operations")
    soup = BeautifulSoup(page.text, "html.parser")
    provider_row = soup.find("th", string="pending-provider")

    assert page.status_code == 200
    assert "Operations · 1 pending" in page.text
    assert provider_row is not None
    table = provider_row.find_parent("table")
    assert table is not None
    assert [cell.get_text(" ", strip=True) for cell in table.select("thead th")] == [
        "Provider",
        "Purpose",
        "Calls",
        "Results",
        "Average",
        "Failures",
        "Blocked",
        "Pending",
        "Estimated",
    ]
    cells = provider_row.find_parent("tr").find_all(["th", "td"])
    assert cells[2].get_text(" ", strip=True) == "1"
    assert cells[5].get_text(" ", strip=True) == "0"
    assert cells[6].get_text(" ", strip=True) == "0"
    assert cells[7].get_text(" ", strip=True) == "1"


def test_operations_page_is_explicit_about_provider_configuration_and_hidden_secrets(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    page = TestClient(create_app(container, data_directory=tmp_path / "data")).get("/operations")

    assert page.status_code == 200
    assert "Provider visibility" in page.text
    assert "Brave Search" in page.text
    assert "Brave Answers" in page.text
    assert "Separate product; no application code path" in page.text
    assert "Not used" in page.text
    assert "Exa Search" in page.text
    assert "What each run consumed" in page.text
    assert "BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD" in page.text
    assert "BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD" in page.text
    assert "brave-secret-value" not in page.text
    assert "exa-secret-value" not in page.text


def test_brave_answers_key_is_never_used_as_explore_search_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_ANSWERS_API_KEY", "answers-only-secret")
    container = ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'answers-only.db').as_posix()}",
            employer_homepage_research=False,
        )
    )

    discovery = container.job_discovery_provider()

    assert container.settings.brave_search_api_key is None
    assert "brave-web" not in {
        provider.name for provider in [*discovery.primary_providers, *discovery.fallback_providers]
    }


def test_operations_exposes_only_a_sanitized_brave_failure_category(tmp_path: Path) -> None:
    container = _container(tmp_path)
    secret = "provider-response-secret"
    container.operations.record(
        ProviderOperation(
            provider="brave-web",
            purpose="job-discovery",
            outcome=ProviderOperationOutcome.FAILED,
            started_at=_now(),
            finished_at=_now(),
            latency_ms=20,
            error_type="BraveSearchPlanError",
        )
    )

    breakdown = container.operations.breakdown_since()
    page = TestClient(create_app(container, data_directory=tmp_path / "data")).get("/operations")

    brave = next(row for row in breakdown if row.provider == "brave-web")
    assert brave.failure_types == ["BraveSearchPlanError"]
    assert "Sanitized: BraveSearchPlanError" in page.text
    assert secret not in page.text


def test_explore_shows_brave_failure_even_when_the_mesh_returns_other_results(
    tmp_path: Path,
) -> None:
    class ArbeitnowStub:
        name = "arbeitnow"
        attribution = "Test feed"
        attribution_url = "https://example.com/feed"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            del query
            return [
                DiscoveredJob(
                    provider=self.name,
                    external_id="job-1",
                    title="Test Automation Engineer",
                    company="Example",
                    location="Frankfurt am Main",
                    source_url="https://careers.example.com/jobs/1",
                )
            ]

    class WrongPlanBraveStub:
        name = "brave-web"
        attribution = "Brave Search"
        attribution_url = "https://brave.com/search/api/"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            del query
            raise BraveSearchPlanError("safe plan failure")

    container = ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'explore-brave.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
            transitous_enabled=False,
            valhalla_enabled=False,
            osm_geocoder_enabled=False,
        )
    )
    budget = ProviderBudgetPolicy(container.operations)
    discovery = DiscoverySourceMesh(
        [
            RecordingDiscoveryProvider(ArbeitnowStub(), container.operations, budget),
            RecordingDiscoveryProvider(WrongPlanBraveStub(), container.operations, budget),
        ],
        search_budget_seconds=30,
    )
    page = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=discovery,
        )
    ).get("/explore", params={"q": "test automation", "location": "Frankfurt"})

    assert page.status_code == 200
    assert "Test Automation Engineer" in page.text
    assert "Arbeitnow · Reached" in page.text
    assert "Brave Search · Failed" in page.text
    assert "Search-product access denied (HTTP 402/403)" in page.text
    assert "safe plan failure" not in page.text


def test_explore_does_not_render_an_unfinished_provider_operation_as_reached(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'explore-pending.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
            transitous_enabled=False,
            valhalla_enabled=False,
            osm_geocoder_enabled=False,
        )
    )
    budget = ProviderBudgetPolicy(container.operations)

    class PendingDiscovery:
        name = "pending-provider"
        attribution = "Pending provider"
        attribution_url = "https://example.com/pending"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            del query
            reservation = budget.reserve(
                operation_id=uuid4(),
                provider=self.name,
                purpose="job-discovery",
                started_at=_now(),
                estimated_cost_usd=0.02,
            )
            assert reservation is not None
            return []

    page = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=PendingDiscovery(),
        )
    ).get("/explore", params={"q": "test automation", "location": "Frankfurt"})

    assert page.status_code == 200
    assert "Pending Provider · Pending" in page.text
    assert "Pending Provider · Reached" not in page.text
    assert "This provider has not reached a terminal result." in page.text


def test_explore_distinguishes_returned_brave_rows_from_final_cards(tmp_path: Path) -> None:
    container = ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'filtered-brave.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
            transitous_enabled=False,
            valhalla_enabled=False,
            osm_geocoder_enabled=False,
        )
    )

    class CentrallyFilteredDiscovery:
        name = "test-mesh"
        attribution = "Test discovery"
        attribution_url = "https://example.com/discovery"

        def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
            del query
            container.operations.record(
                ProviderOperation(
                    provider="brave-web",
                    purpose="job-discovery",
                    outcome=ProviderOperationOutcome.SUCCEEDED,
                    started_at=_now(),
                    finished_at=_now(),
                    latency_ms=12,
                    result_count=2,
                )
            )
            return [
                DiscoveredJob(
                    provider="arbeitnow",
                    external_id="survivor",
                    title="Test Automation Engineer",
                    company="Example",
                    location="Frankfurt am Main",
                    source_url="https://careers.example.com/jobs/survivor",
                )
            ]

    page = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=CentrallyFilteredDiscovery(),
        )
    ).get("/explore", params={"q": "test automation", "location": "Frankfurt"})

    assert page.status_code == 200
    assert "Brave Search · Reached" in page.text
    assert "Found 2 usable job(s); 0 contributed to these ranked results." in page.text


def test_overview_cards_use_a_compact_delete_and_state_footer() -> None:
    result_card = Path("src/betteroption/web/templates/result_card.html").read_text(
        encoding="utf-8"
    )
    archive_card = Path("src/betteroption/web/templates/opportunity_card.html").read_text(
        encoding="utf-8"
    )

    for template in (result_card, archive_card):
        assert 'class="card-actions-row"' in template
        assert "Delete job" in template
        assert "data-application-state" in template
        assert "Saved automatically" not in template
