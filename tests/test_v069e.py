from __future__ import annotations

import httpx

from betteroption.discovery import (
    BraveWebDiscoveryProvider,
    DiscoveredJob,
    DiscoveryQuery,
    _regional_search_locations,
    _web_search_texts,
)
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.geography import OfflinePlaceIndex
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.matching import match_job
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)


def _discovery_job(
    identity: str,
    *,
    location: str,
    remote: bool = False,
    provider: str = "test",
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        external_id=identity,
        title="Test Automation Engineer",
        company=f"Company {identity}",
        location=location,
        remote=remote,
        summary="Build automated software tests.",
        source_url=f"https://{identity}.example/jobs/test-automation",
    )


class StaticProvider:
    name = "static"
    attribution = "Static fixture"
    attribution_url = "https://example.com/source"

    def __init__(self, jobs: list[DiscoveredJob]) -> None:
        self.jobs = jobs
        self.calls = 0

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.calls += 1
        return self.jobs


def _profile_fact(key: str, value: str, section: ProfileSection) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=RequirementLevel.OPEN,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def test_compass_web_search_branches_across_offline_nearby_cities() -> None:
    query = DiscoveryQuery(
        text="test automation · embedded software",
        location="60486",
        desired_terms=["test automation", "embedded software"],
        regional_target=30,
    )

    locations = _regional_search_locations(query)
    searches = _web_search_texts(query)

    assert locations[0] == "Frankfurt am Main"
    assert len(locations) >= 5
    assert len(searches) == 10
    assert any("Frankfurt am Main" in search for search in searches)
    assert (
        len({location for location in locations[:6] if any(location in q for q in searches)}) >= 5
    )


def test_district_detail_recovers_its_explicit_city_without_a_place_specific_rule() -> None:
    resolved = OfflinePlaceIndex().resolve("Frankfurt Bockenheim")

    assert resolved is not None
    assert resolved.label == "Frankfurt am Main"


def test_brave_recovers_an_explicit_regional_location_without_assuming_query_location() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.params.get("q")))
        return httpx.Response(
            200,
            request=request,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Test Automation Engineer – Darmstadt",
                            "url": "https://careers.warm.example/jobs/test-automation",
                            "description": "Join our engineering team in Darmstadt with hybrid flexibility.",
                            "profile": {"long_name": "Warm Engineering"},
                        }
                    ]
                }
            },
        )

    provider = BraveWebDiscoveryProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="test automation",
            location="60486",
            desired_terms=["test automation"],
        )
    )

    assert len(calls) >= 5
    assert len(jobs) == 1
    assert jobs[0].location == "Darmstadt"
    assert jobs[0].remote is False


def test_exa_fallback_uses_regional_coverage_instead_of_total_result_count() -> None:
    primary = StaticProvider(
        [_discovery_job(f"remote-{index}", location="Remote", remote=True) for index in range(30)]
    )
    fallback = StaticProvider(
        [
            _discovery_job("local-1", location="Darmstadt", provider="fallback"),
            _discovery_job("local-2", location="Offenbach", provider="fallback"),
        ]
    )
    mesh = DiscoverySourceMesh(
        [primary],
        fallback_providers=[fallback],
        fallback_min_results=10,
    )

    results = mesh.search(
        DiscoveryQuery(
            text="test automation",
            location="60486",
            regional_target=2,
        )
    )

    assert fallback.calls == 1
    assert mesh.last_fallback_used is True
    assert [job.external_id for job in results[:2]] == ["local-2", "local-1"]


def test_fluent_combined_language_evidence_satisfies_separate_job_languages() -> None:
    profile = CandidateProfile(
        facts=[
            _profile_fact(
                "language.spoken",
                "German and English fluent",
                ProfileSection.PREFERENCES,
            )
        ]
    )
    job = JobPosting(
        title="Test Automation Engineer",
        company="Example",
        location="Frankfurt",
        summary="Automate tests.",
        source_type=JobSourceType.SAMPLE,
        source_name="fixture",
        source_text="Fluent German and English, spoken and written, are required.",
    )

    result = match_job(profile, job)

    assert set(result.matched_required_skills) == {"German (fluent)", "English (fluent)"}
    assert result.missing_required_skills == []


def test_desired_language_is_not_silently_treated_as_candidate_capability() -> None:
    profile = CandidateProfile(
        facts=[
            _profile_fact(
                "language.desired",
                "English-speaking workplace",
                ProfileSection.PREFERENCES,
            )
        ]
    )
    job = JobPosting(
        title="Test Automation Engineer",
        company="Example",
        location="Frankfurt",
        summary="Automate tests.",
        source_type=JobSourceType.SAMPLE,
        source_name="fixture",
        source_text="Fluent English is required.",
    )

    result = match_job(profile, job)

    assert result.matched_required_skills == []
    assert result.missing_required_skills == ["English (fluent)"]
