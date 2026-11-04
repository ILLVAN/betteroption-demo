from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from betteroption.company_intelligence import CompanyIntelligenceService
from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    BraveWebDiscoveryProvider,
    DiscoveredJob,
    DiscoveryQuery,
    _seniority_bands,
    web_discovery_source_is_excluded,
)
from betteroption.discovery_sources import ExaFallbackDiscoveryProvider
from betteroption.explore_repository import ExploreSearchRepository
from betteroption.job_context import (
    ContextConfidence,
    EmployerAssessment,
    EmployerKind,
    JobContext,
)
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import MatchOutcome, SeniorityLevel, match_job
from betteroption.mobility import (
    CommuteAssessment,
    CommuteStatus,
    MobilityService,
    TravelEstimate,
    routing_destinations_from_job,
)
from betteroption.presentation import commute_visual_state
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    ReferenceJob,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_workflow import (
    ProfileWorkflowError,
    ProfileWorkflowService,
    pending_reference_learning_ids,
    workspace_stage,
)
from betteroption.settings import Settings


NOW = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)


def _profile_fact(
    key: str,
    value: str,
    level: RequirementLevel,
    *,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def _job(
    *,
    title: str = "Automation Engineer",
    location: str = "Frankfurt am Main",
    source_text: str = "Build reliable automation products in an international team.",
    facts: list[JobFact] | None = None,
) -> JobPosting:
    return JobPosting(
        title=title,
        company="Example Products",
        location=location,
        summary=source_text,
        source_type=JobSourceType.SAMPLE,
        source_name="v0.7.1c quality regression",
        source_text=source_text,
        facts=facts or [],
    )


def test_absolventa_is_excluded_at_both_web_provider_boundaries() -> None:
    row = {
        "url": "https://www.absolventa.de/jobs/channel/ingenieure",
        "title": "Jobs für Ingenieure",
    }

    assert web_discovery_source_is_excluded(row["url"])
    assert web_discovery_source_is_excluded("https://jobs.absolventa.de/jobs?q=python")
    assert not web_discovery_source_is_excluded("https://absolventa.de.example.com/jobs/1")
    assert not BraveWebDiscoveryProvider._usable(BraveWebDiscoveryProvider, row)
    assert not ExaFallbackDiscoveryProvider._usable(row)


def test_persisted_explore_snapshots_hide_newly_excluded_sources() -> None:
    allowed = DiscoveredJob(
        provider="brave-web",
        external_id="allowed",
        title="Test Engineer",
        company="Example",
        source_url="https://careers.example.com/jobs/123",
        remote=True,
    )
    excluded = DiscoveredJob(
        provider="brave-web",
        external_id="excluded",
        title="Engineering jobs",
        company="Absolventa",
        source_url="https://absolventa.de/jobs/channel/engineering",
    )
    payload = json.dumps([allowed.model_dump(mode="json"), excluded.model_dump(mode="json")])

    restored = ExploreSearchRepository._results(payload)

    assert [job.external_id for job in restored] == ["allowed"]

    query = DiscoveryQuery(
        text="test engineer",
        location="Frankfurt am Main",
        regional_radius_km=150,
    )
    row = SimpleNamespace(
        task_id=str(uuid4()),
        workspace_id=str(uuid4()),
        query_json=query.model_dump_json(),
        query_text=query.text,
        location=query.location,
        work_arrangement=query.work_arrangement_label,
        compass_used=True,
        hide_remote_only=False,
        results_json=payload,
        regional_result_count=1,
        created_at=NOW,
        completed_at=NOW,
    )

    snapshot = ExploreSearchRepository._from_row(row)

    assert snapshot.regional_result_count == 0


def test_international_is_not_an_internship_marker_in_match_or_explore() -> None:
    profile = CandidateProfile(
        facts=[
            _profile_fact(
                "culture.signal",
                "international team",
                RequirementLevel.PREFERENCE,
                section=ProfileSection.ENVIRONMENT_CULTURE,
            ),
            _profile_fact("role.level", "internship", RequirementLevel.EXCLUSION),
        ]
    )
    job = _job(
        title="Software Engineer – International Team",
        facts=[
            JobFact(
                key="culture.signal",
                value="international team",
                kind=JobFactKind.OFFER,
                evidence_quote="international team",
            )
        ],
    )

    result = match_job(profile, job)

    internship = next(reason for reason in result.reasons if reason.profile_value == "internship")
    culture = next(
        reason for reason in result.reasons if reason.profile_value == "international team"
    )
    assert internship.outcome == MatchOutcome.SATISFIED
    assert culture.outcome == MatchOutcome.SUPPORTING
    assert "intern" not in culture.explanation.casefold()
    assert SeniorityLevel.INTERN.value not in {
        band.value for band in _seniority_bands(job.title, [])
    }


def test_real_internship_still_triggers_an_explicit_exclusion() -> None:
    profile = CandidateProfile(
        facts=[_profile_fact("role.level", "internship", RequirementLevel.EXCLUSION)]
    )

    result = match_job(
        profile,
        _job(
            title="Software Engineering Intern",
            source_text="A six-month internship in software test automation.",
        ),
    )

    assert result.reasons[0].outcome == MatchOutcome.VIOLATED


def test_building_monitoring_is_not_human_surveillance_or_military_evidence() -> None:
    text = (
        "Wir entwickeln Gebäudeüberwachungssysteme und Objektüberwachung für "
        "Heizungs- und Energieanlagen."
    )
    job = _job(source_text=text)
    intelligence = CompanyIntelligenceService().analyze(
        job,
        homepage_text=text,
        homepage_url="https://automation.example/products",
    )
    exclusion = _profile_fact(
        "industry.excluded",
        "No military or people-surveillance products",
        RequirementLevel.EXCLUSION,
        section=ProfileSection.EXCLUSIONS,
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

    result = match_job(CandidateProfile(facts=[exclusion]), job, context=context)

    assert "surveillance" not in intelligence.product.sensitive_categories
    assert not [reason for reason in result.reasons if reason.outcome == MatchOutcome.VIOLATED]


def test_explicit_human_surveillance_stays_sensitive_but_negated_claim_does_not() -> None:
    job = _job()
    explicit = CompanyIntelligenceService().analyze(
        job,
        homepage_text="Wir entwickeln Videoüberwachung, CCTV und Gesichtserkennung von Personen.",
        homepage_url="https://vision.example/products",
    )
    negated = CompanyIntelligenceService().analyze(
        job,
        homepage_text="Wir entwickeln keine Video- oder Personenüberwachung.",
        homepage_url="https://safe.example/products",
    )

    assert "surveillance" in explicit.product.sensitive_categories
    assert "surveillance" not in negated.product.sensitive_categories


@pytest.mark.parametrize(
    "text",
    [
        "We provide cyber defense software for industrial networks.",
        "We provide security monitoring for cloud networks.",
        "Building security monitoring and fire-alarm automation.",
    ],
)
def test_benign_security_language_is_not_military_or_human_surveillance(text: str) -> None:
    intelligence = CompanyIntelligenceService().analyze(
        _job(source_text=text),
        homepage_text=text,
        homepage_url="https://security.example/products",
    )

    assert "defence" not in intelligence.product.sensitive_categories
    assert "surveillance" not in intelligence.product.sensitive_categories


def test_sensitive_compounds_and_clause_local_negation_are_classified_precisely() -> None:
    surveillance = CompanyIntelligenceService().analyze(
        _job(),
        homepage_text="Wir entwickeln Videoüberwachungssysteme und Überwachungskameras.",
        homepage_url="https://vision.example/products",
    )
    defence = CompanyIntelligenceService().analyze(
        _job(),
        homepage_text=(
            "We do not outsource development, and we build military radar for armed forces."
        ),
        homepage_url="https://defence.example/products",
    )

    assert "surveillance" in surveillance.product.sensitive_categories
    assert "defence" in defence.product.sensitive_categories


def test_profile_sensitive_intent_distinguishes_security_from_military_and_surveillance() -> None:
    job = _job()
    military = CompanyIntelligenceService().analyze(
        job,
        homepage_text="We build military radar systems for armed forces.",
        homepage_url="https://military.example/products",
    )
    surveillance = CompanyIntelligenceService().analyze(
        job,
        homepage_text="We build video surveillance cameras and facial recognition products.",
        homepage_url="https://vision.example/products",
    )

    def result_for(value: str, intelligence):
        return match_job(
            CandidateProfile(
                facts=[
                    _profile_fact(
                        "industry.excluded",
                        value,
                        RequirementLevel.EXCLUSION,
                        section=ProfileSection.EXCLUSIONS,
                    )
                ]
            ),
            job,
            context=JobContext(
                employer=EmployerAssessment(
                    kind=EmployerKind.DIRECT_EMPLOYER,
                    confidence=ContextConfidence.MEDIUM,
                    likely_direct_contract=True,
                    explanation="Employer-controlled source.",
                ),
                company_intelligence=intelligence,
            ),
        )

    assert not any(
        reason.outcome == MatchOutcome.VIOLATED
        for reason in result_for("No cyber defense products", military).reasons
    )
    assert not any(
        reason.outcome == MatchOutcome.VIOLATED
        for reason in result_for("No building security monitoring", surveillance).reasons
    )
    assert any(
        reason.outcome == MatchOutcome.VIOLATED
        for reason in result_for("No military products", military).reasons
    )
    assert any(
        reason.outcome == MatchOutcome.VIOLATED
        for reason in result_for("No video surveillance products", surveillance).reasons
    )


def test_multi_location_routing_derives_every_physical_workplace_and_groups_precision() -> None:
    source = (
        "Work in Frankfurt am Main or Mülheim an der Ruhr. "
        "The Frankfurt office is at Example Street 12, 60311 Frankfurt am Main."
    )
    job = _job(
        location="Frankfurt am Main / Mülheim an der Ruhr / Remote",
        source_text=source,
        facts=[
            JobFact(
                key="location.address",
                value="Example Street 12, 60311 Frankfurt am Main",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Example Street 12, 60311 Frankfurt am Main",
            )
        ],
    )

    assert routing_destinations_from_job(job) == [
        "Example Street 12, 60311 Frankfurt am Main",
        "Mülheim an der Ruhr",
    ]


def test_multi_location_routing_keeps_distinct_precise_offices_in_one_city() -> None:
    first = "Example Street 12, 60311 Frankfurt"
    second = "Sample Road 9, 60549 Frankfurt"
    source = f"Work at {first} or {second}."
    job = _job(
        location="Frankfurt",
        source_text=source,
        facts=[
            JobFact(
                key="location.address",
                value=value,
                kind=JobFactKind.CONTEXT,
                evidence_quote=value,
            )
            for value in (first, second)
        ],
    )

    assert routing_destinations_from_job(job) == [first, second]


def test_location_splitting_does_not_break_frankfurt_an_der_oder() -> None:
    job = _job(location="Frankfurt an der Oder / Berlin")

    assert routing_destinations_from_job(job) == [
        "Frankfurt an der Oder",
        "Berlin",
    ]


class _NoCacheRepository:
    def get(self, *_args, **_kwargs):
        return None

    def save(self, *_args, **_kwargs):
        raise AssertionError("non-cacheable test estimates must not be persisted")


class _DestinationProvider:
    name = "destination-test"
    persistent_cache_allowed = False

    def __init__(
        self,
        outcomes: dict[str, int | CommuteStatus],
        *,
        message: str | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.message = message
        self.destinations: list[str] = []

    def estimate(self, query):
        self.destinations.append(query.destination)
        outcome = self.outcomes[query.destination]
        if isinstance(outcome, int):
            return TravelEstimate(
                status=CommuteStatus.AVAILABLE,
                provider=self.name,
                duration_minutes=outcome,
                cache_permitted=False,
                message=self.message,
            )
        return TravelEstimate(
            status=outcome,
            provider=self.name,
            cache_permitted=False,
            message=self.message,
        )


def _routing_profile(maximum_minutes: int = 60) -> CandidateProfile:
    return CandidateProfile(
        facts=[
            _profile_fact("location.origin", "Darmstadt", RequirementLevel.MUST_HAVE),
            _profile_fact(
                "commute.car.max_minutes",
                f"{maximum_minutes} minutes by car",
                RequirementLevel.MUST_HAVE,
                section=ProfileSection.LOCATION_MOBILITY,
            ),
        ]
    )


def test_multi_location_routing_selects_the_shortest_route_not_the_longest_label() -> None:
    provider = _DestinationProvider({"Frankfurt am Main": 30, "Mülheim an der Ruhr": 150})
    service = MobilityService(_NoCacheRepository(), provider)

    assessments = service.assess(
        CandidateProfile().id,
        _job().id,
        _routing_profile(),
        ["Mülheim an der Ruhr", "Frankfurt am Main"],
    )

    assert provider.destinations == ["Mülheim an der Ruhr", "Frankfurt am Main"]
    assert len(assessments) == 1
    assert assessments[0].destination == "Frankfurt am Main"
    assert assessments[0].estimate.duration_minutes == 30
    assert assessments[0].within_limit is True
    assert assessments[0].evaluated_destinations == [
        "Mülheim an der Ruhr",
        "Frankfurt am Main",
    ]


def test_unresolved_alternative_cannot_create_a_false_commute_blocker() -> None:
    provider = _DestinationProvider(
        {
            "Frankfurt am Main": 90,
            "Mülheim an der Ruhr": CommuteStatus.PROVIDER_ERROR,
        }
    )
    profile = _routing_profile()
    service = MobilityService(_NoCacheRepository(), provider)
    job = _job(location="Frankfurt am Main / Mülheim an der Ruhr")

    assessments = service.assess(
        profile.id,
        job.id,
        profile,
        routing_destinations_from_job(job),
    )
    result = match_job(profile, job, commutes=assessments)

    assert assessments[0].within_limit is None
    assert assessments[0].unresolved_destinations == ["Mülheim an der Ruhr"]
    assert result.hard_violations == 0
    assert all(reason.profile_key != "commute.car.max_minutes" for reason in result.reasons)
    assert commute_visual_state(assessments[0]) == "unavailable"


def test_all_known_routes_over_the_limit_remain_a_proven_conflict() -> None:
    provider = _DestinationProvider({"Frankfurt am Main": 90, "Mülheim an der Ruhr": 120})
    profile = _routing_profile()
    service = MobilityService(_NoCacheRepository(), provider)
    job = _job(location="Frankfurt am Main / Mülheim an der Ruhr")

    assessments = service.assess(
        profile.id,
        job.id,
        profile,
        routing_destinations_from_job(job),
    )
    result = match_job(profile, job, commutes=assessments)

    assert assessments[0].destination == "Frankfurt am Main"
    assert assessments[0].within_limit is False
    assert result.hard_violations == 1
    assert all(reason.profile_key != "commute.car.max_minutes" for reason in result.reasons)


def test_destination_overflow_keeps_an_over_limit_route_unknown() -> None:
    destinations = [f"Workplace {index}" for index in range(13)]
    provider = _DestinationProvider({destination: 90 for destination in destinations})
    profile = _routing_profile()
    service = MobilityService(_NoCacheRepository(), provider)

    assessment = service.assess(
        profile.id,
        _job().id,
        profile,
        destinations,
    )[0]

    assert provider.destinations == destinations[:12]
    assert assessment.omitted_destination_count == 1
    assert assessment.within_limit is None
    assert "12 of 13 advertised workplace locations" in (assessment.estimate.message or "")


def test_multi_location_message_stays_valid_for_persistence_roundtrip() -> None:
    destinations = ["Frankfurt am Main", "Mülheim an der Ruhr"]
    provider = _DestinationProvider(
        {destinations[0]: 30, destinations[1]: CommuteStatus.NO_ROUTE},
        message="x" * 1_000,
    )
    profile = _routing_profile()
    service = MobilityService(_NoCacheRepository(), provider)

    assessment = service.assess(
        profile.id,
        _job().id,
        profile,
        destinations,
    )[0]

    assert assessment.estimate.message is not None
    assert len(assessment.estimate.message) <= 1_000
    assert CommuteAssessment.model_validate_json(assessment.model_dump_json()) == assessment


def test_total_multi_location_failure_does_not_claim_a_best_route() -> None:
    destinations = ["Frankfurt am Main", "Mülheim an der Ruhr"]
    provider = _DestinationProvider(
        {destination: CommuteStatus.NO_ROUTE for destination in destinations}
    )
    profile = _routing_profile()
    service = MobilityService(_NoCacheRepository(), provider)

    assessment = service.assess(
        profile.id,
        _job().id,
        profile,
        destinations,
    )[0]

    message = assessment.estimate.message or ""
    assert "No available route was confirmed" in message
    assert "best" not in message.casefold()


def _reference_job() -> JobPosting:
    source = "Own technical delivery in a calm international team using Python."
    return _job(
        title="Test Automation Engineer",
        source_text=source,
        facts=[
            JobFact(
                key="role.responsibility",
                value="technical ownership",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Own technical delivery",
            ),
            JobFact(
                key="culture.signal",
                value="calm international team",
                kind=JobFactKind.OFFER,
                evidence_quote="calm international team",
            ),
        ],
    )


def _workflow(tmp_path: Path) -> tuple[ProfileWorkflowService, object]:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'reference-learning.db').as_posix()}",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )
    service = ProfileWorkflowService(container.workspaces)
    return service, service.start()


def test_reference_learning_is_immediately_reviewable_but_not_active(tmp_path: Path) -> None:
    service, workspace = _workflow(tmp_path)

    saved = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/123",
        resolved_url="https://careers.example.com/jobs/123",
        http_status=200,
        verified_at=NOW,
        positives=["Technical ownership", "Calm international team"],
        negatives=["Rigid hierarchy"],
        learning_enabled=True,
        learning_scope=["role", "culture"],
        job=_reference_job(),
    )

    pending_ids = pending_reference_learning_ids(saved.session.profile)
    pending = [fact for fact in saved.session.profile.facts if fact.id in pending_ids]
    assert workspace_stage(saved) == "review"
    assert {str(fact.value) for fact in pending} == {
        "Technical ownership",
        "Calm international team",
    }
    assert all(fact.evidence_status == EvidenceStatus.INFERRED for fact in pending)
    assert all(fact.source_reference_ids for fact in pending)
    assert not saved.session.profile.confirmed_facts
    assert saved.session.profile.reference_jobs[0].negatives == ["Rigid hierarchy"]


def test_reference_learning_is_idempotent_and_deletion_keeps_confirmed_learning(
    tmp_path: Path,
) -> None:
    service, workspace = _workflow(tmp_path)
    arguments = {
        "requested_url": "https://careers.example.com/jobs/123",
        "resolved_url": "https://careers.example.com/jobs/123",
        "http_status": 200,
        "verified_at": NOW,
        "positives": ["Technical ownership", "Calm international team"],
        "negatives": [],
        "learning_enabled": True,
        "learning_scope": ["role", "culture"],
        "job": _reference_job(),
    }
    first = service.upsert_verified_reference(workspace.id, **arguments)
    first_pending = pending_reference_learning_ids(first.session.profile)
    confirmed_id = first_pending[0]
    service.confirm_facts(workspace.id, [confirmed_id], continue_guided=False)

    repeated = service.upsert_verified_reference(workspace.id, **arguments)
    assert len(pending_reference_learning_ids(repeated.session.profile)) == 1
    assert any(fact.id == confirmed_id for fact in repeated.session.profile.confirmed_facts)

    reference_id = repeated.session.profile.reference_jobs[0].id
    deleted = service.delete_reference(workspace.id, reference_id)
    assert pending_reference_learning_ids(deleted.session.profile) == []
    assert any(fact.id == confirmed_id for fact in deleted.session.profile.confirmed_facts)


def test_reference_learning_off_creates_no_compass_proposals(tmp_path: Path) -> None:
    service, workspace = _workflow(tmp_path)

    saved = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/123",
        resolved_url="https://careers.example.com/jobs/123",
        http_status=200,
        verified_at=NOW,
        positives=["Technical ownership"],
        negatives=[],
        learning_enabled=False,
        learning_scope=[],
        job=_reference_job(),
    )

    assert pending_reference_learning_ids(saved.session.profile) == []


def test_reference_learning_requires_positive_note_scope_and_verified_job_evidence(
    tmp_path: Path,
) -> None:
    service, workspace = _workflow(tmp_path)
    common = {
        "workspace_id": workspace.id,
        "requested_url": "https://careers.example.com/jobs/validation",
        "resolved_url": "https://careers.example.com/jobs/validation",
        "http_status": 200,
        "verified_at": NOW,
        "negatives": ["Rigid hierarchy"],
        "learning_enabled": True,
    }

    with pytest.raises(ProfileWorkflowError, match="positive note"):
        service.upsert_verified_reference(
            **common,
            positives=[],
            learning_scope=["culture"],
            job=_reference_job(),
        )
    with pytest.raises(ProfileWorkflowError, match="at least one area"):
        service.upsert_verified_reference(
            **common,
            positives=["Calm international team"],
            learning_scope=[],
            job=_reference_job(),
        )
    with pytest.raises(ProfileWorkflowError, match="structured evidence"):
        service.upsert_verified_reference(
            **common,
            positives=["Calm international team"],
            learning_scope=["culture"],
            job=None,
        )


def test_legacy_reference_learning_settings_remain_readable() -> None:
    reference = ReferenceJob.model_validate(
        {
            "url": "https://careers.example.com/jobs/legacy",
            "positives": [],
            "learning_enabled": True,
            "learning_scope": [],
        }
    )

    assert reference.learning_enabled is True
    assert reference.positives == []


def test_reference_learning_uses_only_concrete_evidence_backed_job_fact_keys(
    tmp_path: Path,
) -> None:
    service, workspace = _workflow(tmp_path)
    job = _job(
        title="Hybrid Engineer",
        location="Frankfurt",
        source_text=("Work from our Frankfurt office. Flexible hybrid work. A salary of 80k EUR."),
        facts=[
            JobFact(
                key="workplace.location",
                value="Frankfurt office",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Work from our Frankfurt office",
            ),
            JobFact(
                key="work_model.arrangement",
                value="hybrid work",
                kind=JobFactKind.OFFER,
                evidence_quote="Flexible hybrid work",
            ),
            JobFact(
                key="compensation.salary",
                value="salary 80k",
                kind=JobFactKind.OFFER,
                evidence_quote="A salary of 80k EUR",
            ),
        ],
    )

    saved = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/evidence",
        resolved_url="https://careers.example.com/jobs/evidence",
        http_status=200,
        verified_at=NOW,
        positives=["Frankfurt office", "Hybrid work", "Salary 80k"],
        negatives=[],
        learning_enabled=True,
        learning_scope=["location", "work_model", "pay"],
        job=job,
    )
    pending = [
        fact
        for fact in saved.session.profile.facts
        if fact.id in pending_reference_learning_ids(saved.session.profile)
    ]

    assert {fact.key for fact in pending} == {
        "workplace.location",
        "work_model.arrangement",
        "compensation.salary",
    }


def test_title_and_location_strings_without_job_facts_create_no_learning_proposal(
    tmp_path: Path,
) -> None:
    service, workspace = _workflow(tmp_path)

    saved = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/no-facts",
        resolved_url="https://careers.example.com/jobs/no-facts",
        http_status=200,
        verified_at=NOW,
        positives=["Automation Engineer", "Frankfurt am Main"],
        negatives=[],
        learning_enabled=True,
        learning_scope=["role", "location"],
        job=_job(title="Automation Engineer", location="Frankfurt am Main", facts=[]),
    )

    assert pending_reference_learning_ids(saved.session.profile) == []


def test_shared_pending_reference_provenance_survives_deleting_one_source(
    tmp_path: Path,
) -> None:
    service, workspace = _workflow(tmp_path)
    first = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/first",
        resolved_url="https://careers.example.com/jobs/first",
        http_status=200,
        verified_at=NOW,
        positives=["Technical ownership"],
        negatives=[],
        learning_enabled=True,
        learning_scope=["role"],
        job=_reference_job(),
    )
    first_reference_id = first.session.profile.reference_jobs[0].id
    second = service.upsert_verified_reference(
        workspace.id,
        requested_url="https://careers.example.com/jobs/second",
        resolved_url="https://careers.example.com/jobs/second",
        http_status=200,
        verified_at=NOW,
        positives=["Technical ownership"],
        negatives=[],
        learning_enabled=True,
        learning_scope=["role"],
        job=_reference_job(),
    )
    pending_id = pending_reference_learning_ids(second.session.profile)[0]
    pending = next(fact for fact in second.session.profile.facts if fact.id == pending_id)
    second_reference_id = second.session.profile.reference_jobs[1].id

    assert pending.source_reference_ids == [first_reference_id, second_reference_id]

    after_first_delete = service.delete_reference(workspace.id, first_reference_id)
    remaining = next(
        fact for fact in after_first_delete.session.profile.facts if fact.id == pending_id
    )
    assert remaining.source_reference_ids == [second_reference_id]
    assert pending_reference_learning_ids(after_first_delete.session.profile) == [pending_id]

    confirmed = service.confirm_facts(workspace.id, [pending_id], continue_guided=False)
    after_second_delete = service.delete_reference(workspace.id, second_reference_id)
    assert any(fact.id == pending_id for fact in confirmed.session.profile.confirmed_facts)
    assert any(
        fact.id == pending_id for fact in after_second_delete.session.profile.confirmed_facts
    )
