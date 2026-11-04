from __future__ import annotations

from datetime import datetime, timedelta, timezone

from betteroption.discovery import (
    ArbeitnowDiscoveryProvider,
    DiscoveredJob,
    DiscoveryQuery,
    finalize_discovered_jobs,
)


def _job(
    identity: str,
    *,
    title: str,
    summary: str,
    location: str = "München",
) -> DiscoveredJob:
    return DiscoveredJob(
        provider="arbeitnow",
        external_id=identity,
        title=title,
        company="Example Employer",
        location=location,
        summary=summary,
        source_url=f"https://jobs.example.test/roles/{identity}",
    )


def _midwife_query() -> DiscoveryQuery:
    return DiscoveryQuery(
        text="midwife · midwifery · supporting childbirth · Python",
        location="München",
        desired_terms=[
            "midwife",
            "midwifery",
            "supporting childbirth",
            # A secondary skill must not admit an unrelated role by itself.
            "Python",
        ],
        regional_target=30,
    )


def test_structured_midwife_search_drops_nearby_jobs_with_only_generic_overlap() -> None:
    jobs = [
        _job(
            "midwife",
            title="Registered Midwife",
            summary="Support families during childbirth in a maternity team.",
        ),
        _job(
            "hebamme",
            title="Hebamme (m/w/d)",
            summary="Arbeit im Kreißsaal und auf der Wochenbettstation.",
        ),
        _job(
            "business",
            title="Senior Business Analyst",
            summary="Supporting a finance team with reporting and Python dashboards.",
        ),
        _job(
            "electronics",
            title="Team Lead Airborne Electronics",
            summary="Supporting engineering delivery near Munich.",
        ),
    ]

    ranked = finalize_discovered_jobs(_midwife_query(), jobs)

    assert [job.external_id for job in ranked] == ["midwife", "hebamme"]
    assert all((job.keyword_relevance or 0) >= 25 for job in ranked)


def test_shared_arbeitnow_feed_cache_is_filtered_again_for_each_persona_query() -> None:
    provider = ArbeitnowDiscoveryProvider(max_pages=1)
    provider._cached_candidates = [  # noqa: SLF001 - explicit cache-isolation regression
        _job(
            "midwife",
            title="Registered Midwife",
            summary="Provide maternity and childbirth care.",
        ),
        _job(
            "embedded",
            title="Embedded Software Engineer",
            summary="Develop firmware and automated tests.",
        ),
    ]
    provider._cache_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)  # noqa: SLF001

    engineer = provider.search(
        DiscoveryQuery(
            text="embedded software",
            location="München",
            desired_terms=["embedded software"],
        )
    )
    midwife = provider.search(_midwife_query())

    assert [job.external_id for job in engineer] == ["embedded"]
    assert [job.external_id for job in midwife] == ["midwife"]
    assert provider.last_request_count == 0


def test_free_form_search_without_structured_compass_terms_keeps_provider_results() -> None:
    job = _job(
        "custom",
        title="Community Programme Coordinator",
        summary="Coordinate local services.",
    )

    ranked = finalize_discovered_jobs(
        DiscoveryQuery(text="open opportunities", location="München"),
        [job],
    )

    assert [item.external_id for item in ranked] == ["custom"]
