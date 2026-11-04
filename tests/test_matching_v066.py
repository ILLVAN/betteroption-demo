from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import MatchDisposition, match_job
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)


def preference(key: str, value: str) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.PREFERENCES, text=value),
    )


def test_unmentioned_preferences_do_not_make_a_relevant_job_look_bad() -> None:
    profile = CandidateProfile(
        facts=[
            preference("role.family", "embedded software"),
            *[
                preference(f"culture.preference_{index}", f"preference {index}")
                for index in range(12)
            ],
        ]
    )
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Example",
        location="Frankfurt",
        summary="Build embedded software.",
        source_type=JobSourceType.SAMPLE,
        source_name="v0.6.6 scoring test",
        source_text="Embedded software development.",
        facts=[
            JobFact(
                key="role.family",
                value="embedded software",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Embedded software",
            )
        ],
    )

    result = match_job(profile, job)

    assert result.score >= 60
    assert result.disposition == MatchDisposition.TOP
    assert len(result.reasons) == 1


def test_no_supporting_evidence_stays_neutral_instead_of_claiming_a_top_match() -> None:
    profile = CandidateProfile(facts=[preference("role.family", "embedded software")])
    job = JobPosting(
        title="Account Executive",
        company="Example",
        location="Remote",
        summary="Sell enterprise software.",
        source_type=JobSourceType.SAMPLE,
        source_name="v0.6.6 scoring test",
        source_text="Enterprise sales role.",
        facts=[],
    )

    result = match_job(profile, job)

    assert result.score == 40
    assert result.disposition == MatchDisposition.STRETCH
