import json
import sys
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.url_ingestion import (  # noqa: E402
    PublicUrlFetcher,
    UrlFailureKind,
    UrlIngestionError,
    extract_job_text,
    save_fetched_document,
)
from bs4 import XMLParsedAsHTMLWarning  # noqa: E402


PUBLIC_IP = "93.184.216.34"


def client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


class TestUrlIngestion:
    def test_json_ld_job_posting_is_preferred_over_page_chrome(self) -> None:
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Embedded Engineer",
            "hiringOrganization": {"name": "Acme Automation"},
            "jobLocation": {"address": "Frankfurt"},
            "description": "Build embedded prototypes with C++ and Python.",
            "qualifications": "Professional C++ experience",
        }
        html = (
            "<html><body><nav>Irrelevant navigation</nav>"
            f'<script type="application/ld+json">{json.dumps(posting)}</script>'
            "<main>Short marketing text</main></body></html>"
        )

        text = extract_job_text(html, "text/html")

        assert "Title: Embedded Engineer" in text
        assert "Company: Acme Automation" in text
        assert "Build embedded prototypes" in text
        assert "Irrelevant navigation" not in text

    def test_xml_looking_json_ld_fragment_is_cleaned_without_a_runtime_warning(self) -> None:
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Systems Engineer",
            "hiringOrganization": {"name": "Stable Systems"},
            "description": (
                '<?xml version="1.0"?><section><p>Build reliable embedded systems.</p></section>'
            ),
        }
        html = f'<html><script type="application/ld+json">{json.dumps(posting)}</script></html>'

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = extract_job_text(html, "text/html")

        assert "Build reliable embedded systems." in text
        assert not any(isinstance(item.message, XMLParsedAsHTMLWarning) for item in caught)

    def test_fetcher_returns_public_job_text_and_honors_size_contract(self) -> None:
        html = (
            "<html><main><h1>Embedded Engineer</h1><p>Acme Automation needs C++ and "
            "Python for prototype development in Frankfurt with hybrid work.</p></main></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=html,
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        document = fetcher.fetch("https://example.com/jobs/123")

        assert document.final_url == "https://example.com/jobs/123"
        assert document.status_code == 200
        assert "Embedded Engineer" in document.text
        assert "<main>" not in document.text

        with TemporaryDirectory() as directory:
            snapshot = save_fetched_document(document, Path(directory))
            snapshot_text = snapshot.read_text(encoding="utf-8")

        assert '"status_code": 200' in snapshot_text
        assert "Embedded Engineer" in snapshot_text

    def test_fetcher_rejects_collection_page_with_distinct_json_ld_jobs(self) -> None:
        postings = [
            {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "@id": "https://example.com/jobs/embedded-123",
                "url": "https://example.com/jobs/embedded-123",
                "title": "Embedded Engineer",
                "hiringOrganization": {"name": "Acme Automation"},
                "jobLocation": {"address": "Frankfurt"},
                "description": "Build embedded prototypes with C++ and Python.",
            },
            {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "@id": "https://example.com/jobs/cloud-456",
                "url": "https://example.com/jobs/cloud-456",
                "title": "Cloud Engineer",
                "hiringOrganization": {"name": "Acme Automation"},
                "jobLocation": {"address": "Berlin"},
                "description": "Build reliable cloud platforms with Python and Kubernetes.",
            },
        ]
        html = (
            "<html><body><main><h1>Open jobs</h1></main>"
            f'<script type="application/ld+json">{json.dumps(postings)}</script>'
            "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="multiple distinct job postings") as caught:
            fetcher.fetch("https://example.com/jobs")

        assert caught.value.kind == UrlFailureKind.UNSUPPORTED
        assert caught.value.http_status == 200

    def test_fetcher_rejects_direct_json_ld_collection_and_accepts_one_posting(self) -> None:
        postings = [
            {
                "@type": "JobPosting",
                "@id": "https://example.com/jobs/embedded-123",
                "title": "Embedded Engineer",
                "hiringOrganization": {"name": "Acme Automation"},
                "jobLocation": {"address": "Frankfurt"},
                "description": "Build embedded prototypes with C++ and Python.",
            },
            {
                "@type": "JobPosting",
                "@id": "https://example.com/jobs/cloud-456",
                "title": "Cloud Engineer",
                "hiringOrganization": {"name": "Acme Automation"},
                "jobLocation": {"address": "Berlin"},
                "description": "Build reliable cloud platforms with Python and Kubernetes.",
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            payload = postings[0] if request.url.path.endswith("embedded-123") else postings
            return httpx.Response(
                200,
                headers={"content-type": "application/ld+json"},
                text=json.dumps(payload),
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="multiple distinct job postings") as caught:
            fetcher.fetch("https://example.com/jobs")

        assert caught.value.kind == UrlFailureKind.UNSUPPORTED
        assert caught.value.http_status == 200
        document = fetcher.fetch("https://example.com/jobs/embedded-123")
        assert document.content_type == "application/ld+json"
        assert "Embedded Engineer" in document.text

    @pytest.mark.parametrize(
        ("first_identity", "second_identity"),
        [
            (
                {"@id": "https://example.com/jobs/embedded-123"},
                {"url": "https://example.com/jobs/embedded-123"},
            ),
            ({}, {}),
        ],
        ids=("explicit-identity", "title-organization-location"),
    )
    def test_fetcher_accepts_duplicate_json_ld_for_one_job(
        self,
        first_identity: dict[str, str],
        second_identity: dict[str, str],
    ) -> None:
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            **first_identity,
            "title": "Embedded Engineer",
            "hiringOrganization": {"name": "Acme Automation"},
            "jobLocation": {"address": "Frankfurt"},
            "description": "Build embedded prototypes with C++ and Python.",
            "qualifications": "Professional C++ experience",
        }
        duplicate = {
            **posting,
            "@id": second_identity.get("@id"),
            "url": second_identity.get("url"),
            "description": "The same vacancy rendered again with a longer description.",
        }
        duplicate = {key: value for key, value in duplicate.items() if value is not None}
        html = (
            "<html><body><main><h1>Embedded Engineer</h1></main>"
            f'<script type="application/ld+json">{json.dumps(posting)}</script>'
            f'<script type="application/ld+json">{json.dumps(duplicate)}</script>'
            "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        document = fetcher.fetch("https://example.com/jobs/embedded-123")

        assert "Title: Embedded Engineer" in document.text
        assert "Company: Acme Automation" in document.text

    def test_fetcher_blocks_private_network_targets_before_request(self) -> None:
        requested = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal requested
            requested = True
            return httpx.Response(200, text="should not be requested", request=request)

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: ["127.0.0.1"],
        )

        with pytest.raises(UrlIngestionError):
            fetcher.fetch("http://localhost/job")
        assert requested is False

    def test_fetcher_respects_robots_disallow(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(
                    200,
                    text="User-agent: *\nDisallow: /jobs/",
                    request=request,
                )
            return httpx.Response(200, text="job text", request=request)

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="robots.txt"):
            fetcher.fetch("https://example.com/jobs/123")

    def test_redirect_to_private_network_is_blocked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/internal"},
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: ["127.0.0.1"] if host == "127.0.0.1" else [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="private"):
            fetcher.fetch("https://example.com/jobs/123")

    def test_soft_expired_job_page_is_rejected(self) -> None:
        html = (
            "<html><main><h1>Job is no longer available</h1>"
            "<p>This position has been filled. Browse other opportunities at Acme.</p>"
            "</main></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="expired or unavailable") as caught:
            fetcher.fetch("https://example.com/jobs/expired")
        assert caught.value.kind == UrlFailureKind.EXPIRED
        assert caught.value.http_status == 200

    def test_visible_expired_badge_overrides_stale_job_posting_json_ld(self) -> None:
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "EMEA Embedded Solutions Engineering Graduate Program",
            "hiringOrganization": {"name": "Example Semiconductors"},
            "jobLocation": {"address": "Stutensee, Germany"},
            "description": (
                "Collaborate with stakeholders, develop embedded solutions, and support "
                "technical projects in a structured graduate programme."
            ),
        }
        html = (
            "<html><body>"
            f'<script type="application/ld+json">{json.dumps(posting)}</script>'
            "<main><h1>EMEA Embedded Solutions Engineering Graduate Program</h1>"
            "<span class='status'>Expired</span><p>Expired 27d ago</p></main>"
            "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=html,
                request=request,
            )

        fetcher = PublicUrlFetcher(
            client=client_with(handler),
            resolver=lambda host: [PUBLIC_IP],
        )

        with pytest.raises(UrlIngestionError, match="expired or unavailable") as caught:
            fetcher.fetch("https://example.com/jobs/stale-json-ld")

        assert caught.value.kind == UrlFailureKind.EXPIRED
        assert caught.value.http_status == 200
