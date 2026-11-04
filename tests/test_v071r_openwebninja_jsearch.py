from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import sleep

import httpx
import pytest
from sqlalchemy import select

from betteroption.container import ApplicationContainer
from betteroption.database import Database
from betteroption.discovery import DiscoveryQuery
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
)
from betteroption.provider_permissions import permission_key_for_provider
from betteroption.providers.openwebninja_jsearch import (
    JSearchAuthenticationError,
    JSearchPlanError,
    JSearchProviderUnavailableError,
    JSearchRateLimitError,
    JSearchReadTimeoutError,
    JSearchRequestError,
    JSearchResponseError,
    OpenWebNinjaJSearchProvider,
)
from betteroption.settings import Settings


def _jsearch_row() -> dict[str, object]:
    return {
        "job_id": "de-midwife-123",
        "job_title": "Midwife / Hebamme (m/w/d)",
        "employer_name": "München Klinik",
        "job_publisher": "LinkedIn",
        "job_employment_types": ["FULLTIME"],
        "job_apply_link": "https://aggregator.example/jobs/123",
        "apply_options": [
            {
                "publisher": "München Klinik",
                "apply_link": "https://jobs.muenchen-klinik.example/midwife-123",
                "is_direct": True,
            }
        ],
        "job_description": "<p>Support families during childbirth.</p>",
        "job_is_remote": False,
        "job_location": "München, Bayern, Germany",
        "job_posted_at_datetime_utc": "2026-08-02T08:30:00Z",
    }


def test_jsearch_uses_focused_queries_and_parses_structured_job_evidence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "request_id": "safe-opaque-id",
                "data": {"jobs": [_jsearch_row()], "cursor": "next-page"},
            },
        )

    provider = OpenWebNinjaJSearchProvider(
        "private-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=2,
    )
    query = DiscoveryQuery(
        text="midwife · midwifery · supporting childbirth",
        desired_terms=["midwife", "midwifery", "supporting childbirth"],
        location="München",
    )

    jobs = provider.search(query)

    assert len(requests) == 2
    assert provider.last_request_count == 2
    assert {request.url.params["query"] for request in requests} == {
        "midwife jobs in München",
        "midwifery jobs in München",
    }
    assert all(request.url.params["country"] == "de" for request in requests)
    assert all(request.url.params["language"] == "de" for request in requests)
    assert all("num_pages" not in request.url.params for request in requests)
    assert all("fields" not in request.url.params for request in requests)
    assert all(request.headers["X-API-Key"] == "private-key" for request in requests)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.provider == "openwebninja-jsearch"
    assert job.title == "Midwife / Hebamme (m/w/d)"
    assert job.company == "München Klinik"
    assert str(job.source_url) == "https://jobs.muenchen-klinik.example/midwife-123"
    assert job.location == "München, Bayern, Germany"
    assert job.summary == "Support families during childbirth."
    assert job.published_at == datetime(2026, 8, 2, 8, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "data": [_jsearch_row()]},
        {"status": 200, "jobs": [_jsearch_row()]},
    ],
)
def test_jsearch_accepts_bounded_compatible_success_envelopes(
    payload: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=payload)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    jobs = provider.search(DiscoveryQuery(text="midwife"))

    assert [job.external_id for job in jobs] == ["de-midwife-123"]


def test_jsearch_current_success_envelope_allows_an_empty_jobs_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"status": "OK", "data": {"jobs": [], "cursor": None}},
        )

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    assert provider.search(DiscoveryQuery(text="midwife")) == []


def test_jsearch_requests_remote_results_explicitly() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [_jsearch_row()]})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    provider.search(DiscoveryQuery(text="midwife", remote_only=True))

    assert requests[0].url.params["work_from_home"] == "true"


@pytest.mark.parametrize("location", ["Germany", "Deutschland", "60311"])
def test_jsearch_normalizes_country_names_and_bare_german_postcodes(location: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
        max_transient_retries=0,
    )
    provider.search(DiscoveryQuery(text="embedded engineer", location=location))

    assert requests[0].url.params["country"] == "de"
    assert requests[0].url.params["language"] == "de"


@pytest.mark.parametrize(
    "location",
    ["Frankfurt am Main, Germany", "Frankfurt am Main, DE"],
)
def test_jsearch_resolves_country_from_compound_compass_location(location: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
        max_transient_retries=0,
    )
    provider.search(DiscoveryQuery(text="embedded software", location=location))

    assert requests[0].url.params["query"] == f"embedded software engineer jobs in {location}"
    assert requests[0].url.params["country"] == "de"
    assert requests[0].url.params["language"] == "de"


def test_jsearch_turns_compass_role_families_into_title_like_queries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        max_transient_retries=0,
    )
    provider.search(
        DiscoveryQuery(
            text="embedded software · test automation · FPGA development",
            desired_terms=["embedded software", "test automation", "FPGA development"],
            location="Frankfurt am Main",
        )
    )

    assert [request.url.params["query"] for request in requests] == [
        "embedded software engineer jobs in Frankfurt am Main",
        "test automation engineer jobs in Frankfurt am Main",
        "FPGA engineer jobs in Frankfurt am Main",
    ]


def test_jsearch_basic_plan_focused_requests_are_serialized() -> None:
    concurrency_lock = Lock()
    active_requests = 0
    maximum_concurrency = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, maximum_concurrency
        del request
        with concurrency_lock:
            active_requests += 1
            maximum_concurrency = max(maximum_concurrency, active_requests)
        sleep(0.02)
        with concurrency_lock:
            active_requests -= 1
        return httpx.Response(200, json={"data": [_jsearch_row()]})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
    )

    provider.search(
        DiscoveryQuery(
            text="midwife · midwifery · hebamme",
            desired_terms=["midwife", "midwifery", "hebamme"],
            location="München",
        )
    )

    assert provider.last_request_count == 3
    assert maximum_concurrency == 1


def test_jsearch_read_timeout_is_not_retried_or_repeated_for_role_variants() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("private response timing", request=request)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        max_transient_retries=2,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(JSearchReadTimeoutError):
        provider.search(
            DiscoveryQuery(
                text="midwife · midwifery · hebamme",
                location="München",
            )
        )

    assert len(requests) == 1
    assert provider.last_request_count == 1


def test_jsearch_request_rejection_stops_variant_fanout() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(400, text="private provider rejection detail")

    provider = OpenWebNinjaJSearchProvider(
        "private-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=6,
    )

    with pytest.raises(JSearchRequestError) as caught:
        provider.search(DiscoveryQuery(text="python · developer · backend · django"))

    assert len(requests) == 1
    assert provider.last_request_count == 1
    assert "private provider" not in str(caught.value)


def test_jsearch_keeps_prior_results_when_a_later_variant_is_rejected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"data": [_jsearch_row()]})
        return httpx.Response(422, text="private provider rejection detail")

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=4,
    )

    jobs = provider.search(DiscoveryQuery(text="midwife · hebamme · midwifery"))

    assert [job.external_id for job in jobs] == ["de-midwife-123"]
    assert len(requests) == 2
    assert provider.last_request_count == 2


def test_jsearch_keeps_prior_variant_results_when_a_later_read_times_out() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"data": [_jsearch_row()]})
        raise httpx.ReadTimeout("private response timing", request=request)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        max_transient_retries=2,
        sleeper=lambda _seconds: None,
    )

    jobs = provider.search(
        DiscoveryQuery(
            text="midwife · midwifery · hebamme",
            location="München",
        )
    )

    assert [job.external_id for job in jobs] == ["de-midwife-123"]
    assert len(requests) == 2
    assert provider.last_request_count == 2


def test_jsearch_whole_provider_deadline_stops_later_variants() -> None:
    requests: list[httpx.Request] = []
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        now[0] = 121.0
        return httpx.Response(200, json={"data": [_jsearch_row()]})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        search_budget_seconds=120.0,
        clock=lambda: now[0],
    )

    jobs = provider.search(
        DiscoveryQuery(
            text="midwife · midwifery · hebamme",
            location="München",
        )
    )

    assert [job.external_id for job in jobs] == ["de-midwife-123"]
    assert len(requests) == 1
    assert provider.last_request_count == 1


def test_jsearch_does_not_start_a_transient_retry_after_its_deadline() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        now[0] = 120.0
        return httpx.Response(503)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        max_transient_retries=2,
        search_budget_seconds=120.0,
        sleeper=delays.append,
        clock=lambda: now[0],
    )

    with pytest.raises(JSearchProviderUnavailableError):
        provider.search(DiscoveryQuery(text="midwife · midwifery · hebamme"))

    assert len(requests) == 1
    assert provider.last_request_count == 1
    assert delays == []


def test_jsearch_honors_retry_after_once_and_accounts_for_retry() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"status": "OK", "data": [_jsearch_row()]})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
        sleeper=delays.append,
    )
    query = DiscoveryQuery(text="midwife", location="München")

    jobs = provider.search(query)

    assert [job.external_id for job in jobs] == ["de-midwife-123"]
    assert len(requests) == 2
    assert provider.last_request_count == 2
    assert provider.maximum_request_count(query) == 2
    assert delays == [0.0]


def test_jsearch_exhausted_rate_limit_is_sanitized_and_stops_fanout() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"})

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(JSearchRateLimitError):
        provider.search(
            DiscoveryQuery(
                text="midwife · midwifery · hebamme",
                location="München",
            )
        )

    # One initial request plus one bounded retry; later focused variants do
    # not continue hammering an account-wide rate limit.
    assert len(requests) == 2
    assert provider.last_request_count == 2


def test_jsearch_rate_limit_error_envelope_is_sanitized_and_stops_fanout() -> None:
    requests: list[httpx.Request] = []
    response_canary = "query-or-provider-body-must-not-be-exposed"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "ERROR",
                "error": {
                    "code": "TOO_MANY_REQUESTS",
                    "message": response_canary,
                },
            },
        )

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
    )

    with pytest.raises(JSearchRateLimitError) as caught:
        provider.search(DiscoveryQuery(text="midwife · midwifery · hebamme"))

    assert len(requests) == 1
    assert response_canary not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": 429, "error": "allowance exhausted"},
        {"status": "ERROR", "error": "rate_limit_exceeded"},
    ],
)
def test_jsearch_recognizes_bounded_rate_limit_envelope_variants(
    payload: dict[str, object],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=2,
    )

    with pytest.raises(JSearchRateLimitError):
        provider.search(DiscoveryQuery(text="midwife · hebamme"))

    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "ERROR", "error": {"message": "private provider detail"}},
        {"status": "OK", "data": {"jobs": {"unexpected": "shape"}}},
        {"status": "mystery", "data": {"jobs": []}},
    ],
)
def test_jsearch_rejects_unsupported_or_unsuccessful_envelopes_without_body_details(
    payload: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=payload)

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    with pytest.raises(JSearchResponseError) as caught:
        provider.search(DiscoveryQuery(text="midwife"))

    assert "private provider detail" not in str(caught.value)
    assert "unexpected" not in str(caught.value)


def test_jsearch_skips_malformed_rows_but_keeps_valid_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": [
                    {"job_id": "broken", "job_title": "No source"},
                    _jsearch_row(),
                ]
            },
        )

    provider = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    jobs = provider.search(DiscoveryQuery(text="midwife", location="München"))

    assert [job.external_id for job in jobs] == ["de-midwife-123"]


def test_jsearch_failure_is_sanitized_and_never_places_key_in_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, text="invalid credential")

    provider = OpenWebNinjaJSearchProvider(
        "private-key-must-not-leak",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=1,
    )

    with pytest.raises(JSearchAuthenticationError) as caught:
        provider.search(DiscoveryQuery(text="midwife", location="München"))

    assert "private-key-must-not-leak" not in str(caught.value)
    assert len(requests) == 1
    assert "private-key-must-not-leak" not in str(requests[0].url)


def test_jsearch_plan_failure_is_sanitized_and_fails_fast() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, text="plan details must not be retained")

    provider = OpenWebNinjaJSearchProvider(
        "private-key-must-not-leak",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=3,
    )

    with pytest.raises(JSearchPlanError) as caught:
        provider.search(DiscoveryQuery(text="midwife · midwifery · hebamme", location="München"))

    assert "private-key-must-not-leak" not in str(caught.value)
    assert "plan details" not in str(caught.value)
    assert len(requests) == 1


def test_jsearch_request_fanout_is_costed_per_actual_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": [_jsearch_row()]})

    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = OpenWebNinjaJSearchProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_requests=2,
    )
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0.005,
        cost_is_per_request=True,
    )

    provider.search(
        DiscoveryQuery(
            text="midwife · midwifery",
            desired_terms=["midwife", "midwifery"],
        )
    )

    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.provider == "openwebninja-jsearch"
    assert row.unit_count == 2
    assert row.estimated_cost_usd == pytest.approx(0.01)


def test_jsearch_settings_permission_and_container_wiring(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'jsearch.db').as_posix()}",
        OPENWEBNINJA_JSEARCH_API_KEY="secret",
        BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS=2,
        BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD=0.005,
        _env_file=None,
    )
    assert settings.openwebninja_jsearch_api_key_value == "secret"
    assert settings.openwebninja_jsearch_max_requests == 2
    assert permission_key_for_provider("openwebninja-jsearch") == "jsearch"

    container = ApplicationContainer(settings)
    mesh = container.job_discovery_provider()

    assert "openwebninja-jsearch" in [provider.name for provider in mesh.primary_providers]
    assert container.provider_availability()["jsearch"] == (True, "Configured")


def test_hosted_jsearch_remains_closed_until_processor_review(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'hosted-jsearch.db').as_posix()}",
        app_environment="staging",
        OPENWEBNINJA_JSEARCH_API_KEY="secret",
        processor_review_completed=False,
        _env_file=None,
    )
    container = ApplicationContainer(settings)

    assert container.provider_availability()["jsearch"][0] is False
    assert "openwebninja-jsearch" not in [
        provider.name for provider in container.job_discovery_provider().primary_providers
    ]
