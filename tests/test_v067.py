from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from betteroption.container import ApplicationContainer
from betteroption.cv import CvRetention, extract_cv_text
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.job_context import EmployerContextService, EmployerKind, source_guidance
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchOutcome, match_job
from betteroption.mobility import (
    CommuteStatus,
    FallbackTravelTimeProvider,
    GoogleRoutesTravelTimeProvider,
    OpenRouteServiceTravelTimeProvider,
    TravelQuery,
)
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelMode,
)
from betteroption.profile_workflow import ProfileWorkflowError, ProfileWorkflowService
from betteroption.settings import Settings
from betteroption.web import create_app


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


class TwoFactExtractor:
    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        return SectionExtraction(
            summary="Two explicit preferences were found.",
            facts=[
                ExtractedFactDraft(
                    key="role.family",
                    value="Embedded software",
                    level=RequirementLevel.PREFERENCE,
                    evidence_status="explicit",
                    confidence=Confidence.HIGH,
                    source_quote="Embedded software",
                ),
                ExtractedFactDraft(
                    key="work_model.remote",
                    value="Hybrid",
                    level=RequirementLevel.PREFERENCE,
                    evidence_status="explicit",
                    confidence=Confidence.HIGH,
                    source_quote="Hybrid",
                ),
            ],
            follow_up_question=None,
        )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v067.db').as_posix()}",
            auth_mode="local",
            employer_homepage_research=False,
        )
    )


def _job(source: str, *, company: str = "Acme", url: str = "https://acme.example/jobs/1"):
    return JobPosting(
        title="Embedded Engineer",
        company=company,
        location="Frankfurt",
        summary="Build embedded products.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
    )


def test_bulk_confirmation_is_selected_and_atomic(tmp_path: Path) -> None:
    container = _container(tmp_path)
    service = ProfileWorkflowService(container.workspaces, extractor=TwoFactExtractor())
    workspace = service.start()
    workspace = service.add_private_evidence(
        workspace.id,
        "Embedded software. Hybrid.",
        source_label="uploaded CV",
    )
    pending = workspace.session.profile.pending_facts

    with pytest.raises(ProfileWorkflowError):
        service.confirm_facts(workspace.id, [pending[0].id, uuid4()])
    unchanged = container.workspaces.get(workspace.id)
    assert unchanged is not None
    assert len(unchanged.session.profile.pending_facts) == 2

    saved = service.confirm_facts(
        workspace.id,
        [fact.id for fact in pending],
        continue_guided=False,
    )
    assert len(saved.session.profile.confirmed_facts) == 2
    assert not saved.session.profile.pending_facts


def test_employer_and_work_mode_context_stay_evidence_backed() -> None:
    source = (
        "Join our team at Acme. Hybrid work is available with 2 days per week in office. "
        "The role is 35 hours per week."
    )
    context = EmployerContextService(research_homepages=False).assess(_job(source))

    assert context.employer.kind == EmployerKind.DIRECT_EMPLOYER
    assert context.employer.likely_direct_contract is True
    assert {fact.key for fact in context.work_mode_facts} >= {
        "work_model.hybrid",
        "work_model.office_days",
        "work_model.weekly_hours",
    }
    assert all(fact.evidence_quote in source for fact in context.work_mode_facts)


def test_staffing_evidence_resolves_direct_contract_boundary() -> None:
    source = "We are a Personaldienstleister offering Arbeitnehmerüberlassung for our client."
    job = _job(source, company="Talent Staffing")
    context = EmployerContextService(research_homepages=False).assess(job)
    profile_fact = ProfileFact(
        key="employment.arrangement",
        value="Direct employer contract",
        level=RequirementLevel.MUST_HAVE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.MUST_HAVES,
            text="Direct employer contract",
        ),
    )
    from betteroption.profile import CandidateProfile

    profile = CandidateProfile(facts=[profile_fact])
    result = match_job(profile, job, context=context)

    assert context.employer.kind == EmployerKind.STAFFING_AGENCY
    assert result.reasons[0].outcome == MatchOutcome.VIOLATED
    assert result.reasons[0].evidence_quotes


def test_linkedin_guidance_requests_the_canonical_employer_source() -> None:
    guidance = source_guidance("https://www.linkedin.com/jobs/view/123")
    assert guidance is not None
    assert "does not permit" in guidance
    assert "employer's careers page" in guidance


def test_mobility_falls_back_to_openrouteservice_with_diagnostics() -> None:
    google_transport = httpx.MockTransport(
        lambda request: httpx.Response(503, request=request, json={"error": "temporary"})
    )

    def ors_handler(request: httpx.Request) -> httpx.Response:
        if "/geocode/search" in request.url.path:
            value = 8.6 if "Frankfurt" in str(request.url) else 8.9
            return httpx.Response(
                200,
                request=request,
                json={"features": [{"geometry": {"coordinates": [value, 50.1]}}]},
            )
        return httpx.Response(
            200,
            request=request,
            json={"routes": [{"summary": {"duration": 1800, "distance": 22000}}]},
        )

    google = GoogleRoutesTravelTimeProvider(
        "google-key",
        client=httpx.Client(transport=google_transport),
    )
    ors = OpenRouteServiceTravelTimeProvider(
        "ors-key",
        client=httpx.Client(transport=httpx.MockTransport(ors_handler)),
    )
    provider = FallbackTravelTimeProvider([google, ors])
    estimate = provider.estimate(
        TravelQuery(origin="Frankfurt", destination="Darmstadt", mode=TravelMode.CAR)
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.provider == "openrouteservice"
    assert estimate.duration_minutes == 30
    assert any("Google Routes failed" in attempt for attempt in estimate.attempts)
    assert "openrouteservice" in (estimate.attribution or "")
    assert provider.persistent_cache_allowed is True


def test_cv_binary_is_not_persisted_and_text_can_be_deleted(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    content = b"Alex Example\nEmbedded software engineer\nPython C++ test automation"
    document = container.cvs.save(
        workspace.id,
        "resume.txt",
        "text/plain",
        content,
        CvRetention.UNTIL_DELETED,
    )

    assert "Embedded software" in document.extracted_text
    assert document.content_hash
    columns = {
        column["name"] for column in inspect(container.database.engine).get_columns("cv_documents")
    }
    assert "binary_content" not in columns
    assert container.cvs.delete(workspace.id, document.id)
    assert container.cvs.list_for_workspace(workspace.id) == []


def test_cv_type_validation_rejects_disguised_pdf() -> None:
    with pytest.raises(ValueError, match="not a PDF"):
        extract_cv_text("resume.pdf", b"This is not really a PDF but has enough text.")


def test_review_tray_bulk_controls_confirm_selected_statements(tmp_path: Path) -> None:
    container = _container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=TwoFactExtractor(),
        )
    )
    started = client.post("/profile/start", follow_redirects=False)
    workspace_id = started.headers["location"].rsplit("/", 1)[-1]
    service = ProfileWorkflowService(
        container.workspaces,
        extractor=TwoFactExtractor(),
    )
    service.add_private_evidence(
        UUID(workspace_id),
        "Embedded software. Hybrid.",
        source_label="uploaded CV",
    )
    review = client.get(f"/profile/{workspace_id}/review?return_to=compass")
    workspace = container.workspaces.latest()
    assert workspace is not None

    assert "Confirm selected" in review.text
    assert "Select all" in review.text
    assert review.text.count('name="selected_fact_ids"') == 2
    selected = client.post(
        f"/profile/{workspace_id}/confirm-selected",
        data={
            "return_to": "compass",
            "selected_fact_ids": [str(fact.id) for fact in workspace.session.profile.pending_facts],
        },
        follow_redirects=False,
    )
    assert selected.status_code == 303
    saved = container.workspaces.latest()
    assert saved is not None
    assert len(saved.session.profile.confirmed_facts) == 2


def test_cv_upload_requires_preview_and_never_persists_text(tmp_path: Path) -> None:
    container = _container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=TwoFactExtractor(),
        )
    )
    started = client.post("/profile/start", follow_redirects=False)
    workspace_id = started.headers["location"].rsplit("/", 1)[-1]
    preview = client.post(
        f"/profile/{workspace_id}/cv",
        data={"acknowledge_cv_rules": "true"},
        files={
            "cv_file": (
                "resume.txt",
                b"Embedded software engineer with Python and test automation experience.",
                "text/plain",
            )
        },
        follow_redirects=False,
    )

    assert preview.status_code == 200
    assert "Review the exact text you choose to share" in preview.text
    assert "Where this text goes" in preview.text
    workspace = container.workspaces.latest()
    assert workspace is not None
    assert container.cvs.list_for_workspace(workspace.id) == []
    assert workspace.session.profile.pending_facts == []

    response = client.post(
        f"/profile/{workspace_id}/cv/confirm",
        data={
            "selected_text": (
                "Embedded software engineer with Python and test automation experience."
            ),
            "cv_ai_consent": "true",
            "confirm_no_sensitive_data": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "/review?return_to=compass" in response.headers["location"]
    workspace = container.workspaces.latest()
    assert workspace is not None
    assert workspace.session.profile.pending_facts
    assert container.cvs.list_for_workspace(workspace.id) == []
    assert workspace.session.profile.raw_sections.get(ProfileSection.EXPERIENCE) is None
