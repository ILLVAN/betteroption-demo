from __future__ import annotations

from betteroption.company_intelligence import CompanyIntelligenceService
from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryQuery,
    discovery_query_from_profile,
    finalize_discovered_jobs,
)
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerContextService,
    EmployerKind,
    JobContext,
)
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


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text=value),
    )


def _job(*, location: str = "Darmstadt, Germany", remote: bool = False) -> DiscoveredJob:
    return DiscoveredJob(
        provider="test",
        external_id=f"job-{location}-{remote}",
        title="Embedded Software Engineer",
        company="Example Systems",
        location=location,
        remote=remote,
        summary="Develop embedded software and automated tests.",
        source_url=f"https://example.com/jobs/{'remote' if remote else 'onsite'}",
    )


def test_explore_resolves_a_german_postcode_before_ranking_distance() -> None:
    jobs = finalize_discovered_jobs(
        DiscoveryQuery(text="embedded software", location="60486"),
        [_job()],
    )

    assert jobs[0].distance_km is not None
    assert 15 < jobs[0].distance_km < 40
    assert jobs[0].distance_relevance is not None


def test_compass_work_arrangement_replaces_the_one_way_remote_checkbox() -> None:
    remote_profile = CandidateProfile(
        facts=[
            _fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            _fact("work_model.remote", "fully remote", RequirementLevel.PREFERENCE),
        ]
    )
    onsite_profile = CandidateProfile(
        facts=[
            _fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            _fact("work_model.onsite", "on-site", RequirementLevel.PREFERENCE),
        ]
    )
    hybrid_profile = CandidateProfile(
        facts=[
            _fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            _fact("work_model.hybrid", "hybrid", RequirementLevel.PREFERENCE),
        ]
    )

    remote_query = discovery_query_from_profile(remote_profile)
    onsite_query = discovery_query_from_profile(onsite_profile)
    hybrid_query = discovery_query_from_profile(hybrid_profile)

    assert remote_query.remote_preferred and not remote_query.remote_only
    assert not onsite_query.remote_only and not onsite_query.onsite_only
    assert not hybrid_query.remote_only and not hybrid_query.onsite_only
    assert [
        job.remote for job in finalize_discovered_jobs(remote_query, [_job(), _job(remote=True)])
    ][0] is True
    assert len(finalize_discovered_jobs(onsite_query, [_job(), _job(remote=True)])) == 2


def test_origin_postcode_is_context_for_routing_not_a_job_ad_requirement() -> None:
    origin = _fact("location.origin", "60486", RequirementLevel.MUST_HAVE)
    role = _fact("role.family", "embedded software", RequirementLevel.PREFERENCE)
    profile = CandidateProfile(facts=[origin, role])
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Example Systems",
        location="Darmstadt",
        summary="Develop embedded software.",
        source_type=JobSourceType.SAMPLE,
        source_name="test fixture",
        source_text="Develop embedded software.",
    )

    result = match_job(profile, job)

    assert all(reason.profile_fact_id != origin.id for reason in result.reasons)
    assert "60486" not in " ".join(reason.profile_value for reason in result.reasons)


def test_attributed_surveillance_evidence_can_enforce_an_explicit_exclusion() -> None:
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Vision Systems",
        location="Darmstadt",
        summary="Develop imaging software.",
        source_type=JobSourceType.SAMPLE,
        source_name="test fixture",
        source_text="Develop imaging software.",
    )
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text="We build facial recognition and video surveillance products.",
        homepage_url="https://vision.example/",
    )
    profile = CandidateProfile(
        facts=[
            _fact(
                "industry.excluded",
                "No surveillance products",
                RequirementLevel.EXCLUSION,
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
    assert result.reasons[0].evidence_urls == ["https://vision.example/"]


def test_employer_context_reuses_research_for_an_unchanged_job() -> None:
    class CountingResearch:
        def __init__(self) -> None:
            self.calls = 0

        def research(self, company: str):
            self.calls += 1
            return []

    research = CountingResearch()
    service = EmployerContextService(
        research_homepages=False,
        company_research_provider=research,
    )
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Example Systems",
        location="Darmstadt",
        summary="Develop embedded software.",
        source_type=JobSourceType.SAMPLE,
        source_name="test fixture",
        source_text="Develop embedded software.",
    )

    first = service.assess(job)
    second = service.assess(job)

    assert first == second
    assert research.calls == 1
