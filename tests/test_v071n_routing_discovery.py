from __future__ import annotations

from datetime import datetime, timezone

from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryQuery,
    _web_search_texts,
    web_discovery_document_is_error_landing,
    web_discovery_url_is_error_landing,
)
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.mobility import routing_destinations_from_job
from betteroption.url_ingestion import FetchedDocument


def _job(*, location: str, remote_fact: str | None = None) -> JobPosting:
    source_text = f"Example Employer seeks an engineer. Workplace: {location}."
    facts = []
    if remote_fact is not None:
        source_text = f"{source_text} Work model: {remote_fact}."
        facts.append(
            JobFact(
                key="work_model.remote",
                value=remote_fact,
                kind=JobFactKind.OFFER,
                evidence_quote=remote_fact,
            )
        )
    return JobPosting(
        title="Engineer",
        company="Example Employer",
        location=location,
        summary="Build useful products.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="Manual input",
        source_text=source_text,
        facts=facts,
    )


def test_remote_only_jobs_do_not_create_route_destinations() -> None:
    assert routing_destinations_from_job(_job(location="Remote – Europe")) == []
    assert (
        routing_destinations_from_job(
            _job(location="Company HQ, Berlin", remote_fact="fully remote in Germany")
        )
        == []
    )

    # A genuine physical alternative remains routable, and hybrid is not
    # silently reclassified as remote-only.
    assert routing_destinations_from_job(_job(location="Berlin / Remote")) == ["Berlin"]
    assert routing_destinations_from_job(_job(location="Berlin", remote_fact="hybrid remote")) == [
        "Berlin"
    ]


def test_searches_split_role_concepts_and_keep_only_clear_exclusions() -> None:
    searches = _web_search_texts(
        DiscoveryQuery(
            text="embedded software · test automation",
            location="Frankfurt",
            excluded_terms=["military", "intern role"],
        )
    )

    assert searches
    assert any('"embedded software"' in value for value in searches)
    assert any('"test automation"' in value for value in searches)
    assert all("-military" in value for value in searches)
    assert all("intern role" not in value for value in searches)
    assert all('"embedded software" "test automation"' not in value for value in searches)


def test_suspended_redirects_and_explicit_http_200_error_pages_are_closed() -> None:
    assert web_discovery_url_is_error_landing(
        "https://suspended-domain.net/index.php?host=careerium.unaux.com"
    )
    assert web_discovery_document_is_error_landing(
        "https://careers.example/jobs/123",
        "404 — Diese URL existiert nicht. Zurück zu allen Stellen.",
    )

    class RedirectingFetcher:
        def fetch(self, url: str) -> FetchedDocument:
            final_url = (
                "https://suspended-domain.net/index.php?host=careerium.unaux.com"
                if "careerium" in url
                else url
            )
            text = (
                "Domain is suspended" if "careerium" in url else "404 — Diese URL existiert nicht"
            )
            return FetchedDocument(
                requested_url=url,
                final_url=final_url,
                status_code=200,
                content_type="text/html",
                text=text,
                fetched_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )

    jobs = [
        DiscoveredJob(
            provider="exa-fallback",
            external_id=name,
            title="Applied AI Engineer",
            company="Example",
            location="Frankfurt",
            source_url=url,
        )
        for name, url in (
            ("careerium", "https://careerium.unaux.com/jobs/applied-ai"),
            ("missing", "https://careers.example/jobs/missing"),
        )
    ]
    policy = DiscoveryAvailabilityFilter(
        fetcher=RedirectingFetcher(),
        maximum_checks=10,
        total_timeout_seconds=2,
    )

    assert policy.keep_open_or_unknown(jobs) == []
