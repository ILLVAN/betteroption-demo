from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from betteroption.database import Database
from betteroption.discovery import DiscoveryQuery, SeniorityBand
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
)
from betteroption.providers.apify_eures import ApifyEuresDiscoveryProvider
from betteroption.providers.apify_jobspipe import (
    ApifyJobsPipeDiscoveryProvider,
    JobsPipeAuthenticationError,
    JobsPipePlanError,
    JobsPipeRateLimitError,
    JobsPipeResponseError,
    JobsPipeUnavailableError,
)


def _jobspipe_row() -> dict[str, object]:
    return {
        "id": "jp_7f3a9c21",
        "job_title": "Embedded Python Engineer",
        "company": "Acme Robotics",
        "company_domain": "acme.example",
        "location": "Frankfurt am Main, Germany",
        "country_code": "DE",
        "remote": False,
        "seniority": "junior",
        "date_posted": "2026-08-02",
        "min_annual_salary_usd": 60_000,
        "max_annual_salary_usd": 75_000,
        "final_url": "https://acme.example/careers/embedded-python-engineer",
        "technology_slugs": ["python", "embedded-systems"],
        "description": "<p>Build embedded prototypes and automated tests.</p>",
        "source": "greenhouse",
        "employment_type": "full-time",
    }


def test_jobspipe_uses_its_own_actor_identity_payload_and_public_schema() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[_jobspipe_row()])

    provider = ApifyJobsPipeDiscoveryProvider(
        "private-apify-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_results=150,
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="embedded engineer · python developer · test automation",
            desired_terms=[
                "embedded engineer",
                "python developer",
                "test automation",
                "embedded Linux",
                "CAN bus",
            ],
            location="60311 Frankfurt am Main",
            limit=180,
            seniority_targets=[SeniorityBand.JUNIOR, SeniorityBand.MID],
        )
    )

    assert len(requests) == 4
    request = requests[0]
    assert all(item.method == "POST" for item in requests)
    assert all(item.url.params["maxItems"] == "38" for item in requests)
    assert all(
        item.url.path != httpx.URL(ApifyEuresDiscoveryProvider.endpoint).path for item in requests
    )
    assert provider.name == "apify-jobspipe"
    assert provider.name != ApifyEuresDiscoveryProvider.name
    assert request.headers["Authorization"] == "Bearer private-apify-token"
    assert "private-apify-token" not in str(request.url)
    assert "private-apify-token" not in request.content.decode()
    payloads = [json.loads(item.content) for item in requests]
    assert {
        (
            tuple(payload.get("searchTerms", [])),
            tuple(payload.get("descriptionKeywords", [])),
            tuple(payload["countries"]),
        )
        for payload in payloads
    } == {
        (("embedded",), (), ("DE",)),
        (("engineer",), (), ("DE",)),
        ((), ("embedded",), ("DE",)),
        (("embedded",), (), ()),
    }
    assert all(payload["postedWithinDays"] == 60 for payload in payloads)
    assert all(payload["maxItems"] == 38 for payload in payloads)
    assert all("seniority" not in payload for payload in payloads)
    assert all(
        not (payload.get("searchTerms") and payload.get("descriptionKeywords"))
        for payload in payloads
    )
    assert provider.last_request_count == 4
    assert provider.maximum_request_count(DiscoveryQuery(text="embedded")) == 1

    assert len(jobs) == 1
    job = jobs[0]
    assert job.provider == "apify-jobspipe"
    assert job.external_id == "jp_7f3a9c21"
    assert job.title == "Embedded Python Engineer"
    assert job.company == "Acme Robotics"
    assert job.location == "Frankfurt am Main, Germany"
    assert str(job.source_url) == ("https://acme.example/careers/embedded-python-engineer")
    assert job.published_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert "Build embedded prototypes and automated tests." in job.summary
    assert "Salary: USD 60,000–75,000 per year" in job.summary
    assert "JobsPipe" in job.tags
    assert "Source: greenhouse" in job.tags
    assert "private-apify-token" not in job.model_dump_json()


def test_jobspipe_remote_worldwide_query_and_documented_url_variant() -> None:
    row = _jobspipe_row()
    row.pop("final_url")
    row["url"] = "https://jobs.example/remote-role"
    row["remote"] = "true"
    row["min_annual_salary_usd"] = 0
    row["max_annual_salary_usd"] = 0

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[row])

    provider = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="python developer OR embedded engineer",
            location="Berlin",
            worldwide=True,
            remote_only=True,
        )
    )

    payloads = [json.loads(request.content) for request in requests]
    assert [payload["searchTerms"] for payload in payloads] == [
        ["python"],
        ["developer"],
        ["embedded"],
    ]
    assert all(payload["countries"] == [] for payload in payloads)
    assert all(payload["postedWithinDays"] == 60 for payload in payloads)
    assert all(payload["maxItems"] == 100 for payload in payloads)
    assert all(payload["remote"] is True for payload in payloads)
    assert all(request.url.params["maxItems"] == "100" for request in requests)
    assert jobs[0].remote is True
    assert str(jobs[0].source_url) == "https://jobs.example/remote-role"
    assert "USD 0" not in jobs[0].summary


def test_jobspipe_omits_unsupported_seniority_values_instead_of_zeroing_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    provider = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.search(
        DiscoveryQuery(
            text="engineering manager or working student",
            location="Berlin",
            seniority_targets=[SeniorityBand.INTERN, SeniorityBand.MANAGER],
        )
    )

    assert all("seniority" not in json.loads(request.content) for request in requests)


@pytest.mark.parametrize("location", ["DE", "Germany", "Deutschland", "60311"])
def test_jobspipe_normalizes_country_names_and_bare_german_postcodes(location: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    provider = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.search(DiscoveryQuery(text="embedded engineer", location=location))

    countries = [json.loads(request.content)["countries"] for request in requests]
    assert ["DE"] in countries
    assert all(value in (["DE"], []) for value in countries)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, JobsPipeAuthenticationError),
        (403, JobsPipePlanError),
        (429, JobsPipeRateLimitError),
        (503, JobsPipeUnavailableError),
    ],
)
def test_jobspipe_failures_are_distinct_and_secret_safe(
    status: int,
    error_type: type[Exception],
) -> None:
    canary = "private-token-or-provider-body-must-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, text=canary)

    provider = ApifyJobsPipeDiscoveryProvider(
        "private-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(error_type) as caught:
        provider.search(DiscoveryQuery(text="embedded engineer"))

    assert canary not in str(caught.value)
    assert "private-token" not in str(caught.value)
    assert provider.last_request_count == provider.maximum_request_count(
        DiscoveryQuery(text="embedded engineer")
    )


def test_jobspipe_rejects_an_unsupported_dataset_envelope_without_echoing_it() -> None:
    canary = "unsupported-response-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": {"jobs": canary}})

    provider = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(JobsPipeResponseError) as caught:
        provider.search(DiscoveryQuery(text="embedded engineer"))

    assert canary not in str(caught.value)


def test_jobspipe_deduplicates_stable_ids_and_skips_malformed_rows() -> None:
    duplicate = _jobspipe_row()
    duplicate["final_url"] = "https://duplicate.example/job"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                {"id": "missing-url", "job_title": "Malformed"},
                _jobspipe_row(),
                duplicate,
            ],
        )

    provider = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    jobs = provider.search(DiscoveryQuery(text="embedded engineer"))

    assert [job.external_id for job in jobs] == ["jp_7f3a9c21"]


def test_jobspipe_operation_is_recorded_separately_from_eures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[_jobspipe_row()])

    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = ApifyJobsPipeDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0.0005,
        cost_is_per_request=True,
    )

    provider.search(DiscoveryQuery(text="embedded engineer", location="Frankfurt"))

    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.provider == "apify-jobspipe"
    assert row.provider != "apify-eures"
    assert row.unit_count == 3
    assert row.result_count == 1
    assert row.estimated_cost_usd == pytest.approx(0.0015)
