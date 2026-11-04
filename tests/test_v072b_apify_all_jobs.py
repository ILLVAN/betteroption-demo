from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from betteroption.discovery import DiscoveryQuery
from betteroption.providers.apify_all_jobs import (
    AllJobsAuthenticationError,
    AllJobsPlanError,
    AllJobsRateLimitError,
    AllJobsRequestError,
    AllJobsResponseError,
    AllJobsUnavailableError,
    ApifyAllJobsDiscoveryProvider,
)


def _actor_row() -> dict[str, object]:
    return {
        "processor": "https://apify.com/private/processor",
        "processed_at": "2026-08-04T10:00:00Z",
        "platform": "LinkedIn",
        "platform_url": "https://www.linkedin.com/jobs/view/123",
        "official_url": "https://careers.acme.example/jobs/embedded-engineer",
        "title": "Embedded Software Engineer",
        "posted_date": "2026-08-02",
        "valid_through": "2026-09-02",
        "location": {
            "raw": "Frankfurt am Main, Hessen, Germany",
            "locality": "Frankfurt am Main",
            "region": "Hessen",
            "postal_code": "60311",
            "country": "Germany",
            "country_code": "DE",
            "latitude": 50.1109,
            "longitude": 8.6821,
        },
        "is_remote": True,
        "description": "<p>Build embedded products and automated tests.</p>",
        "job_type": "Full-time",
        "job_level": "Mid",
        "job_function": "Engineering",
        "skills": "Python, C++, Test automation",
        "work_from_home": "Hybrid (2 days from home)",
        "salary_period": "yearly",
        "salary_minimum": 70_000,
        "salary_maximum": 90_000,
        "salary_currency": "EUR",
        "company_name": "Acme Robotics",
        "company_website": "https://acme.example",
        # These actor enrichment fields are deliberately outside the adapter's
        # public Explore mapping and must not reach a result.
        "emails": ["contact-field-canary@example.invalid"],
        "phones": ["contact-phone-canary"],
        "social_links": {"linkedin": "contact-social-canary"},
    }


def _completed_run_handler(
    rows: list[dict[str, object]],
    requests: list[httpx.Request] | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
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
        return httpx.Response(200, json=rows)

    return handler


def test_all_jobs_default_actor_request_uses_cost_safe_caps_and_public_schema() -> None:
    requests: list[httpx.Request] = []

    provider = ApifyAllJobsDiscoveryProvider(
        "private-apify-token",
        client=httpx.Client(
            transport=httpx.MockTransport(_completed_run_handler([_actor_row()], requests))
        ),
        platforms="LinkedIn, Indeed; Glassdoor",
        distance_miles=75,
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="embedded engineer · python developer · test automation",
            desired_terms=["embedded engineer", "python developer", "test automation"],
            location="60311 Frankfurt am Main",
            remote_only=True,
            limit=300,
        )
    )

    assert len(requests) == 2
    request = requests[0]
    assert request.method == "POST"
    assert request.url.copy_with(query=None) == httpx.URL(ApifyAllJobsDiscoveryProvider.endpoint)
    assert request.url.params["maxItems"] == "120"
    assert request.url.params["timeout"] == "285"
    assert request.url.params["waitForFinish"] == "60"
    assert request.url.params["maxTotalChargeUsd"] == "0.4"
    assert request.headers["Authorization"] == "Bearer private-apify-token"
    assert "private-apify-token" not in str(request.url)
    assert "private-apify-token" not in request.content.decode()
    assert json.loads(request.content) == {
        "max_results": 20,
        "keyword": "embedded engineer",
        "country": "Germany",
        "location": "60311 Frankfurt am Main",
        "remote_only": True,
        "posted_since": "30 days",
        "platforms": ["LinkedIn", "Indeed", "Glassdoor"],
        "distance": 75,
    }
    assert requests[1].url.path == "/v2/datasets/safeDataset123/items"
    assert requests[1].url.params["limit"] == "120"
    assert requests[1].url.params["clean"] == "1"
    assert provider.last_request_count == 2
    assert provider.maximum_request_count(DiscoveryQuery(text="embedded")) == 6

    assert len(jobs) == 1
    job = jobs[0]
    assert job.provider == "apify-all-jobs"
    assert job.external_id == "https://careers.acme.example/jobs/embedded-engineer"
    assert job.title == "Embedded Software Engineer"
    assert job.company == "Acme Robotics"
    assert job.location == "Frankfurt am Main, Hessen, Germany"
    assert job.remote is True
    assert str(job.source_url) == "https://careers.acme.example/jobs/embedded-engineer"
    assert job.published_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert "Build embedded products and automated tests." in job.summary
    assert "Salary: EUR 70,000–90,000 per year" in job.summary
    assert "All Jobs Scraper" in job.tags
    assert "Source: LinkedIn" in job.tags
    serialized = job.model_dump_json()
    assert "contact-field-canary" not in serialized
    assert "contact-phone-canary" not in serialized
    assert "contact-social-canary" not in serialized
    assert "processor" not in serialized
    assert "private-apify-token" not in serialized


def test_all_jobs_omits_unused_optional_inputs_and_uses_platform_url_fallback() -> None:
    row = _actor_row()
    row["official_url"] = None
    row["is_remote"] = None
    row["work_from_home"] = None
    row["location"] = {
        "locality": "Berlin",
        "region": "Berlin",
        "country": "Germany",
        "country_code": "DE",
    }
    requests: list[httpx.Request] = []

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(_completed_run_handler([row], requests))),
        posted_since="",
        max_total_charge_usd=0,
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="software jobs in europe",
            desired_terms=["software engineer", "test engineer"],
            location="DE",
            worldwide=True,
        )
    )

    assert json.loads(requests[0].content) == {
        "max_results": 20,
        "keyword": "software engineer",
        "country": "Germany",
    }
    assert dict(requests[0].url.params) == {
        "maxItems": "120",
        "timeout": "285",
        "waitForFinish": "60",
    }
    assert jobs[0].remote is False
    assert jobs[0].location == "Berlin, Germany, DE"
    assert str(jobs[0].source_url) == "https://www.linkedin.com/jobs/view/123"


def test_all_jobs_readback_guard_is_independent_of_per_platform_result_limit() -> None:
    requests: list[httpx.Request] = []

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(_completed_run_handler([], requests))),
        max_results_per_platform=80,
        max_items=120,
        timeout_seconds=900,
    )
    provider.search(
        DiscoveryQuery(
            text="data engineer",
            location="Frankfurt am Main",
            limit=120,
            regional_radius_km=50,
        )
    )

    assert provider.timeout_seconds == 285
    assert requests[0].url.params["maxItems"] == "120"
    payload = json.loads(requests[0].content)
    assert payload["max_results"] == 80
    assert payload["distance"] == 50


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AllJobsAuthenticationError),
        (403, AllJobsPlanError),
        (408, AllJobsUnavailableError),
        (429, AllJobsRateLimitError),
        (503, AllJobsUnavailableError),
    ],
)
def test_all_jobs_failures_are_distinct_and_secret_safe(
    status: int,
    error_type: type[Exception],
) -> None:
    canary = "provider-body-must-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, text=canary)

    provider = ApifyAllJobsDiscoveryProvider(
        "private-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(error_type) as caught:
        provider.search(DiscoveryQuery(text="embedded engineer", location="Berlin"))

    assert canary not in str(caught.value)
    assert "private-token" not in str(caught.value)
    assert provider.last_request_count == 1


def test_all_jobs_rejects_unsupported_dataset_without_echoing_it() -> None:
    canary = "unsupported-response-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": {"items": canary}})

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AllJobsResponseError) as caught:
        provider.search(DiscoveryQuery(text="embedded engineer", location="Berlin"))

    assert canary not in str(caught.value)


def test_all_jobs_skips_malformed_rows_and_deduplicates_source_urls() -> None:
    duplicate = _actor_row()
    duplicate["platform_url"] = "https://different.example/job"

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(
            transport=httpx.MockTransport(
                _completed_run_handler(
                    [
                        {"title": "Missing URL"},
                        {"official_url": "https://example.test/missing-title"},
                        _actor_row(),
                        duplicate,
                    ]
                )
            )
        ),
    )

    jobs = provider.search(DiscoveryQuery(text="embedded engineer", location="Berlin"))

    assert [job.external_id for job in jobs] == [
        "https://careers.acme.example/jobs/embedded-engineer"
    ]


def test_all_jobs_requires_country_without_disclosing_location_or_calling_actor() -> None:
    requests: list[httpx.Request] = []

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(_completed_run_handler([], requests))),
    )

    with pytest.raises(AllJobsRequestError) as caught:
        provider.search(
            DiscoveryQuery(text="embedded engineer", location="Unresolvable Place Canary")
        )

    assert requests == []
    assert "Unresolvable Place Canary" not in str(caught.value)
    assert provider.last_request_count == 0


@pytest.mark.parametrize("location", ["DE", "Germany", "Deutschland", "60311"])
def test_all_jobs_normalizes_country_labels_without_mistaking_them_for_a_city(
    location: str,
) -> None:
    requests: list[httpx.Request] = []

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(_completed_run_handler([], requests))),
    )
    provider.search(DiscoveryQuery(text="embedded engineer", location=location))

    payload = json.loads(requests[0].content)
    assert payload["country"] == "Germany"
    if location in {"DE", "Germany", "Deutschland"}:
        assert "location" not in payload


def test_all_jobs_polls_one_paid_run_and_keeps_a_timed_out_partial_dataset() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "boundedRun123",
                        "status": "RUNNING",
                        "defaultDatasetId": "partialDataset123",
                    }
                },
            )
        if "/actor-runs/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "boundedRun123",
                        "status": "TIMED-OUT",
                        "defaultDatasetId": "partialDataset123",
                    }
                },
            )
        return httpx.Response(200, json=[_actor_row()])

    provider = ApifyAllJobsDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    jobs = provider.search(DiscoveryQuery(text="python", location="München"))

    assert [job.title for job in jobs] == ["Embedded Software Engineer"]
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert sum(request.method == "POST" for request in requests) == 1
    assert provider.last_request_count == 3
