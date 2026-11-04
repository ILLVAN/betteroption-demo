from __future__ import annotations

from datetime import datetime, timezone

import httpx

from betteroption.company_intelligence import (
    CompanyIntelligenceService,
    CompanyResearchHit,
    ResearchPurpose,
    WikimediaCompanyResearchProvider,
)
from betteroption.discovery import (
    CompositeDiscoveryProvider,
    DiscoveredJob,
    DiscoveryQuery,
    SeniorityBand,
    discovery_query_from_profile,
)
from betteroption.job_context import EmployerContextService, EmployerKind
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.matching import MatchDisposition, match_job
from betteroption.mobility import (
    CommuteStatus,
    RoutePrecision,
    TransitousTravelTimeProvider,
    TravelQuery,
)
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelMode,
)


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text=value),
    )


def _job(*, company: str = "Boundary Dynamics", source_text: str = "Embedded software role."):
    return JobPosting(
        title="Embedded Software Engineer",
        company=company,
        location="Darmstadt",
        summary="Build embedded products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text=source_text,
    )


def test_same_city_transit_does_not_claim_a_fake_door_to_door_time() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/geocode"):
            return httpx.Response(
                200,
                request=request,
                json=[{"name": "Frankfurt (Main) Hbf", "lat": 50.107, "lon": 8.663}],
            )
        raise AssertionError("same-city city-level routing must stop before the plan call")

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Frankfurt am Main",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.NEEDS_PRECISE_LOCATION
    assert estimate.duration_minutes is None
    assert estimate.precision == RoutePrecision.CITY_TO_CITY
    assert "district, postcode, station, or street" in (estimate.message or "")


def test_city_pair_uses_a_validated_city_centre_benchmark() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/geocode"):
            is_frankfurt = "Frankfurt" in request.url.params["text"]
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "type": "PLACE",
                        "name": "Frankfurt am Main" if is_frankfurt else "Darmstadt",
                        "country": "DE",
                        "lat": 50.115 if is_frankfurt else 49.872,
                        "lon": 8.684 if is_frankfurt else 8.650,
                    }
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": [{"duration": 1_680}]},
        )

    estimate = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    ).estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Darmstadt",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.duration_minutes == 28
    assert estimate.precision == RoutePrecision.CITY_TO_CITY
    assert "Hauptbahnhof" not in calls[0].url.params["text"]
    assert "Bahnhof" not in calls[1].url.params["text"]
    assert any("not door-to-door" in attempt for attempt in estimate.attempts)


def test_wikimedia_company_summary_is_attributed_and_classifies_defence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Boundary Dynamics",
                            "extract": (
                                "Boundary Dynamics is a German defence technology company. "
                                "It develops military radar and electronic systems for armed forces."
                            ),
                            "fullurl": "https://en.wikipedia.org/wiki/Boundary_Dynamics",
                        }
                    ]
                }
            },
        )

    research = WikimediaCompanyResearchProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    intelligence = CompanyIntelligenceService(research).analyze(_job())

    assert "defence" in intelligence.product.sensitive_categories
    assert intelligence.product.evidence_urls == ["https://en.wikipedia.org/wiki/Boundary_Dynamics"]
    assert intelligence.product.confidence.value in {"medium", "high"}


class FixedCompanyResearch:
    def research(self, company: str) -> list[CompanyResearchHit]:
        assert company == "Agency People"
        return [
            CompanyResearchHit(
                title="Agency People profile",
                description=(
                    "Agency People is a temporary staffing company providing employee leasing "
                    "and recruitment services."
                ),
                url="https://example.org/agency-people",
                purpose=ResearchPurpose.BUSINESS,
            )
        ]


def test_researched_company_business_resolves_staffing_and_exclusion() -> None:
    job = _job(company="Agency People")
    context = EmployerContextService(
        research_homepages=False,
        company_research_provider=FixedCompanyResearch(),
    ).assess(job)
    profile = CandidateProfile(
        facts=[
            _fact(
                "employment.arrangement",
                "No temporary staffing or employee leasing",
                RequirementLevel.EXCLUSION,
            )
        ]
    )

    result = match_job(profile, job, context=context)

    assert context.employer.kind == EmployerKind.STAFFING_AGENCY
    assert context.employer.likely_direct_contract is False
    assert result.disposition == MatchDisposition.BLOCKED
    assert result.hard_violations == 1


class FixedDiscovery:
    name = "fixed"
    attribution = "Fixed jobs"
    attribution_url = "https://example.org/jobs"

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        titles = [
            "Junior Embedded Software Engineer",
            "Embedded Software Engineer",
            "Senior Embedded Software Engineer",
            "Lead Embedded Architect",
            "Engineering Manager Embedded Systems",
        ]
        return [
            DiscoveredJob(
                provider=self.name,
                external_id=str(index),
                title=title,
                company="Calm Systems",
                location="Frankfurt am Main",
                summary="Embedded firmware development with C++.",
                source_url=f"https://example.org/jobs/{index}",
            )
            for index, title in enumerate(titles)
        ]


def test_compass_search_prioritizes_level_and_limits_explicit_seniority_conflicts() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("role.family", "Embedded software", RequirementLevel.PREFERENCE),
            _fact("seniority.target", "Junior or entry level", RequirementLevel.PREFERENCE),
            _fact("location.origin", "Frankfurt", RequirementLevel.OPEN),
            _fact("industry.excluded", "Military defence", RequirementLevel.EXCLUSION),
        ]
    )
    query = discovery_query_from_profile(profile)
    results = CompositeDiscoveryProvider([FixedDiscovery()]).search(query)

    assert query.seniority_targets == [SeniorityBand.JUNIOR]
    assert query.excluded_terms == ["Military defence"]
    assert results[0].title == "Junior Embedded Software Engineer"
    assert results[0].seniority_relevance == 100
    assert sum(result.seniority_conflict for result in results) <= 2
    first_conflict = next(
        index for index, result in enumerate(results) if result.seniority_conflict
    )
    assert all(not result.seniority_conflict for result in results[:first_conflict]), (
        "explicit senior/lead roles must not crowd junior Compass results"
    )
