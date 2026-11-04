from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from betteroption.container import ApplicationContainer
from betteroption.database import Database
from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryError,
    DiscoveryQuery,
    _web_search_texts,
    web_discovery_document_is_error_landing,
    web_discovery_document_is_individual_job,
    web_discovery_result_is_plausible_job,
)
from betteroption.discovery_sources import DiscoverySourceMesh, YouWebDiscoveryProvider
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
)
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument


def _document(requested_url: str, *, final_url: str | None = None, text: str) -> FetchedDocument:
    return FetchedDocument(
        requested_url=requested_url,
        final_url=final_url or requested_url,
        status_code=200,
        content_type="text/html",
        text=text,
        fetched_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    (
        (
            "https://jobs.siemens.com/en_US/externaljobs/JobDetail/Automation-Engineer/1234",
            "Automation Engineer",
            True,
        ),
        ("https://careers.example.com/jobs/embedded-engineer-4711", "Embedded Engineer", True),
        ("https://careers.example.com/jobs", "Search jobs", False),
        ("https://example.com/blog/best-job-boards", "10 Best Job Boards in 2026", False),
        ("https://example.com/resources/software-careers", "Software career guide", False),
    ),
)
def test_web_result_gate_requires_an_individual_vacancy_shape(
    url: str,
    title: str,
    expected: bool,
) -> None:
    assert web_discovery_result_is_plausible_job(url, title) is expected


@pytest.mark.parametrize(
    ("url", "title"),
    (
        (
            "https://example.successfactors.eu/career?career_job_req_id=12345",
            "Senior Engineer",
        ),
        (
            "https://careers.example.icims.com/jobs/12345/senior-engineer/job",
            "Senior Engineer",
        ),
        (
            "https://careers.example.icims.com/jobs/12345/job",
            "Senior Engineer",
        ),
        ("https://jobs.example.com/careers?jobId=12345", "Senior Engineer"),
    ),
)
def test_web_result_gate_accepts_explicit_ats_job_identifiers(url: str, title: str) -> None:
    assert web_discovery_result_is_plausible_job(url, title)


@pytest.mark.parametrize(
    ("url", "title"),
    (
        ("https://example.successfactors.eu/career", "Senior Engineer"),
        ("https://careers.example.icims.com/jobs/job", "Senior Engineer"),
        ("https://careers.example.icims.com/jobs/search/job", "Senior Engineer"),
        (
            "https://example.successfactors.eu/blog?career_job_req_id=12345",
            "Senior Engineer",
        ),
        (
            "https://example.successfactors.eu/career?career_job_req_id=12345",
            "Search jobs",
        ),
    ),
)
def test_web_result_gate_keeps_generic_or_editorial_ats_pages_closed(
    url: str,
    title: str,
) -> None:
    assert not web_discovery_result_is_plausible_job(url, title)


def test_identifier_bearing_ats_url_still_requires_individual_job_body() -> None:
    url = "https://example.successfactors.eu/career?career_job_req_id=12345"
    generic_body = "Search all open positions and browse our career opportunities."
    vacancy_body = "Senior Engineer. Responsibilities and qualifications. Apply now."

    assert not web_discovery_document_is_error_landing(url, generic_body)
    assert not web_discovery_document_is_individual_job(generic_body)
    assert web_discovery_document_is_individual_job(vacancy_body)


@pytest.mark.parametrize(
    ("final_url", "text"),
    (
        (
            "https://suspended-domain.net/index.php?host=careerium.unaux.com",
            "This domain has been suspended",
        ),
        ("https://employer.example/jobs", "Search all open positions"),
        ("https://employer.example/blog/roles", "Engineering careers"),
        ("https://employer.example/jobs/123", "404 page not found"),
        ("https://employer.example/jobs/123", "The 10 best job boards in Europe"),
    ),
)
def test_reachability_gate_rejects_error_category_and_editorial_landings(
    final_url: str,
    text: str,
) -> None:
    assert web_discovery_document_is_error_landing(final_url, text)


class _RedirectingFetcher:
    def fetch(self, url: str) -> FetchedDocument:
        if "parked" in url:
            return _document(
                url,
                final_url="https://suspended-domain.net/index.php?host=careerium.unaux.com",
                text="This domain has been suspended",
            )
        if "category" in url:
            return _document(
                url,
                final_url="https://employer.example/jobs",
                text="Search all jobs",
            )
        return _document(
            url,
            text="Embedded Engineer. Responsibilities and qualifications. Apply now.",
        )


def test_web_hits_fail_closed_after_redirect_and_body_checks() -> None:
    filter_ = DiscoveryAvailabilityFilter(
        fetcher=_RedirectingFetcher(),  # type: ignore[arg-type]
        maximum_checks=10,
        total_timeout_seconds=2,
    )
    jobs = [
        DiscoveredJob(
            provider="exa-fallback",
            external_id=identity,
            title="Embedded Engineer",
            company="Example",
            location="Leipzig",
            source_url=f"https://careers.example.com/jobs/{identity}",
        )
        for identity in ("open", "parked", "category")
    ]
    direct = jobs[0].model_copy(
        update={
            "provider": "arbeitnow",
            "external_id": "feed",
            "source_url": "https://feed.example/jobs/feed",
        }
    )

    kept = filter_.keep_open_or_unknown([*jobs, direct])

    assert {(job.provider, job.external_id) for job in kept} == {
        ("exa-fallback", "open"),
        ("arbeitnow", "feed"),
    }


def test_cross_provider_duplicate_does_not_consume_same_host_check_slot() -> None:
    class RecordingFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch(self, url: str) -> FetchedDocument:
            self.calls.append(url)
            return _document(
                url,
                text="Embedded Engineer. Responsibilities and qualifications. Apply now.",
            )

    fetcher = RecordingFetcher()
    filter_ = DiscoveryAvailabilityFilter(
        fetcher=fetcher,  # type: ignore[arg-type]
        maximum_checks=10,
        maximum_checks_per_host=2,
        total_timeout_seconds=2,
    )
    shared_url = "https://careers.example.com/jobs/shared"
    jobs = [
        DiscoveredJob(
            provider="exa-fallback",
            external_id="exa-shared",
            title="Embedded Engineer",
            company="Example",
            location="Leipzig",
            source_url=shared_url,
        ),
        DiscoveredJob(
            provider="brave-web",
            external_id="brave-shared",
            title="Embedded Engineer",
            company="Example",
            location="Leipzig",
            source_url=shared_url,
        ),
        DiscoveredJob(
            provider="exa-fallback",
            external_id="second",
            title="Firmware Engineer",
            company="Example",
            location="Leipzig",
            source_url="https://careers.example.com/jobs/second",
        ),
    ]

    kept = filter_.keep_open_or_unknown(jobs)

    assert set(fetcher.calls) == {
        shared_url,
        "https://careers.example.com/jobs/second",
    }
    assert {job.external_id for job in kept} == {
        "exa-shared",
        "brave-shared",
        "second",
    }


def test_search_bundles_are_concise_independent_and_keep_safe_exclusions() -> None:
    query = DiscoveryQuery(
        text="embedded software · test automation · firmware",
        location="60486",
        desired_terms=["embedded software", "test automation", "firmware"],
        excluded_terms=["military", "defence industry"],
    )

    searches = _web_search_texts(query)

    assert 10 < len(searches) <= 16
    assert all(" OR " not in search for search in searches)
    assert all(search.count('"') <= 4 for search in searches)
    assert all("-military" in search for search in searches)
    assert all("defence industry" not in search for search in searches)
    assert any('"embedded software"' in search for search in searches)
    assert any('"test automation"' in search for search in searches)
    assert any('"firmware"' in search for search in searches)


def test_you_search_uses_current_endpoint_and_parses_only_job_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "results": {
                    "web": [
                        {
                            "url": "https://careers.example.com/jobs/embedded-engineer-123",
                            "title": "Embedded Software Engineer in Leipzig",
                            "description": "Build embedded products in Leipzig.",
                            "snippets": ["Join the Leipzig engineering team."],
                            "page_age": "2026-07-28T10:00:00Z",
                        },
                        {
                            "url": "https://example.com/blog/best-job-boards",
                            "title": "10 Best Job Boards in Europe",
                            "description": "A list of search sites.",
                        },
                    ]
                }
            },
        )

    provider = YouWebDiscoveryProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="embedded software",
            location="Leipzig",
            desired_terms=["embedded software"],
            limit=180,
        )
    )

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ydc-index.io/v1/search"
    assert request.headers["X-API-Key"] == "test-key"
    payload = json.loads(request.content)
    assert payload["count"] == 100
    assert payload["country"] == "DE"
    assert payload["safesearch"] == "strict"
    assert "linkedin.com" in payload["exclude_domains"]
    assert [job.title for job in jobs] == ["Embedded Software Engineer in Leipzig"]
    assert jobs[0].provider == "you-web"
    assert jobs[0].published_at is None
    assert provider.last_request_count == 1


class _MultiRequestProvider:
    name = "exa-fallback"
    attribution = "Test provider"
    attribution_url = "https://example.com"

    def __init__(self, *, actual_requests: int = 3, maximum_requests: int = 5) -> None:
        self.actual_requests = actual_requests
        self.maximum_requests = maximum_requests
        self.last_request_count = 0
        self.search_calls = 0

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        del query
        return self.maximum_requests

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        del query
        self.search_calls += 1
        self.last_request_count = self.actual_requests
        return []


def test_discovery_cost_reserves_maximum_but_records_actual_http_calls() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = _MultiRequestProvider(actual_requests=3, maximum_requests=5)
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=0.025),
        estimated_cost_usd=0.005,
        cost_is_per_request=True,
    )

    assert provider.search(DiscoveryQuery(text="embedded engineer")) == []

    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.unit_name == "external request"
    assert row.unit_count == 3
    assert row.estimated_cost_usd == pytest.approx(0.015)


def test_discovery_budget_blocks_before_calls_when_maximum_fanout_would_exceed_it() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = _MultiRequestProvider(actual_requests=3, maximum_requests=5)
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=0.024),
        estimated_cost_usd=0.005,
        cost_is_per_request=True,
    )

    with pytest.raises(DiscoveryError, match="provider budget"):
        provider.search(DiscoveryQuery(text="embedded engineer"))

    assert raw.search_calls == 0
    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.outcome == "blocked"
    assert row.unit_count == 0
    assert row.estimated_cost_usd is None


def test_zero_price_is_recorded_as_unpriced_not_free() -> None:
    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = _MultiRequestProvider(actual_requests=2, maximum_requests=2)
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0,
        cost_is_per_request=True,
    )

    provider.search(DiscoveryQuery(text="embedded engineer"))

    summary = ledger.summary_today()
    assert summary.unit_count == 2
    assert summary.costed_operations == 0
    assert summary.unpriced_operations == 1


def test_you_key_aliases_and_shared_explore_deadline_are_bounded() -> None:
    assert Settings(YDC_API_KEY="canonical", _env_file=None).you_search_api_key == "canonical"
    assert (
        Settings(BETTEROPTION_YOU_SEARCH_API_KEY="prefixed", _env_file=None).you_search_api_key
        == "prefixed"
    )
    primary = _MultiRequestProvider(actual_requests=1, maximum_requests=1)
    mesh = DiscoverySourceMesh(
        [primary],
        search_budget_seconds=230,
    )

    assert mesh.search_budget_seconds == 230
    assert mesh.availability_reserve_seconds == 40
    assert DiscoverySourceMesh([primary], search_budget_seconds=999).search_budget_seconds == 420


def test_discovery_fallback_floor_has_new_name_and_legacy_alias() -> None:
    assert (
        Settings(
            BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS=42,
            _env_file=None,
        ).discovery_fallback_min_results
        == 42
    )
    assert (
        Settings(
            BETTEROPTION_EXA_FALLBACK_MIN_RESULTS=37,
            _env_file=None,
        ).discovery_fallback_min_results
        == 37
    )


def test_container_runs_each_configured_web_provider_as_a_primary_source(tmp_path) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
            EXA_API_KEY="exa",
            BRAVE_SEARCH_API_KEY="brave",
            YDC_API_KEY="you",
            _env_file=None,
        )
    )

    mesh = container.job_discovery_provider()

    assert [provider.name for provider in mesh.primary_providers] == [
        "betteroption-posted",
        "arbeitnow",
        "exa-fallback",
        "brave-web",
        "you-web",
    ]
    assert mesh.fallback_providers == []
