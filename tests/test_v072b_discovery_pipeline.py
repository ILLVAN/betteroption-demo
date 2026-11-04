from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Barrier, Event

import pytest
from pydantic import ValidationError

from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryQuery,
    _canonical_url,
    finalize_discovered_jobs,
)
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.explore_repository import ExploreSearchRepository


def _job(
    provider: str,
    external_id: str,
    url: str,
    *,
    title: str = "Embedded Engineer",
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        external_id=external_id,
        title=title,
        company="Example",
        summary="Embedded product development.",
        source_url=url,
    )


class _BarrierProvider:
    attribution = "Test source"
    attribution_url = "https://example.com/source"

    def __init__(self, name: str, barrier: Barrier) -> None:
        self.name = name
        self.barrier = barrier

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.barrier.wait(timeout=1)
        return [_job(self.name, self.name, f"https://example.com/jobs/{self.name}")]


class _PendingProvider:
    attribution = "Test source"
    attribution_url = "https://example.com/source"

    def __init__(self, name: str, release: Event) -> None:
        self.name = name
        self.release = release

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.release.wait(timeout=1)
        return []


class _EmptyProvider:
    name = "empty"
    attribution = "Test source"
    attribution_url = "https://example.com/source"

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        return []


def test_discovery_query_defaults_to_and_is_bounded_at_300() -> None:
    assert DiscoveryQuery(text="embedded").limit == 300
    assert DiscoveryQuery(text="embedded", limit=300).limit == 300
    with pytest.raises(ValidationError):
        DiscoveryQuery(text="embedded", limit=301)


def test_structured_sources_may_use_excluded_platforms_but_raw_web_sources_may_not() -> None:
    query = DiscoveryQuery(text="Embedded Engineer")
    structured = _job(
        "apify-all-jobs",
        "structured",
        "https://de.indeed.com/viewjob?jk=structured",
    )
    raw_web = _job(
        "exa-fallback",
        "raw-web",
        "https://de.indeed.com/viewjob?jk=raw-web",
    )

    results = finalize_discovered_jobs(query, [structured, raw_web])

    assert [job.external_id for job in results] == ["structured"]


def test_canonical_url_keeps_job_identity_and_removes_tracking() -> None:
    first = _canonical_url("https://DE.Indeed.com/viewjob/?utm_source=mail&jk=first&from=search")
    same_first = _canonical_url("https://de.indeed.com/viewjob?JK=first&utm_campaign=tracking")
    second = _canonical_url("https://de.indeed.com/viewjob?jk=second")

    assert first == "https://de.indeed.com/viewjob?jk=first"
    assert same_first == first
    assert second != first
    assert "utm_" not in first


def test_structured_platform_jobs_remain_distinct_and_tracking_variants_deduplicate() -> None:
    query = DiscoveryQuery(text="Embedded Engineer")
    first = _job(
        "apify-all-jobs",
        "first",
        "https://de.indeed.com/viewjob?jk=first&utm_source=one",
    )
    first_tracking_variant = _job(
        "apify-all-jobs",
        "first-copy",
        "https://de.indeed.com/viewjob?utm_source=two&jk=first",
    )
    second = _job(
        "apify-all-jobs",
        "second",
        "https://de.indeed.com/viewjob?jk=second",
    )

    results = finalize_discovered_jobs(query, [first, first_tracking_variant, second])

    assert {job.external_id for job in results} == {"first", "second"}


def test_vacancy_query_identity_keeps_old_and_new_rows_with_their_own_dates() -> None:
    query = DiscoveryQuery(text="Embedded Engineer")
    old_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
    new_date = datetime(2026, 8, 1, tzinfo=timezone.utc)
    old = _job(
        "apify-all-jobs",
        "old",
        "https://careers.example.com/jobs/opening?VacancyId=old&locale=nl-NL",
    ).model_copy(update={"published_at": old_date})
    new = _job(
        "apify-all-jobs",
        "new",
        "https://careers.example.com/jobs/opening?vacancyid=new&Locale=nl-NL",
    ).model_copy(update={"published_at": new_date})

    results = finalize_discovered_jobs(query, [old, new])

    assert {job.external_id: job.published_at for job in results} == {
        "old": old_date,
        "new": new_date,
    }
    assert "locale=nl-NL" in _canonical_url(str(old.source_url))
    assert "vacancyid=old" in _canonical_url(str(old.source_url))


def test_tracking_duplicate_borrows_date_only_for_the_same_normalized_subject() -> None:
    query = DiscoveryQuery(text="Embedded Engineer")
    published_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    richer = _job(
        "brave-web",
        "richer",
        "https://careers.example.com/jobs/embedded?utm_source=brave",
    )
    sparse_same = _job(
        "you-web",
        "dated-copy",
        "https://careers.example.com/jobs/embedded?UTM_SOURCE=you",
        title="  EMBEDDED   engineer ",
    ).model_copy(update={"summary": "", "company": " example ", "published_at": published_at})

    result = finalize_discovered_jobs(query, [richer, sparse_same])

    assert len(result) == 1
    assert result[0].external_id == "richer"
    assert result[0].published_at == published_at


def test_sparse_dated_conflicting_title_does_not_displace_or_contaminate_richer_row() -> None:
    query = DiscoveryQuery(text="Embedded Engineer")
    richer = _job(
        "brave-web",
        "richer",
        "https://careers.example.com/jobs/embedded?ref=search",
    )
    conflicting = _job(
        "you-web",
        "conflicting",
        "https://careers.example.com/jobs/embedded?utm_campaign=mail",
        title="Product Marketing Manager",
    ).model_copy(
        update={
            "summary": "",
            "published_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
        }
    )

    result = finalize_discovered_jobs(query, [richer, conflicting])

    assert len(result) == 1
    assert result[0].external_id == "richer"
    assert result[0].published_at is None


def test_snapshot_restore_scopes_excluded_domains_to_raw_web_sources() -> None:
    structured = _job(
        "apify-all-jobs",
        "structured",
        "https://www.linkedin.com/jobs/view/123",
    )
    raw_web = _job(
        "brave-web",
        "raw-web",
        "https://www.linkedin.com/jobs/view/456",
    )
    payload = json.dumps(
        [
            structured.model_dump(mode="json"),
            raw_web.model_dump(mode="json"),
        ]
    )

    restored = ExploreSearchRepository._results(payload)

    assert [job.external_id for job in restored] == ["structured"]


def test_snapshot_json_roundtrip_keeps_the_complete_300_result_pool() -> None:
    jobs = [
        _job(
            "apify-all-jobs",
            f"job-{index}",
            f"https://careers.example.com/jobs/{index}",
        )
        for index in range(300)
    ]
    payload = json.dumps([job.model_dump(mode="json") for job in jobs])

    restored = ExploreSearchRepository._results(payload)

    assert len(restored) == 300
    assert restored[0].external_id == "job-0"
    assert restored[-1].external_id == "job-299"


def test_mesh_allows_a_420_second_budget_and_a_300_second_primary_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_timeouts: list[float] = []

    def fake_search_providers(
        providers,
        query: DiscoveryQuery,
        *,
        timeout_seconds: float,
        check_control=None,
    ) -> tuple[list[list[DiscoveredJob]], list[str]]:
        del providers, query, check_control
        captured_timeouts.append(timeout_seconds)
        return [[]], []

    monkeypatch.setattr(
        DiscoverySourceMesh,
        "_search_providers",
        staticmethod(fake_search_providers),
    )
    mesh = DiscoverySourceMesh([_EmptyProvider()], search_budget_seconds=999)

    assert mesh.search(DiscoveryQuery(text="embedded")) == []
    assert mesh.search_budget_seconds == 420.0
    assert captured_timeouts == [300.0]


def test_mesh_starts_ten_configured_sources_without_queueing() -> None:
    barrier = Barrier(10)
    providers = [_BarrierProvider(f"source-{index}", barrier) for index in range(10)]

    results, errors = DiscoverySourceMesh._search_providers(
        providers,
        DiscoveryQuery(text="Embedded Engineer"),
        timeout_seconds=2,
    )

    assert errors == []
    assert len(results) == 10
    assert [group[0].provider for group in results] == [f"source-{index}" for index in range(10)]


def test_pending_provider_gets_a_fixed_secret_safe_deadline_row() -> None:
    release = Event()
    provider = _PendingProvider("provider token=never-echo-this", release)
    try:
        results, errors = DiscoverySourceMesh._search_providers(
            [provider],
            DiscoveryQuery(text="Embedded Engineer"),
            timeout_seconds=0.01,
        )
    finally:
        release.set()

    assert results == []
    assert errors == [
        "discovery-provider: shared Explore deadline reached before the provider returned."
    ]
    assert "never-echo-this" not in " ".join(errors)
