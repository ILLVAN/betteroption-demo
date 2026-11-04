from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from betteroption.background import BackgroundTaskKind
from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryQuery,
    SourceReadiness,
    finalize_discovered_jobs,
)
from betteroption.explore_repository import ExploreSearchRepository
from betteroption.job_repository import normalize_job_url
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument, UrlFailureKind, UrlIngestionError


def _job(
    provider: str,
    identity: str,
    url: str,
    *,
    summary: str = "Embedded product development.",
    source_providers: list[str] | None = None,
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        source_providers=source_providers or [],
        external_id=identity,
        title="Embedded Software Engineer",
        company="Example Products",
        location="Berlin",
        summary=summary,
        source_url=url,
    )


def test_legacy_discovery_has_one_effective_provider_and_safe_readiness() -> None:
    legacy = _job(
        "apify-jobspipe",
        "legacy",
        "https://careers.example.com/jobs/legacy",
    ).model_dump(mode="json")
    legacy.pop("source_providers")
    legacy.pop("source_readiness")

    restored = DiscoveredJob.model_validate(legacy)

    assert restored.source_providers == []
    assert restored.effective_source_providers == ("apify-jobspipe",)
    assert restored.source_readiness == SourceReadiness.PROVIDER_LISTED


def test_deduplication_keeps_richer_primary_and_stable_provider_union() -> None:
    url = "https://careers.example.com/jobs/embedded-engineer"
    sparse = _job(
        "exa-fallback",
        "sparse",
        f"{url}?utm_source=exa",
        summary="",
    )
    richer = _job(
        "brave-web",
        "richer",
        f"{url}?utm_source=brave",
        summary="Develop embedded products, firmware, and automated tests.",
    )

    results = finalize_discovered_jobs(DiscoveryQuery(text="embedded software"), [sparse, richer])

    assert len(results) == 1
    assert results[0].provider == "brave-web"
    assert results[0].external_id == "richer"
    assert results[0].source_providers == ["exa-fallback", "brave-web"]
    assert results[0].effective_source_providers == ("exa-fallback", "brave-web")


def test_single_vacancy_shape_is_required_for_every_provider() -> None:
    query = DiscoveryQuery(text="embedded software")
    roots = [
        _job(provider, provider, "https://www.stellenonline.de")
        for provider in (
            "brave-web",
            "apify-jobspipe",
            "apify-all-jobs",
            "openwebninja-jsearch",
        )
    ]
    search_page = _job(
        "apify-jobspipe",
        "search-page",
        "https://www.stellenonline.de/jobs",
    )
    nested_search_page = _job(
        "apify-all-jobs",
        "nested-search-page",
        "https://www.stellenonline.de/search/embedded-software-engineer",
    )
    category_page = _job(
        "openwebninja-jsearch",
        "category-page",
        "https://www.stellenonline.de/category/engineering",
    )
    individual = _job(
        "apify-jobspipe",
        "individual",
        "https://www.stellenonline.de/jobs/embedded-software-engineer-4711",
    )
    ordinary_employer_slug = _job(
        "apify-all-jobs",
        "ordinary-employer-slug",
        "https://ordinary-company.example/open-position-software-engineer",
    )

    results = finalize_discovered_jobs(
        query,
        [
            *roots,
            search_page,
            nested_search_page,
            category_page,
            individual,
            ordinary_employer_slug,
        ],
    )

    assert {job.external_id for job in results} == {
        "individual",
        "ordinary-employer-slug",
    }


class _ReadinessFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchedDocument:
        self.calls.append(url)
        if "blocked" in url:
            raise UrlIngestionError(
                "robots.txt does not permit fetching this URL",
                kind=UrlFailureKind.BLOCKED,
            )
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            text="Embedded Engineer. Responsibilities and qualifications. Apply now.",
            fetched_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )


def test_preflight_fails_raw_web_closed_and_annotates_structured_sources() -> None:
    fetcher = _ReadinessFetcher()
    filter_ = DiscoveryAvailabilityFilter(
        fetcher=fetcher,  # type: ignore[arg-type]
        max_workers=1,
        maximum_checks=4,
        maximum_checks_per_host=5,
        total_timeout_seconds=2,
    )
    structured_open = _job(
        "apify-jobspipe",
        "structured-open",
        "https://structured-open.example/jobs/open",
    )
    structured_blocked = _job(
        "apify-all-jobs",
        "structured-blocked",
        "https://structured-blocked.example/jobs/blocked",
    )
    structured_unchecked = _job(
        "openwebninja-jsearch",
        "structured-unchecked",
        "https://structured-unchecked.example/jobs/unchecked",
    )
    raw_open = _job(
        "brave-web",
        "raw-open",
        "https://raw-open.example/jobs/open",
    )
    raw_blocked = _job(
        "exa-fallback",
        "raw-blocked",
        "https://raw-blocked.example/jobs/blocked",
    )

    kept = filter_.keep_open_or_unknown(
        [structured_open, structured_blocked, structured_unchecked, raw_open, raw_blocked]
    )
    by_id = {job.external_id: job for job in kept}

    assert set(by_id) == {
        "structured-open",
        "structured-blocked",
        "structured-unchecked",
        "raw-open",
    }
    assert by_id["raw-open"].source_readiness == SourceReadiness.READY
    assert by_id["structured-open"].source_readiness == SourceReadiness.READY
    assert by_id["structured-blocked"].source_readiness == SourceReadiness.MANUAL_REQUIRED
    assert by_id["structured-unchecked"].source_readiness == SourceReadiness.PROVIDER_LISTED
    assert len(fetcher.calls) == 4


def test_zero_preflight_budget_never_leaks_an_unverified_raw_web_hit() -> None:
    fetcher = _ReadinessFetcher()
    filter_ = DiscoveryAvailabilityFilter(
        fetcher=fetcher,  # type: ignore[arg-type]
        maximum_checks=10,
    )
    structured = _job(
        "apify-jobspipe",
        "structured",
        "https://structured.example/jobs/embedded",
    )
    raw = _job(
        "brave-web",
        "raw",
        "https://raw.example/jobs/embedded",
    )

    kept = filter_.keep_open_or_unknown([structured, raw], timeout_seconds=0)

    assert [job.external_id for job in kept] == ["structured"]
    assert kept[0].source_readiness == SourceReadiness.PROVIDER_LISTED
    assert fetcher.calls == []


def test_snapshot_restore_and_readiness_update_preserve_all_results(tmp_path: Path) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'explore-readiness.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    query = DiscoveryQuery(text="embedded software")
    first = _job(
        "apify-jobspipe",
        "first",
        "https://careers.example.com/jobs/first",
    )
    second = _job(
        "apify-all-jobs",
        "second",
        "https://careers.example.com/jobs/second",
    )
    container.explore_searches.create(
        task_id=task.id,
        workspace_id=workspace.id,
        query=query,
        query_text=query.text,
        location="",
        compass_used=False,
        hide_remote_only=False,
    )
    container.explore_searches.complete(
        task.id,
        results=[first, second],
        regional_result_count=0,
    )

    updated = container.explore_searches.update_result_readiness(
        task.id,
        {normalize_job_url(str(first.source_url))},
    )
    restored = container.explore_searches.get(task.id)

    assert updated == 1
    assert restored is not None
    assert [job.external_id for job in restored.results] == ["first", "second"]
    assert restored.results[0].source_readiness == SourceReadiness.MANUAL_REQUIRED
    assert restored.results[1].source_readiness == SourceReadiness.PROVIDER_LISTED


def test_old_snapshot_restores_provenance_and_drops_structured_root_page() -> None:
    individual = _job(
        "apify-jobspipe",
        "individual",
        "https://careers.example.com/jobs/individual",
    ).model_dump(mode="json")
    individual.pop("source_providers")
    individual.pop("source_readiness")
    root = _job(
        "apify-all-jobs",
        "root",
        "https://www.stellenonline.de",
    ).model_dump(mode="json")
    root.pop("source_providers")
    root.pop("source_readiness")

    restored = ExploreSearchRepository._results(json.dumps([individual, root]))

    assert [job.external_id for job in restored] == ["individual"]
    assert restored[0].effective_source_providers == ("apify-jobspipe",)
    assert restored[0].source_readiness == SourceReadiness.PROVIDER_LISTED
