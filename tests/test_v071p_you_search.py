from __future__ import annotations

import httpx
import pytest

from betteroption.discovery import DiscoveryError, DiscoveryQuery
from betteroption.discovery_sources import YouWebDiscoveryProvider


def _query() -> DiscoveryQuery:
    return DiscoveryQuery(
        text="python engineer",
        location="Berlin",
        desired_terms=["python engineer"],
        limit=25,
    )


def test_you_search_accepts_current_json_and_markdown_livecrawl_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "results": {
                    "web": [
                        {
                            "id": "you-result-1",
                            "url": "https://careers.example.com/jobs/python-engineer-123",
                            "title": "Senior Python Engineer in Berlin",
                            "contents": {
                                "markdown": (
                                    "# Senior Python Engineer\n\n"
                                    "Acme is hiring in Berlin. Build Python services and own "
                                    "production reliability.\n\n"
                                    "## Responsibilities\n\nDevelop and test backend services."
                                )
                            },
                            "page_age": "2026-08-01T09:30:00Z",
                            "date": "2026-07-31T08:00:00Z",
                        }
                    ]
                }
            },
        )

    provider = YouWebDiscoveryProvider(
        "private-test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    jobs = provider.search(_query())

    assert len(jobs) == 1
    assert jobs[0].provider == "you-web"
    assert jobs[0].external_id == "you-result-1"
    assert "Build Python services" in jobs[0].summary
    assert "#" not in jobs[0].summary
    assert jobs[0].published_at is None


def test_you_search_recovers_linked_rows_from_markdown_response() -> None:
    markdown = """
## [Python Platform Engineer in Berlin](https://jobs.example.com/jobs/python-platform-456)

Example GmbH is hiring a Python Platform Engineer in Berlin. Responsibilities
include backend services, automated testing, and production operations.

## [Best engineering job boards](https://example.com/blog/job-boards)

A general directory of job search websites.
"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text=markdown,
            headers={"Content-Type": "text/markdown; charset=utf-8"},
        )

    provider = YouWebDiscoveryProvider(
        "private-test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    jobs = provider.search(_query())

    assert [job.title for job in jobs] == ["Python Platform Engineer in Berlin"]
    assert str(jobs[0].source_url) == "https://jobs.example.com/jobs/python-platform-456"
    assert "automated testing" in jobs[0].summary
    assert jobs[0].tags == ["Source verification required"]


def test_you_search_rejects_malformed_web_collection_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"results": {"web": {"unexpected": "shape"}}},
        )

    provider = YouWebDiscoveryProvider(
        "do-not-leak-this-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(DiscoveryError) as error:
        provider.search(_query())

    assert "unavailable" in str(error.value).casefold()
    assert "do-not-leak-this-key" not in str(error.value)
