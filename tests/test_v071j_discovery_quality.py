from __future__ import annotations

from datetime import datetime, timedelta, timezone

from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryQuery,
    finalize_discovered_jobs,
    rank_discovered_jobs,
)


def _web_job(
    provider: str,
    *,
    title: str,
    url: str,
    external_id: str,
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        external_id=external_id,
        title=title,
        company="Example Products",
        location="Berlin",
        summary="Embedded product development in a permanent engineering role.",
        source_url=url,
    )


def test_equally_relevant_web_results_are_not_ranked_by_provider_name() -> None:
    query = DiscoveryQuery(text="embedded", location="")
    brave = _web_job(
        "brave-web",
        title="Alpha Embedded Engineer",
        url="https://careers.brave-result.example/jobs/embedded",
        external_id="brave-result",
    )
    exa = _web_job(
        "exa-fallback",
        title="Zeta Embedded Engineer",
        url="https://careers.exa-result.example/jobs/embedded",
        external_id="exa-result",
    )

    ranked = rank_discovered_jobs(query, [brave, exa])

    assert [job.provider for job in ranked] == ["brave-web", "exa-fallback"]
    assert ranked[0].search_score == ranked[1].search_score


def test_duplicate_provider_does_not_replace_equal_first_seen_evidence() -> None:
    query = DiscoveryQuery(text="embedded", location="")
    url = "https://careers.example.com/jobs/embedded-engineer"
    brave = _web_job(
        "brave-web",
        title="Embedded Engineer - search result",
        url=f"{url}?utm_source=brave",
        external_id="brave-copy",
    )
    exa = _web_job(
        "exa-fallback",
        title="Embedded Engineer | Example Careers",
        url=f"{url}?utm_source=exa",
        external_id="exa-copy",
    )

    ranked = finalize_discovered_jobs(query, [brave, exa])

    assert len(ranked) == 1
    assert ranked[0].provider == "brave-web"
    assert ranked[0].external_id == "brave-copy"


def test_richer_duplicate_wins_without_a_provider_preference() -> None:
    query = DiscoveryQuery(text="embedded", location="")
    url = "https://careers.example.com/jobs/embedded-engineer"
    sparse = _web_job(
        "exa-fallback",
        title="Embedded Engineer",
        url=f"{url}?utm_source=exa",
        external_id="sparse",
    ).model_copy(update={"summary": ""})
    richer = _web_job(
        "brave-web",
        title="Embedded Engineer",
        url=f"{url}?utm_source=brave",
        external_id="richer",
    )

    ranked = finalize_discovered_jobs(query, [sparse, richer])

    assert len(ranked) == 1
    assert ranked[0].provider == "brave-web"
    assert ranked[0].external_id == "richer"


def test_compass_exclusion_conflict_is_visible_and_reduces_explore_score() -> None:
    query = DiscoveryQuery(
        text="embedded engineer",
        location="",
        desired_terms=["embedded engineer"],
        excluded_terms=["military"],
    )
    compatible = DiscoveredJob(
        provider="arbeitnow",
        external_id="compatible",
        title="Embedded Engineer",
        company="Example Products",
        location="Berlin",
        summary="Develop embedded products for industrial measurement.",
        source_url="https://careers.example.com/jobs/compatible",
    )
    conflict = compatible.model_copy(
        update={
            "external_id": "conflict",
            "summary": "Develop embedded products for military systems.",
            "source_url": "https://careers.example.com/jobs/conflict",
        }
    )

    ranked = rank_discovered_jobs(query, [conflict, compatible])
    by_id = {job.external_id: job for job in ranked}

    assert by_id["conflict"].exclusion_signals == ["military"]
    assert by_id["conflict"].compass_relevance < by_id["compatible"].compass_relevance
    assert by_id["conflict"].search_score < by_id["compatible"].search_score


def test_known_posting_freshness_has_a_small_provider_neutral_rank_effect() -> None:
    now = datetime.now(timezone.utc)
    query = DiscoveryQuery(text="embedded systems engineer", location="")
    fresh = DiscoveredJob(
        provider="brave-web",
        external_id="fresh",
        title="Embedded Engineer",
        company="Example Products",
        location="Berlin",
        summary="Develop embedded products.",
        source_url="https://careers.fresh.example/jobs/embedded",
        published_at=now - timedelta(days=7),
    )
    old = fresh.model_copy(
        update={
            "provider": "exa-fallback",
            "external_id": "old",
            "source_url": "https://careers.old.example/jobs/embedded",
            "published_at": now - timedelta(days=180),
        }
    )

    ranked = rank_discovered_jobs(query, [old, fresh])

    assert [job.external_id for job in ranked] == ["fresh", "old"]
    assert ranked[0].search_score == ranked[1].search_score + 6
