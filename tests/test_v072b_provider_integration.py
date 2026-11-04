from __future__ import annotations

from pathlib import Path

import httpx
from sqlalchemy import select

from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveryQuery
from betteroption.operations import ProviderOperationRow
from betteroption.provider_permissions import (
    DEFAULT_PROVIDER_KEYS,
    permission_key_for_provider,
)
from betteroption.settings import Settings


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
        APIFY_API_TOKEN="shared-apify-token",
        _env_file=None,
        **overrides,
    )


def test_all_jobs_has_independent_settings_permission_and_local_mesh_identity(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=40,
        BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=250,
        BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=1.5,
        BETTEROPTION_APIFY_ALL_JOBS_PLATFORMS="LinkedIn, Indeed, Glassdoor",
        BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD=0.002,
    )
    container = ApplicationContainer(settings)
    mesh = container.job_discovery_provider()
    names = [provider.name for provider in mesh.primary_providers]

    assert settings.apify_all_jobs_max_results_per_platform == 40
    assert settings.apify_all_jobs_max_items == 250
    assert settings.apify_all_jobs_max_total_charge_usd == 1.5
    assert permission_key_for_provider("apify-all-jobs") == "all-jobs"
    assert permission_key_for_provider("apify-jobspipe") == "jobspipe"
    assert {"all-jobs", "jobspipe", "eures"} <= DEFAULT_PROVIDER_KEYS
    assert {"apify-eures", "apify-jobspipe", "apify-all-jobs"} <= set(names)
    assert container.provider_availability()["all-jobs"] == (True, "Configured")


def test_all_jobs_cost_safe_defaults_are_isolated_from_eures_and_jobspipe(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    providers = {
        provider.name: provider
        for provider in ApplicationContainer(settings).job_discovery_provider().primary_providers
    }

    assert settings.apify_all_jobs_max_results_per_platform == 20
    assert settings.apify_all_jobs_max_items == 120
    assert settings.apify_all_jobs_max_total_charge_usd == 0.40
    assert settings.apify_all_jobs_estimated_cost_per_run_usd == 0.40
    assert providers["apify-all-jobs"].provider.max_results_per_platform == 20
    assert providers["apify-all-jobs"].provider.max_items == 120
    assert providers["apify-all-jobs"].provider.max_total_charge_usd == 0.40
    assert providers["apify-all-jobs"].estimated_cost_usd == 0.40

    assert settings.apify_eures_max_results == 30
    assert settings.apify_eures_estimated_cost_per_run_usd == 0
    assert providers["apify-eures"].provider.max_results == 30
    assert providers["apify-eures"].estimated_cost_usd is None
    assert settings.apify_jobspipe_max_results == 300
    assert settings.apify_jobspipe_estimated_cost_per_run_usd == 0
    assert providers["apify-jobspipe"].provider.max_results == 300
    assert providers["apify-jobspipe"].estimated_cost_usd is None


def test_every_configured_search_provider_is_primary_by_default(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        OPENWEBNINJA_JSEARCH_API_KEY="jsearch-key",
        EXA_API_KEY="exa-key",
        BRAVE_SEARCH_API_KEY="brave-key",
        YDC_API_KEY="you-key",
    )
    mesh = ApplicationContainer(settings).job_discovery_provider()
    names = {provider.name for provider in mesh.primary_providers}

    assert {
        "openwebninja-jsearch",
        "apify-eures",
        "apify-jobspipe",
        "apify-all-jobs",
        "arbeitnow",
        "exa-fallback",
        "brave-web",
        "you-web",
    } <= names
    assert mesh.fallback_providers == []


def test_call_all_switch_retains_the_legacy_brave_and_you_fallback(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        BRAVE_SEARCH_API_KEY="brave-key",
        YDC_API_KEY="you-key",
        BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=False,
    )
    mesh = ApplicationContainer(settings).job_discovery_provider()

    assert {provider.name for provider in mesh.fallback_providers} == {
        "brave-web",
        "you-web",
    }


def test_all_jobs_has_an_actor_specific_hosted_gate(tmp_path: Path) -> None:
    closed = _settings(
        tmp_path,
        app_environment="staging",
        processor_review_completed=True,
        BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=False,
    )
    closed_container = ApplicationContainer(closed)
    closed_names = {
        provider.name for provider in closed_container.job_discovery_provider().primary_providers
    }
    assert "apify-eures" in closed_names
    assert "apify-jobspipe" in closed_names
    assert "apify-all-jobs" not in closed_names
    assert closed_container.provider_availability()["all-jobs"][0] is False

    open_settings = closed.model_copy(
        update={"apify_all_jobs_hosted_enabled": True},
    )
    open_container = ApplicationContainer(open_settings)
    assert "apify-all-jobs" in {
        provider.name for provider in open_container.job_discovery_provider().primary_providers
    }


def test_all_jobs_actor_run_has_its_own_operation_and_cost_row(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    container = ApplicationContainer(settings)
    mesh = container.job_discovery_provider()
    recorded = next(
        provider for provider in mesh.primary_providers if provider.name == "apify-all-jobs"
    )
    raw = recorded.provider

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "safeRun123",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "safeDataset123",
                    }
                },
            )
        return httpx.Response(200, json=[])

    raw.client = httpx.Client(transport=httpx.MockTransport(handler))

    assert (
        recorded.search(DiscoveryQuery(text="Embedded Engineer", location="Frankfurt am Main"))
        == []
    )

    with container.database.session_factory() as session:
        row = session.scalar(
            select(ProviderOperationRow).where(ProviderOperationRow.provider == "apify-all-jobs")
        )
    assert row is not None
    assert row.unit_count == 2
    assert row.result_count == 0
    assert row.estimated_cost_usd == 0.40


def test_current_examples_expose_all_provider_caps_without_secrets() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (".env.example", "deploy/.env.staging.example"):
        example = (root / relative).read_text(encoding="utf-8")
        assert "APIFY_API_TOKEN=" in example
        assert "BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS=390" in example
        assert "BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true" in example
        assert "BETTEROPTION_APIFY_EURES_MAX_RESULTS=30" in example
        assert "BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=300" in example
        assert "BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD=0" in example
        assert "BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD=0" in example
        assert "BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM=20" in example
        assert "BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS=120" in example
        assert "BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD=0.40" in example
        assert "BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD=0.40" in example


def test_current_readme_and_privacy_copy_distinguish_readback_from_charge_caps() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    privacy = (root / "src/betteroption/web/templates/legal_privacy.html").read_text(
        encoding="utf-8"
    )

    assert "120-item readback/presentation guard" in readme
    assert "USD 0.40 pay-per-event charge ceiling" in readme
    assert "a separate readback/presentation limit" in privacy
    assert "a pay-per-event charge ceiling" in privacy
    assert "per-platform/total caps" not in privacy
