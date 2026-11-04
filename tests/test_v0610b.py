from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchOutcome, match_job
from betteroption.operations import (
    ProviderOperation,
    ProviderOperationOutcome,
)
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.profile_consistency import inspect_profile_consistency
from betteroption.result_repository import ApplicationState
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime.now(timezone.utc)


def _fact(key: str, value: str, level: RequirementLevel) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.LOCATION_MOBILITY, text=value),
        needs_confirmation=False,
    )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v0610b.db').as_posix()}",
            auth_mode="local",
            employer_homepage_research=False,
        )
    )


def _seed_job(container: ApplicationContainer) -> str:
    url = "https://careers.example.com/jobs/application-state"
    source = "Test Engineer at Example Products. Python and test automation are required."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title="Test Engineer",
        company="Example Products",
        location="Frankfurt",
        summary="Build test automation for a product team.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
    )
    return str(container.repository.store_revision(document, job, JobObservationKind.NEW).id)


def test_internship_exclusion_explanation_preserves_negative_polarity() -> None:
    exclusion = _fact("role.level", "internship", RequirementLevel.EXCLUSION)
    job = JobPosting(
        title="Junior Test Engineer",
        company="Example",
        location="Frankfurt",
        summary="An individual-contributor graduate role with no leadership responsibility.",
        source_type=JobSourceType.SAMPLE,
        source_name="v0.6.10b",
        source_text="Graduate role with no leadership responsibility.",
    )

    result = match_job(CandidateProfile(facts=[exclusion]), job)

    reason = result.reasons[0]
    assert reason.outcome == MatchOutcome.SATISFIED
    assert "Compass excludes intern roles" in reason.explanation
    assert "exclusion does not apply" in reason.explanation
    assert "Compass targets intern" not in reason.explanation


def test_no_internship_does_not_conflict_with_a_junior_target() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("role.level", "junior", RequirementLevel.MUST_HAVE),
            _fact("role.level", "internship", RequirementLevel.EXCLUSION),
        ]
    )

    issues = inspect_profile_consistency(profile)

    assert not [issue for issue in issues if issue.code == "seniority-extremes"]


def test_commute_limits_require_a_resolvable_starting_point() -> None:
    without_origin = CandidateProfile(
        facts=[_fact("commute.car.max_minutes", "60 minutes by car", RequirementLevel.MUST_HAVE)]
    )
    with_origin = CandidateProfile(
        facts=[
            _fact("location.origin", "60486", RequirementLevel.MUST_HAVE),
            _fact("commute.car.max_minutes", "60 minutes by car", RequirementLevel.MUST_HAVE),
        ]
    )

    assert "missing-mobility-origin" in {
        issue.code for issue in inspect_profile_consistency(without_origin)
    }
    assert not {
        "missing-mobility-origin",
        "unresolved-mobility-origin",
    }.intersection(issue.code for issue in inspect_profile_consistency(with_origin))


def test_operation_breakdown_and_dashboard_are_privacy_safe(tmp_path: Path) -> None:
    container = _container(tmp_path)
    container.operations.record(
        ProviderOperation(
            provider="example-search",
            purpose="job-discovery",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
            latency_ms=25,
            result_count=7,
            estimated_cost_usd=0.01,
        )
    )

    breakdown = container.operations.breakdown_since(NOW.replace(hour=0, minute=0, second=0))
    page = TestClient(create_app(container, data_directory=tmp_path / "data")).get("/operations")

    assert breakdown[0].provider == "example-search"
    assert breakdown[0].result_count == 7
    assert breakdown[0].average_latency_ms == 25
    assert page.status_code == 200
    assert "Know what the providers cost" in page.text
    assert "example-search" in page.text
    assert (
        "Candidate searches, locations, prompts, CV text, job text, URLs, and API keys" in page.text
    )


def test_application_state_auto_saves_from_archive_and_colors_the_card(tmp_path: Path) -> None:
    container = _container(tmp_path)
    container.workspaces.create(new_session())
    record_id = _seed_job(container)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    before = client.get("/jobs")
    saved = client.post(
        f"/jobs/{record_id}/application-state",
        data={"application_state": "applied"},
    )
    after = client.get("/jobs")

    assert before.status_code == 200
    assert "Application state" in before.text
    assert f"/jobs/{record_id}/application-state" in before.text
    assert saved.status_code == 200
    assert saved.json() == {"state": "applied", "label": "Applied"}
    assert 'data-application-state-card="applied"' in after.text
    assert '<option value="applied" selected>Applied</option>' in after.text
    interaction = container.results.get_interaction(
        container.workspaces.latest().id,
        record_id,
    )
    assert interaction.application_state == ApplicationState.APPLIED
