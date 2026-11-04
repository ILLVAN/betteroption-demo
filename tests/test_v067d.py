from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from betteroption.company_intelligence import (
    CompanyIntelligenceService,
    CompanyResearchHit,
)
from betteroption.discovery import DiscoveredJob, DiscoveryQuery, rank_discovered_jobs
from betteroption.geography import OfflinePlaceIndex
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.matching import MatchOutcome, match_job
from betteroption.mobility import GoogleRoutesTravelTimeProvider, TravelQuery, _next_peak_departure
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


class FixedEmployerResearch:
    def employer_signals(self, company: str) -> list[CompanyResearchHit]:
        assert company == "Calm Systems"
        return [
            CompanyResearchHit(
                title="Calm Systems certified employer",
                description="An independent employer certification profile.",
                url="https://www.greatplacetowork.de/workplace/item/123",
            )
        ]


def _job(*, company: str = "Calm Systems") -> JobPosting:
    return JobPosting(
        title="Embedded Software Engineer",
        company=company,
        location="Seligenstadt, Germany",
        summary="Develop controls for engineered products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text="Develop controls for engineered products and production systems.",
    )


def test_explore_rank_is_seventy_percent_distance_and_thirty_percent_keywords() -> None:
    jobs = [
        DiscoveredJob(
            provider="test",
            external_id="berlin",
            title="Embedded Software Engineer",
            company="Far Systems",
            location="Berlin, Germany",
            source_url="https://far.example/jobs/1",
        ),
        DiscoveredJob(
            provider="test",
            external_id="seligenstadt",
            title="Embedded Software Engineer",
            company="Near Systems",
            location="Seligenstadt, Germany",
            source_url="https://near.example/jobs/1",
        ),
    ]

    ranked = rank_discovered_jobs(
        DiscoveryQuery(text="embedded software", location="Frankfurt am Main"),
        jobs,
        place_index=OfflinePlaceIndex(),
    )

    assert [job.external_id for job in ranked] == ["seligenstadt", "berlin"]
    assert ranked[0].distance_km is not None and ranked[0].distance_km < 30
    assert ranked[0].keyword_relevance >= 90
    assert ranked[0].search_score is not None
    assert ranked[0].search_score > ranked[1].search_score


def test_standard_commute_departure_is_tuesday_0800_and_skips_a_holiday() -> None:
    # German Unity Day falls on Tuesday in 2028, so the comparison moves one week.
    now = datetime(2028, 9, 30, 10, 0, tzinfo=timezone.utc)

    departure = _next_peak_departure(now)

    assert departure.isoformat() == "2028-10-10T08:00:00+02:00"
    assert departure.weekday() == 1


def test_google_routes_selects_the_shortest_returned_alternative() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "routes": [
                    {"duration": "2700s", "distanceMeters": 30_000},
                    {"duration": "2100s", "distanceMeters": 32_000},
                ]
            },
        )

    estimate = GoogleRoutesTravelTimeProvider(
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Darmstadt",
            mode=TravelMode.TRANSIT,
            departure_at=datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
        )
    )

    assert captured["computeAlternativeRoutes"] is True
    assert estimate.duration_minutes == 35
    assert estimate.distance_km == 32.0
    assert "2 valid route option" in estimate.attempts[0]


def test_company_profile_and_reputation_stay_source_attributed() -> None:
    intelligence = CompanyIntelligenceService(FixedEmployerResearch()).analyze(
        _job(),
        homepage_text=(
            "We manufacture automation systems. Our Kununu score is 4.2 from 123 Bewertungen."
        ),
        homepage_url="https://calm.example/",
    )

    assert intelligence.product.revenue_model.startswith("engineered products")
    assert intelligence.product.evidence_urls == ["https://calm.example/"]
    assert intelligence.reputation.kununu_score is None
    assert intelligence.reputation.kununu_review_count is None
    assert intelligence.reputation.review_links[0].label == "Find this employer on Kununu"
    assert intelligence.reputation.signals[0].source_url.startswith(
        "https://www.greatplacetowork.de/"
    )
    assert "does not collect employee-review platforms" in intelligence.reputation.caveat


def test_company_product_evidence_can_enforce_a_defence_exclusion() -> None:
    job = _job(company="Boundary Systems")
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text="We design defence systems for military customers.",
        homepage_url="https://boundary.example/",
    )
    profile = CandidateProfile(
        facts=[
            ProfileFact(
                key="industry.excluded",
                value="No military or defence work",
                level=RequirementLevel.EXCLUSION,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.EXCLUSIONS,
                    text="No military or defence work",
                ),
            )
        ]
    )
    context = JobContext(
        employer=EmployerAssessment(
            kind=EmployerKind.DIRECT_EMPLOYER,
            confidence=ContextConfidence.MEDIUM,
            likely_direct_contract=True,
            explanation="Employer-controlled source.",
        ),
        company_intelligence=intelligence,
    )

    result = match_job(profile, job, context=context)

    assert result.hard_violations == 1
    assert result.disposition.value == "blocked"
    assert result.reasons[0].outcome == MatchOutcome.VIOLATED
    assert "defence" in result.reasons[0].explanation
    assert result.reasons[0].evidence_urls == ["https://boundary.example/"]
