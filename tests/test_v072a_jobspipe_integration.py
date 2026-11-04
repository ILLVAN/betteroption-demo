from __future__ import annotations

from pathlib import Path
from time import sleep

from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.provider_permissions import DEFAULT_PROVIDER_KEYS, permission_key_for_provider
from betteroption.settings import Settings


class _OrderedProvider:
    attribution = "Test"
    attribution_url = "https://example.com"

    def __init__(self, name: str, delay: float) -> None:
        self.name = name
        self.delay = delay

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        sleep(self.delay)
        return [
            DiscoveredJob(
                provider=self.name,
                external_id=self.name,
                title=query.text,
                company="Example",
                source_url=f"https://example.com/{self.name}",
            )
        ]


def test_jobspipe_has_independent_settings_permission_and_mesh_identity(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'jobspipe.db').as_posix()}",
        APIFY_API_TOKEN="shared-apify-secret",
        BETTEROPTION_APIFY_EURES_MAX_RESULTS=25,
        BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=120,
        BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD=0.0005,
        _env_file=None,
    )

    assert settings.apify_jobspipe_max_results == 120
    assert settings.apify_jobspipe_estimated_cost_per_run_usd == 0.0005
    assert permission_key_for_provider("apify-jobspipe") == "jobspipe"
    assert permission_key_for_provider("apify-eures") == "eures"
    assert "jobspipe" in DEFAULT_PROVIDER_KEYS

    container = ApplicationContainer(settings)
    names = [provider.name for provider in container.job_discovery_provider().primary_providers]

    assert "apify-eures" in names
    assert "apify-jobspipe" in names
    assert container.provider_availability()["eures"] == (True, "Configured")
    assert container.provider_availability()["jobspipe"] == (True, "Configured")


def test_hosted_jobspipe_remains_closed_until_processor_review(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'hosted-jobspipe.db').as_posix()}",
        app_environment="staging",
        APIFY_API_TOKEN="shared-apify-secret",
        processor_review_completed=False,
        _env_file=None,
    )
    container = ApplicationContainer(settings)

    assert container.provider_availability()["jobspipe"][0] is False
    assert "apify-jobspipe" not in [
        provider.name for provider in container.job_discovery_provider().primary_providers
    ]


def test_jobspipe_examples_keep_the_shared_secret_blank_and_limits_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (".env.example", "deploy/.env.staging.example"):
        example = (root / relative).read_text(encoding="utf-8")
        assert "APIFY_API_TOKEN=" in example
        assert "BETTEROPTION_APIFY_EURES_MAX_RESULTS=30" in example
        assert "BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS=300" in example
        assert "BETTEROPTION_APIFY_JOBSPIPE_POSTED_WITHIN_DAYS=60" in example
        assert "BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD=0" in example


def test_parallel_source_results_preserve_configured_provider_order() -> None:
    first = _OrderedProvider("first-source", 0.03)
    second = _OrderedProvider("second-source", 0)

    results, errors = DiscoverySourceMesh._search_providers(
        [first, second],
        DiscoveryQuery(text="Embedded Engineer"),
        timeout_seconds=1,
    )

    assert errors == []
    assert [[job.provider for job in group] for group in results] == [
        ["first-source"],
        ["second-source"],
    ]
