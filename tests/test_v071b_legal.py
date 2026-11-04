from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from betteroption import __version__
from betteroption.accounts import (
    AccountInvitationRow,
    AuthAttemptRow,
    AuthSessionRow,
    RegistrationMode,
)
from betteroption.container import ApplicationContainer
from betteroption.cv import CvDocumentRow, CvRetention, sanitize_cv_text
from betteroption.extraction import SectionExtraction
from betteroption.llm import InvocationOutcome, LLMTask
from betteroption.operations import (
    ProviderOperation,
    ProviderOperationOutcome,
    ProviderOperationRow,
)
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    SourceExcerpt,
)
from betteroption.profile_workflow import ProfileWorkflowError, ProfileWorkflowService
from betteroption.profile_repository import ConversationMessageRow, ConversationRole
from betteroption.retention import REDACTED_SOURCE_TEXT, RetentionPolicy, run_retention
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.telemetry import ModelInvocationRow
from betteroption.web import create_app


@pytest.fixture(autouse=True)
def _clear_ambient_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider/legal assertions must not inherit a developer's real shell keys."""

    for key in (
        "OPENAI_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "BRAVE_ANSWERS_API_KEY",
        "EXA_API_KEY",
        "GOOGLE_ROUTES_API_KEY",
        "OPENROUTESERVICE_API_KEY",
        "APIFY_API_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_release_keeps_legal_baseline_in_distinct_account_persona_iteration() -> None:
    assert __version__ == "0.7.2k"


def test_cv_sanitization_removes_common_identifiers_before_preview() -> None:
    result = sanitize_cv_text(
        "\n".join(
            (
                "Alex Example",
                "alex@example.com | +49 30 00000000 | https://linkedin.com/in/alex-example",
                "Musterstraße 12, 60311 Frankfurt",
                "Embedded engineer with Python, C++, CI and test automation.",
            )
        )
    )

    assert "Alex Example" not in result.text
    assert "alex@example.com" not in result.text
    assert "12345678" not in result.text
    assert "linkedin.com" not in result.text
    assert "Musterstraße" not in result.text
    assert set(result.redactions) == {
        "likely name/header",
        "email address",
        "personal URL",
        "phone number",
        "exact address",
    }
    assert not result.blocked


def test_cv_sanitization_flags_sensitive_categories_without_returning_matches() -> None:
    result = sanitize_cv_text(
        "Embedded engineer with a disability and a recorded security clearance."
    )

    assert result.blocked_categories == [
        "health or disability",
        "criminal-offence or security-clearance information",
    ]


def test_compass_sensitive_input_is_stopped_before_provider_call(tmp_path: Path) -> None:
    class Extractor:
        def __init__(self) -> None:
            self.calls: list[tuple[ProfileSection, str]] = []

        def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
            self.calls.append((section, user_text))
            return SectionExtraction(summary="Not reached.", facts=[], follow_up_question=None)

    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'screening.db').as_posix()}",
        background_worker_enabled=False,
    )
    container = ApplicationContainer(settings)
    extractor = Extractor()
    service = ProfileWorkflowService(container.workspaces, extractor=extractor)
    workspace = service.start()

    with pytest.raises(ProfileWorkflowError, match="health or disability"):
        service.answer(workspace.id, "I have a disability and need a Python role.")

    assert extractor.calls == []


def test_legal_and_ai_notices_are_public_and_fail_closed(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'legal.db').as_posix()}",
        auth_mode="accounts",
        registration_mode="invite_only",
        background_worker_enabled=False,
        transitous_enabled=False,
        valhalla_enabled=False,
        osm_geocoder_enabled=False,
    )
    client = TestClient(
        create_app(ApplicationContainer(settings), data_directory=tmp_path / "data")
    )

    for path in (
        "/legal/imprint",
        "/legal/privacy",
        "/legal/terms",
        "/legal/ai",
        "/legal/storage",
    ):
        response = client.get(path)
        assert response.status_code == 200

    privacy = client.get("/legal/privacy").text
    ai_notice = client.get("/legal/ai").text
    terms = client.get("/legal/terms").text
    assert "Launch blocked" in privacy
    assert "acknowledging this notice is not consent" in privacy
    assert "No optional search, geocoding or route provider is enabled" in privacy
    assert "recommendations exclusively for the candidate" in privacy
    assert "The research adapter never receives your compensation criterion" in ai_notice
    assert "A German benchmark is never extrapolated to another country" in ai_notice
    assert "not pay advertised by the employer and not a hard matching blocker" in ai_notice
    assert "Returned country, original currency, pay period" in privacy
    assert "No secondary salary source is currently enabled" in privacy
    assert "does not promise coverage of every European country or occupation" in privacy
    assert "Contact names, identifying roles, email addresses, phone numbers" in privacy
    assert "removed from every drafting-prompt surface" in privacy
    assert "does not deliberately supply a contact identity or infer gender" in privacy
    assert "deterministic application layer" in ai_notice
    assert "not in an LLM" in ai_notice
    assert "no configured model receives the extracted contact fields" in ai_notice
    assert "never infers gender from a name" in ai_notice
    assert "Private employer ratings and notes are excluded" in privacy
    assert "Placeholder employers such as “Unknown”" in ai_notice
    assert "Annex III point 4(a) of the EU AI Act" in privacy
    assert "This is not a completed legal classification" in ai_notice
    assert "Article 14 concept" in privacy
    assert "Articles 13/14 contact-transparency records" in terms
    assert "Salary research uses only public job fields" in terms
    assert "verified job-poster and public-vacancy prototype" in privacy
    assert "receives no candidate profile, persona, ranking, match, rating or draft data" in privacy
    assert "Job-poster access" in privacy
    assert "Public vacancies supplied by an approved poster" in privacy
    assert "posters never receive candidate workspace data" in privacy
    assert "hosted publication must fail closed" in privacy
    assert "Articles 13 or 14 transparency route" in privacy
    assert "Articles 14, 16 and 17" in privacy
    assert "Article 19 may exempt" in privacy
    assert "does not remove the earlier hosting-service duties" in privacy
    assert "candidate-side ranking that includes first-party vacancies" in privacy
    assert "Separate verified job-poster prototype" in terms
    assert "poster receives no candidate data or analytics" in terms
    assert "Fake, deceptive, duplicate, discriminatory or unlawful vacancies" in terms
    assert "Moderation, notices and review" in terms
    assert "Article 16 notice/action" in terms
    assert "No high-risk/non-high-risk conclusion is made" in terms
    assert "Separate public-vacancy prototype" in ai_notice
    assert "Publication itself does not send candidate data" in ai_notice
    assert "does not by itself settle" in ai_notice
    for text in (privacy, terms, ai_notice):
        assert "CELEX:32024R1689" in text
    for text in (privacy, terms):
        assert "CELEX:32016R0679" in text
        assert "2022/2065" in text


def test_staging_example_disables_unreviewed_optional_providers() -> None:
    example = (Path(__file__).resolve().parents[1] / "deploy" / ".env.staging.example").read_text(
        encoding="utf-8"
    )

    assert "BETTEROPTION_TRANSITOUS_ENABLED=false" in example
    assert "BETTEROPTION_VALHALLA_ENABLED=false" in example
    assert "BETTEROPTION_OSM_GEOCODER_ENABLED=false" in example
    assert "BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD=0" in example
    assert "BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD=0" in example
    assert "YDC_API_KEY=" in example
    assert "BETTEROPTION_YOU_SEARCH_ESTIMATED_COST_PER_CALL_USD=0" in example


def test_privacy_notice_discloses_enabled_salary_web_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ApplicationContainer, "salary_benchmark_provider", lambda self: None)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'salary-legal.db').as_posix()}",
        salary_research_enabled=True,
        background_worker_enabled=False,
    )
    client = TestClient(
        create_app(ApplicationContainer(settings), data_directory=tmp_path / "data")
    )

    privacy = client.get("/legal/privacy").text

    assert "OpenAI salary web search" in privacy
    assert "No optional search, geocoding or route provider is enabled" not in privacy


def test_staging_blocks_external_processors_until_review(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
        app_environment="staging",
        processor_review_completed=False,
        brave_search_api_key="configured-but-not-reviewed",
        exa_search_api_key="configured-but-not-reviewed",
        google_routes_api_key="configured-but-not-reviewed",
        mobility_provider="google",
        mobility_privacy_mode="balanced",
    )
    container = ApplicationContainer(settings)

    with pytest.raises(RuntimeError, match="processor review"):
        container.profile_extractor()
    assert container.travel_time_provider().name == "not-configured"
    discovery = container.job_discovery_provider()
    assert "brave-web" not in {
        provider.name for provider in [*discovery.primary_providers, *discovery.fallback_providers]
    }


def test_retention_minimises_raw_profile_content_and_old_facts(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
    old = now - timedelta(days=31)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'profile-retention.db').as_posix()}")
    container = ApplicationContainer(settings)
    profile_session = new_session()
    direction = profile_session.sections[0]
    direction.updated_at = old
    direction.summary = "Private summary"
    direction.clarification_answer = "Private clarification"
    profile_session.profile.updated_at = old
    profile_session.profile.raw_sections[ProfileSection.DIRECTION] = "Private raw answer"
    profile_session.profile.unresolved_questions = ["Private unresolved question"]
    pending = ProfileFact(
        created_at=old,
        key="skill.pending",
        value="Old pending fact",
        evidence_status=EvidenceStatus.EXPLICIT,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text="Old source"),
    )
    rejected = ProfileFact(
        created_at=old,
        reviewed_at=now - timedelta(days=8),
        key="skill.rejected",
        value="Old rejected fact",
        evidence_status=EvidenceStatus.REJECTED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text="Old rejection"),
    )
    confirmed = ProfileFact(
        created_at=old,
        reviewed_at=old,
        key="skill.confirmed",
        value="Python",
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=ProfileSection.DIRECTION, text="Private source text"),
    )
    profile_session.profile.facts = [pending, rejected, confirmed]
    direction.proposed_fact_ids = [pending.id, rejected.id, confirmed.id]
    workspace = container.workspaces.create(profile_session)
    container.workspaces.add_message(
        workspace.id,
        ConversationRole.USER,
        "Private conversation text",
        section=ProfileSection.DIRECTION,
    )
    with container.database.session_factory.begin() as session:
        message = session.scalar(select(ConversationMessageRow))
        assert message is not None
        message.created_at = old

    report = run_retention(container.database, RetentionPolicy(), now=now)
    restored = container.workspaces.get(workspace.id)

    assert restored is not None
    assert restored.session.profile.raw_sections == {}
    assert restored.session.profile.unresolved_questions == []
    assert [fact.key for fact in restored.session.profile.facts] == ["skill.confirmed"]
    assert restored.session.profile.facts[0].source.text == REDACTED_SOURCE_TEXT
    assert restored.session.sections[0].summary is None
    assert restored.session.sections[0].clarification_answer is None
    assert restored.session.sections[0].proposed_fact_ids == [confirmed.id]
    assert container.workspaces.messages(workspace.id) == []
    assert report.pending_facts == 1
    assert report.rejected_facts == 1
    assert report.source_excerpts == 1


def test_retention_purges_auth_cv_and_provider_metadata(tmp_path: Path) -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'record-retention.db').as_posix()}")
    container = ApplicationContainer(settings)
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.FIRST_USER,
    )
    auth_session = container.accounts.create_session(account, ttl=timedelta(hours=1))
    invitation, _token = container.accounts.create_invitation(
        "invitee@example.com",
        invited_by_account_id=account.id,
        ttl=timedelta(hours=1),
    )
    workspace = container.workspaces.create(new_session(), account_id=account.id)
    document = container.cvs.save(
        workspace.id,
        "legacy.txt",
        "text/plain",
        b"Legacy CV text with Python engineering experience.",
        CvRetention.UNTIL_DELETED,
    )
    old_telemetry = now - timedelta(days=91)
    container.operations.record(
        ProviderOperation(
            provider="openai",
            purpose="test",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=old_telemetry,
            finished_at=old_telemetry,
            latency_ms=1,
        )
    )
    with container.database.session_factory.begin() as session:
        stored_session = session.scalar(
            select(AuthSessionRow).where(AuthSessionRow.token_hash.is_not(None))
        )
        assert stored_session is not None
        stored_session.expires_at = now - timedelta(seconds=1)
        stored_invitation = session.get(AccountInvitationRow, str(invitation.id))
        assert stored_invitation is not None
        stored_invitation.expires_at = now - timedelta(days=8)
        stored_cv = session.get(CvDocumentRow, str(document.id))
        assert stored_cv is not None
        stored_cv.uploaded_at = now - timedelta(hours=25)
        session.add(
            AuthAttemptRow(
                id=str(uuid4()),
                action="login",
                subject_hash="a" * 64,
                created_at=now - timedelta(days=8),
            )
        )
        session.add(
            ModelInvocationRow(
                id=str(uuid4()),
                task=LLMTask.PROFILE_EXTRACTION.value,
                provider="openai",
                model="test",
                prompt_version="test",
                attempt=1,
                outcome=InvocationOutcome.SUCCEEDED.value,
                started_at=old_telemetry,
                finished_at=old_telemetry,
                latency_ms=1,
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                estimated_cost_usd=None,
                error_type=None,
            )
        )

    report = run_retention(container.database, RetentionPolicy(), now=now)
    with container.database.session_factory() as session:
        assert session.scalar(select(func.count(AuthSessionRow.id))) == 0
        assert session.scalar(select(func.count(AccountInvitationRow.id))) == 0
        assert session.scalar(select(func.count(AuthAttemptRow.id))) == 0
        assert session.scalar(select(func.count(CvDocumentRow.id))) == 0
        assert session.scalar(select(func.count(ModelInvocationRow.id))) == 0
        assert session.scalar(select(func.count(ProviderOperationRow.id))) == 0
    assert report.total_changes == 6
    assert container.accounts.resolve_session(auth_session.token) is None
