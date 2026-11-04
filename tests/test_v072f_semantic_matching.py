from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.match_evidence import (
    SemanticFitOutcome,
    SemanticMatchAssessment,
    job_fact_fingerprint,
)
from betteroption.matching import MatchDisposition, MatchOutcome, match_job, match_jobs
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.providers.openai_match_evidence import (
    OpenAIMatchEvidenceResolver,
    SemanticAssessmentDraft,
    SemanticAssessmentOutput,
)
from betteroption.settings import Settings


NOW = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)


def _criterion(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.MUST_HAVES, text=value),
    )


def _job(*facts: JobFact) -> JobPosting:
    source = "Embedded software. The work is performed on-site in a busy open-plan office."
    return JobPosting(
        title="Embedded Engineer",
        company="Example",
        location="Frankfurt",
        summary=source,
        source_type=JobSourceType.SAMPLE,
        source_name="semantic matching test",
        source_text=source,
        observed_at=NOW,
        facts=list(facts),
    )


def _context(*work_facts: JobFact) -> JobContext:
    return JobContext(
        employer=EmployerAssessment(
            kind=EmployerKind.UNKNOWN,
            confidence=ContextConfidence.LOW,
            explanation="The employer relationship is not established.",
        ),
        work_mode_facts=list(work_facts),
    )


def _assessment(
    job: JobPosting,
    criterion: ProfileFact,
    evidence: JobFact,
    *,
    outcome: SemanticFitOutcome = SemanticFitOutcome.VIOLATED,
    confidence: ContextConfidence = ContextConfidence.MEDIUM,
) -> SemanticMatchAssessment:
    return SemanticMatchAssessment(
        job_id=job.id,
        profile_fact_id=criterion.id,
        outcome=outcome,
        confidence=confidence,
        evidence_job_fact_ids=[evidence.id],
        evidence_fact_fingerprints={evidence.id: job_fact_fingerprint(evidence)},
        explanation="The public job fact conflicts with the confirmed boundary.",
    )


def test_medium_cross_key_office_contradiction_blocks_one_must_have() -> None:
    criterion = _criterion(
        "work_model.office_days_max",
        "At most 2 days per week in the office",
        RequirementLevel.MUST_HAVE,
    )
    onsite = JobFact(
        key="work_model.onsite",
        value="on-site",
        kind=JobFactKind.CONTEXT,
        evidence_quote="performed on-site",
    )
    job = _job()

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        context=_context(onsite),
        semantic_assessments=[_assessment(job, criterion, onsite)],
        evaluated_at=NOW,
    )

    reason = next(item for item in result.reasons if item.profile_fact_id == criterion.id)
    assert reason.outcome == MatchOutcome.VIOLATED
    assert reason.reasoning_confidence == ContextConfidence.MEDIUM
    assert reason.ai_assisted
    assert result.hard_violations == 1
    assert result.disposition == MatchDisposition.BLOCKED
    assert result.semantic_assessments


def test_generic_cross_key_contradiction_is_not_work_mode_hardcoded() -> None:
    criterion = _criterion(
        "culture.focus_environment",
        "Quiet individual focus",
        RequirementLevel.MUST_HAVE,
    )
    culture = JobFact(
        key="culture.signal",
        value="constant collaboration in a busy open-plan office",
        kind=JobFactKind.CONTEXT,
        evidence_quote="busy open-plan office",
    )
    job = _job(culture)

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        semantic_assessments=[_assessment(job, criterion, culture)],
        evaluated_at=NOW,
    )

    assert result.reasons[0].outcome == MatchOutcome.VIOLATED
    assert result.disposition == MatchDisposition.BLOCKED


def test_low_confidence_contradiction_remains_unknown_and_cannot_block() -> None:
    criterion = _criterion("culture.focus", "Quiet focus", RequirementLevel.MUST_HAVE)
    culture = JobFact(
        key="culture.signal",
        value="collaborative",
        kind=JobFactKind.CONTEXT,
        evidence_quote="busy open-plan office",
    )
    job = _job(culture)

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        semantic_assessments=[
            _assessment(
                job,
                criterion,
                culture,
                confidence=ContextConfidence.LOW,
            )
        ],
        evaluated_at=NOW,
    )

    assert result.reasons[0].outcome == MatchOutcome.UNKNOWN
    assert result.hard_violations == 0
    assert result.disposition != MatchDisposition.BLOCKED


def test_deterministic_result_wins_over_conflicting_semantic_output() -> None:
    criterion = _criterion("skill.name", "Python", RequirementLevel.MUST_HAVE)
    python = JobFact(
        key="skill.name",
        value="Python",
        kind=JobFactKind.REQUIREMENT,
        evidence_quote="Embedded software",
    )
    job = _job(python)

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        semantic_assessments=[_assessment(job, criterion, python)],
        evaluated_at=NOW,
    )

    assert result.reasons[0].outcome == MatchOutcome.SATISFIED
    assert not result.reasons[0].ai_assisted
    assert result.disposition != MatchDisposition.BLOCKED


def test_matching_normalizes_restored_semantic_outcome_to_criterion_level() -> None:
    criterion = _criterion("culture.focus", "Quiet focus", RequirementLevel.PREFERENCE)
    hard_criterion = _criterion(
        "environment.focus_requirement",
        "Quiet focus",
        RequirementLevel.MUST_HAVE,
    )
    culture = JobFact(
        key="culture.signal",
        value="quiet focus time",
        kind=JobFactKind.CONTEXT,
        evidence_quote="busy open-plan office",
    )
    job = _job(culture)

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        semantic_assessments=[
            _assessment(
                job,
                criterion,
                culture,
                outcome=SemanticFitOutcome.SATISFIED,
            )
        ],
        evaluated_at=NOW,
    )

    assert result.reasons[0].outcome == MatchOutcome.SUPPORTING

    hard_result = match_job(
        CandidateProfile(facts=[hard_criterion]),
        job,
        semantic_assessments=[
            _assessment(
                job,
                hard_criterion,
                culture,
                outcome=SemanticFitOutcome.SUPPORTING,
            )
        ],
        evaluated_at=NOW,
    )
    assert hard_result.reasons[0].outcome == MatchOutcome.SATISFIED


def test_changed_evidence_invalidates_stored_semantic_assessment_locally() -> None:
    criterion = _criterion(
        "work_model.office_days_max",
        "At most 2 office days",
        RequirementLevel.MUST_HAVE,
    )
    original = JobFact(
        key="work_model.onsite",
        value="on-site",
        kind=JobFactKind.CONTEXT,
        evidence_quote="performed on-site",
    )
    corrected = original.model_copy(update={"value": "hybrid, 2 office days"})
    job = _job()

    result = match_job(
        CandidateProfile(facts=[criterion]),
        job,
        context=_context(corrected),
        semantic_assessments=[_assessment(job, criterion, original)],
        evaluated_at=NOW,
    )

    assert result.reasons[0].outcome == MatchOutcome.UNKNOWN
    assert not result.reasons[0].ai_assisted
    assert result.disposition != MatchDisposition.BLOCKED


class _CapturingResolver:
    model = "test"

    def __init__(self, evidence: JobFact) -> None:
        self.evidence = evidence
        self.criteria_by_job_id: dict[UUID, list[ProfileFact]] = {}

    def assess(self, *, profile_facts_by_job_id, jobs):
        self.criteria_by_job_id = profile_facts_by_job_id
        job = jobs[0]
        criterion = profile_facts_by_job_id[job.id][0]
        return {job.id: [_assessment(job, criterion, self.evidence)]}


def test_resolver_receives_only_deterministically_unresolved_pairs() -> None:
    role = _criterion("role.family", "embedded software", RequirementLevel.PREFERENCE)
    office = _criterion(
        "work_model.office_days_max",
        "At most 2 office days",
        RequirementLevel.MUST_HAVE,
    )
    role_fact = JobFact(
        key="role.family",
        value="embedded software",
        kind=JobFactKind.CONTEXT,
        evidence_quote="Embedded software",
    )
    onsite = JobFact(
        key="work_model.onsite",
        value="on-site",
        kind=JobFactKind.CONTEXT,
        evidence_quote="performed on-site",
    )
    job = _job(role_fact)
    resolver = _CapturingResolver(onsite)

    run = match_jobs(
        CandidateProfile(facts=[role, office]),
        [job],
        contexts_by_job_id={job.id: _context(onsite)},
        match_evidence_resolver=resolver,
        evaluated_at=NOW,
    )

    assert [fact.id for fact in resolver.criteria_by_job_id[job.id]] == [office.id]
    assert run.results[0].disposition == MatchDisposition.BLOCKED


class _FakeResponses:
    def __init__(self, parsed: SemanticAssessmentOutput) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed, usage=None)


def test_openai_relation_prompt_is_minimized_and_validates_references() -> None:
    criterion = _criterion("culture.focus", "Quiet focus", RequirementLevel.MUST_HAVE)
    culture = JobFact(
        key="culture.signal",
        value="busy open-plan office",
        kind=JobFactKind.CONTEXT,
        evidence_quote="busy open-plan office",
    )
    precise_location = JobFact(
        key="location.address",
        value="Private-looking workplace address",
        kind=JobFactKind.CONTEXT,
        evidence_quote="performed on-site",
    )
    job = _job(culture, precise_location)
    responses = _FakeResponses(
        SemanticAssessmentOutput(
            assessments=[
                SemanticAssessmentDraft(
                    job_id=job.id,
                    profile_fact_id=criterion.id,
                    outcome=SemanticFitOutcome.VIOLATED,
                    confidence="medium",
                    evidence_job_fact_ids=[culture.id],
                    explanation="The explicit environment conflicts with quiet focus.",
                )
            ]
        )
    )
    resolver = OpenAIMatchEvidenceResolver(client=SimpleNamespace(responses=responses))

    assessed = resolver.assess(
        profile_facts_by_job_id={job.id: [criterion]},
        jobs=[job],
    )

    prompt = str(responses.calls[0]["input"])
    assert "unresolved_criteria" in prompt
    assert "busy open-plan office" in prompt
    assert "location.address" not in prompt
    assert "Private-looking workplace address" not in prompt
    assert job.source_text not in prompt
    assert "account" not in prompt.casefold()
    assert assessed[job.id][0].confidence == ContextConfidence.MEDIUM


def test_match_evidence_limit_is_bounded_and_routed() -> None:
    settings = Settings(match_evidence_max_jobs=25)
    route = settings.model_policy().route("match_explanation")

    assert settings.match_evidence_max_jobs == 25
    assert route.prompt_version == "match-evidence-v0.7.2i"


def test_raw_work_mode_observation_is_neutral_and_ai_reason_is_labelled() -> None:
    template = Path("src/betteroption/web/templates/job_detail.html").read_text(encoding="utf-8")
    work_mode_tile = template.split(
        "{% if item.stored.result.derived_work_mode_facts %}",
        1,
    )[1].split("{% if item.why_still_apply %}", 1)[0]

    assert "evidence-comparison unknown" in work_mode_tile
    assert "evidence-comparison supporting" not in work_mode_tile
    assert "Source-backed observation · compared with your Compass below" in work_mode_tile
    assert "AI-assisted" in template
