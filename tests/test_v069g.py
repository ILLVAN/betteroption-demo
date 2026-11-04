from __future__ import annotations

from datetime import datetime, timezone

from betteroption.company_intelligence import (
    CompanyIntelligenceService,
    CompanyResearchHit,
    ResearchPurpose,
)
from betteroption.job_context import EmployerContextService, EmployerKind
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchOutcome, match_job
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text=value),
    )


def _sample_job(
    *,
    title: str = "Testing Engineer / QA (m/w/d)",
    source_text: str = "Develop and test firmware for connected energy systems.",
) -> JobPosting:
    return JobPosting(
        title=title,
        company="Calm Energy",
        location="Alzenau",
        summary="Develop and test connected energy systems.",
        source_type=JobSourceType.SAMPLE,
        source_name="test fixture",
        source_text=source_text,
    )


def _live_job(source_text: str) -> JobPosting:
    return JobPosting(
        title="Graduate Test Engineer",
        company="Calm Energy",
        location="Alzenau",
        summary="Test connected energy products.",
        source_type=JobSourceType.URL_TEXT,
        source_name="Personio",
        source_url="https://calm-energy.jobs.personio.de/job/123",
        requested_url="https://calm-energy.jobs.personio.de/job/123",
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source_text,
    )


def test_operational_building_monitoring_is_not_human_surveillance() -> None:
    job = _sample_job()
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text=(
            "We optimize heating systems and provide operational monitoring of energy centres "
            "and building-management equipment."
        ),
        homepage_url="https://calm-energy.example/products",
    )

    assert "surveillance" not in intelligence.product.sensitive_categories
    assert "energy" in intelligence.product.categories


def test_video_surveillance_remains_a_traceable_sensitive_category() -> None:
    job = _sample_job()
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text="We develop video surveillance and facial recognition products.",
        homepage_url="https://vision.example/products",
    )

    assert "surveillance" in intelligence.product.sensitive_categories
    assert intelligence.product.evidence_urls == ["https://vision.example/products"]


class ProductCompanyResearch:
    def research(self, company: str) -> list[CompanyResearchHit]:
        assert company == "Calm Energy"
        return [
            CompanyResearchHit(
                title="Calm Energy products",
                description=(
                    "Calm Energy develops software products for heating optimisation and "
                    "energy management in commercial buildings."
                ),
                url="https://calm-energy.example/products",
                purpose=ResearchPurpose.BUSINESS,
            )
        ]


def test_attributed_operating_company_evidence_supports_likely_direct_employment() -> None:
    job = _live_job(
        "Calm Energy is looking for a Graduate Test Engineer to test our energy software products."
    )
    context = EmployerContextService(
        research_homepages=False,
        company_research_provider=ProductCompanyResearch(),
    ).assess(job)
    profile = CandidateProfile(
        facts=[
            _fact(
                "employment.arrangement",
                "direct contract with the employer",
                RequirementLevel.MUST_HAVE,
            )
        ]
    )

    result = match_job(profile, job, context=context)

    assert context.employer.kind == EmployerKind.DIRECT_EMPLOYER
    assert context.employer.likely_direct_contract is True
    assert "https://calm-energy.example/products" in context.employer.evidence_urls
    assert result.reasons[0].outcome == MatchOutcome.SATISFIED


def test_plain_individual_contributor_role_is_cautiously_junior_compatible() -> None:
    job = _sample_job(
        source_text=(
            "You will test embedded firmware, write automated tests, and collaborate with the "
            "development team. A technical degree is welcome."
        )
    )
    profile = CandidateProfile(
        facts=[_fact("seniority.target", "junior", RequirementLevel.MUST_HAVE)]
    )

    result = match_job(profile, job)
    reason = result.reasons[0]

    assert reason.outcome == MatchOutcome.SATISFIED
    assert reason.reasoning_confidence.value == "medium"
    assert "individual-contributor" in reason.explanation


def test_explicit_senior_scope_conflicts_with_a_junior_boundary() -> None:
    job = _sample_job(
        title="Senior Testing Engineer",
        source_text="Senior Testing Engineer with at least 6 years of experience.",
    )
    profile = CandidateProfile(
        facts=[_fact("seniority.target", "junior", RequirementLevel.MUST_HAVE)]
    )

    reason = match_job(profile, job).reasons[0]

    assert reason.outcome == MatchOutcome.VIOLATED
    assert "senior" in reason.explanation


def test_graduate_signal_supports_a_junior_target() -> None:
    job = _sample_job(
        title="Embedded Solutions Engineering Graduate",
        source_text="Our graduate programme starts with structured technical onboarding.",
    )
    profile = CandidateProfile(
        facts=[_fact("seniority.target", "junior", RequirementLevel.MUST_HAVE)]
    )

    reason = match_job(profile, job).reasons[0]

    assert reason.outcome == MatchOutcome.SATISFIED
    assert reason.reasoning_confidence.value == "high"
