from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from betteroption.container import ApplicationContainer
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.jobs import JobSourceType
from betteroption.profile import EvidenceStatus, ProfileSection, RequirementLevel
from betteroption.profile_repository import (
    ConversationMessageRow,
    ConversationRole,
    ProfileWorkspaceRepository,
    ProfileWorkspaceRow,
)
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import SectionStatus, new_session, progress_for, save_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument, UrlFailureKind, UrlIngestionError
from betteroption.web import create_app


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
REFERENCE_URL = "https://careers.example.com/jobs/platform-123"


class FakeExtractor:
    model = "profile-test-model"

    def __init__(self, *, follow_up_question: str | None = None) -> None:
        self.follow_up_question = follow_up_question
        self.calls: list[tuple[ProfileSection, str]] = []

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        self.calls.append((section, user_text))
        return SectionExtraction(
            summary="Platform engineering is a positive direction.",
            facts=[
                ExtractedFactDraft(
                    key="role.family",
                    value="Platform engineering",
                    level="preference",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="platform engineering",
                )
            ],
            follow_up_question=self.follow_up_question,
        )


class FakeFetcher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchedDocument:
        self.urls.append(url)
        if self.error:
            raise self.error
        return FetchedDocument(
            requested_url=url,
            final_url=REFERENCE_URL,
            status_code=200,
            content_type="text/html",
            text=(
                "Platform Engineer at Example. Build reliable developer tooling "
                "with a calm product team and flexible hybrid work."
            ),
            fetched_at=NOW,
        )


class FakeJobExtractor:
    model = "job-test-model"

    def extract(self, source_text: str, **metadata):
        return JobExtraction(
            title="Platform Engineer",
            company="Example",
            location="Frankfurt",
            summary="Build reliable developer tooling with a calm product team.",
            facts=[
                JobFactDraft(
                    key="role.family",
                    value="platform engineering",
                    kind="context",
                    evidence_quote="Platform Engineer",
                ),
                JobFactDraft(
                    key="role.responsibility",
                    value="technical ownership",
                    kind="context",
                    evidence_quote="Build reliable developer tooling",
                ),
                JobFactDraft(
                    key="culture.signal",
                    value="calm team",
                    kind="offer",
                    evidence_quote="calm product team",
                ),
            ],
        ).to_job_posting(source_text=source_text, **metadata)


def build_container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'betteroption.db').as_posix()}",
            auth_mode="local",
        )
    )


def start_profile(client: TestClient) -> UUID:
    response = client.post("/profile/start", follow_redirects=False)
    assert response.status_code == 303
    return UUID(response.headers["location"].rsplit("/", 1)[-1])


def answer_first_section(client: TestClient, workspace_id: UUID) -> UUID:
    response = client.post(
        f"/profile/{workspace_id}/answer",
        data={"answer": "I would enjoy platform engineering."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/profile/{workspace_id}/guided"
    workspace = client.app.state.container.workspaces.get(workspace_id)
    assert workspace is not None
    return workspace.session.profile.confirmed_facts[0].id


def test_repository_round_trips_private_profile_and_messages_in_database(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = container.workspaces.create()
    workspace.session.profile.raw_sections[ProfileSection.DIRECTION] = "Private answer"
    container.workspaces.save(workspace)
    container.workspaces.add_message(
        workspace.id,
        ConversationRole.USER,
        "Private answer",
        section=ProfileSection.DIRECTION,
    )

    reopened = ProfileWorkspaceRepository(container.database).get(workspace.id)
    messages = ProfileWorkspaceRepository(container.database).messages(workspace.id)

    assert reopened is not None
    assert reopened.session.profile.raw_sections[ProfileSection.DIRECTION] == "Private answer"
    assert messages[0].content == "Private answer"
    assert messages[0].role == ConversationRole.USER
    assert not list(tmp_path.rglob("session-*.json"))
    assert not list(tmp_path.rglob("profile-*.json"))


def test_legacy_json_checkpoint_is_adopted_once(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    sessions = tmp_path / "legacy" / "sessions"
    legacy = new_session()
    save_session(legacy, sessions)

    first = container.workspaces.adopt_latest_file(sessions)
    second = container.workspaces.adopt_latest_file(sessions)

    assert first is not None
    assert second is not None
    assert first.id == legacy.id
    assert second.id == legacy.id
    with container.database.session_factory() as database_session:
        workspace_count = database_session.scalar(
            select(func.count()).select_from(ProfileWorkspaceRow)
        )
        message_count = database_session.scalar(
            select(func.count()).select_from(ConversationMessageRow)
        )
    assert workspace_count == 1
    assert message_count == 1


def test_web_conversation_resumes_with_interpreted_answer_active_after_restart(
    tmp_path: Path,
) -> None:
    extractor = FakeExtractor()
    container = build_container(tmp_path)
    client = TestClient(
        create_app(container, data_directory=tmp_path / "data", profile_extractor=extractor)
    )
    workspace_id = start_profile(client)
    answer_first_section(client, workspace_id)

    restarted = build_container(tmp_path)
    resumed_client = TestClient(
        create_app(restarted, data_directory=tmp_path / "data", profile_extractor=extractor)
    )
    response = resumed_client.get(f"/profile/{workspace_id}", follow_redirects=False)

    assert response.status_code == 200
    assert "Platform engineering" in response.text
    reopened = restarted.workspaces.get(workspace_id)
    assert reopened is not None
    assert reopened.session.profile.pending_facts == []


def test_immediate_compass_fact_edit_and_category_are_authoritative_database_decisions(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=FakeExtractor(),
        )
    )
    workspace_id = start_profile(client)
    fact_id = answer_first_section(client, workspace_id)

    response = client.post(
        f"/profile/{workspace_id}/saved-facts/{fact_id}",
        data={
            "action": "edit_value",
            "new_value": "Developer platform engineering",
            "new_level": "must_have",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    fact = next(item for item in workspace.session.profile.facts if item.id == fact_id)
    assert fact.value == "Developer platform engineering"
    assert fact.level == RequirementLevel.MUST_HAVE
    assert fact.evidence_status == EvidenceStatus.CONFIRMED
    assert len(workspace.session.profile.review_events) == 3
    assert (
        progress_for(workspace.session, ProfileSection.DIRECTION).status == SectionStatus.COMPLETED
    )
    assert (
        progress_for(workspace.session, ProfileSection.LOCATION_MOBILITY).status
        == SectionStatus.PENDING
    )


def test_immediate_compass_fact_removal_is_persisted(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=FakeExtractor(),
        )
    )
    workspace_id = start_profile(client)
    fact_id = answer_first_section(client, workspace_id)

    response = client.post(
        f"/profile/{workspace_id}/saved-facts/{fact_id}",
        data={"action": "reject"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    fact = next(item for item in workspace.session.profile.facts if item.id == fact_id)
    assert fact.evidence_status == EvidenceStatus.REJECTED
    assert workspace.session.completed_count == 1


def test_compass_can_update_one_section_without_restarting_the_guided_loop(
    tmp_path: Path,
) -> None:
    extractor = FakeExtractor()
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=extractor,
        )
    )
    workspace_id = start_profile(client)

    proposed = client.post(
        f"/profile/{workspace_id}/sections/direction/detail",
        data={"answer": "I want platform engineering."},
        follow_redirects=False,
    )
    assert proposed.headers["location"].startswith(f"/profile/{workspace_id}?notice=")
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    page = client.get(f"/profile/{workspace_id}")

    assert "Change one thing without starting over" in page.text
    assert page.text.count("Add to Compass") == 9
    assert "Platform engineering" in page.text
    assert extractor.calls == [(ProfileSection.DIRECTION, "I want platform engineering.")]


def test_compass_direct_fact_edit_and_removal_change_active_matching_input(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=FakeExtractor(),
        )
    )
    workspace_id = start_profile(client)
    fact_id = answer_first_section(client, workspace_id)

    edited = client.post(
        f"/profile/{workspace_id}/saved-facts/{fact_id}",
        data={
            "action": "edit_value",
            "new_value": "Embedded platform engineering",
            "new_level": "must_have",
        },
        follow_redirects=False,
    )
    workspace = container.workspaces.get(workspace_id)
    assert edited.status_code == 303
    assert workspace is not None
    fact = next(item for item in workspace.session.profile.facts if item.id == fact_id)
    assert fact.value == "Embedded platform engineering"
    assert fact.level == RequirementLevel.MUST_HAVE

    removed = client.post(
        f"/profile/{workspace_id}/saved-facts/{fact_id}",
        data={"action": "reject"},
        follow_redirects=False,
    )
    workspace = container.workspaces.get(workspace_id)
    assert removed.status_code == 303
    assert workspace is not None
    assert fact_id not in {item.id for item in workspace.session.profile.confirmed_facts}


def test_add_page_saves_a_reachable_job_and_all_reference_settings_in_one_flow(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)

    response = client.post(
        "/add/jobs",
        data={
            "url": "https://short.example/jobs/123",
            "positives": "Technical ownership\nCalm team",
            "negatives": "Three office days",
            "learning_enabled": "true",
            "learning_scope": ["role", "culture"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"/profile/{workspace_id}/review?return_to=compass" in response.headers["location"]
    assert fetcher.urls == ["https://short.example/jobs/123"]
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    reference = workspace.session.profile.reference_jobs[0]
    assert str(reference.url) == "https://short.example/jobs/123"
    assert str(reference.resolved_url) == REFERENCE_URL
    assert reference.url_http_status == 200
    assert reference.positives == ["Technical ownership", "Calm team"]
    assert reference.negatives == ["Three office days"]
    assert reference.learning_enabled is True
    assert reference.learning_scope == ["role", "culture"]
    assert workspace.session.profile.reference_learning_fact_ids
    assert container.repository.count_records() == 1
    review = client.get(response.headers["location"])
    assert REFERENCE_URL in review.text

    updated = client.post(
        "/add/jobs",
        data={
            "url": "https://short.example/jobs/123",
            "positives": "Deeper technical ownership",
            "negatives": "Weekly travel",
        },
        follow_redirects=False,
    )
    refreshed_workspace = container.workspaces.get(workspace_id)
    assert updated.status_code == 303
    assert refreshed_workspace is not None
    assert container.repository.count_records() == 1
    assert len(refreshed_workspace.session.profile.reference_jobs) == 1
    refreshed_reference = refreshed_workspace.session.profile.reference_jobs[0]
    assert refreshed_reference.id == reference.id
    assert refreshed_reference.positives == ["Deeper technical ownership"]
    assert refreshed_reference.negatives == ["Weekly travel"]
    assert refreshed_reference.learning_enabled is False
    assert refreshed_workspace.session.profile.reference_learning_fact_ids == []
    assert fetcher.urls == [
        "https://short.example/jobs/123",
        "https://short.example/jobs/123",
    ]

    add_page = client.get("/add")
    matches = client.get("/matches")
    archive = client.get("/jobs")
    assert "Jobs with reference notes" in add_page.text
    assert "Deeper technical ownership" in add_page.text
    assert "Deeper technical ownership" not in matches.text
    assert "Everything you chose to keep" in archive.text
    assert "Platform Engineer" in archive.text


def test_unreachable_reference_is_not_saved(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)

    response = client.post(
        "/matches/jobs",
        data={"url": "This is copied job text, not a URL"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "job+URL+must+use+http" in response.headers["location"]
    assert fetcher.urls == []
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert workspace.session.profile.reference_jobs == []


def test_manual_reference_is_marked_and_never_refetched(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)
    source_text = (
        "Platform Engineer at Example. Build reliable developer tooling with a calm "
        "product team and flexible hybrid work. Please send a CV to jobs@example.com."
    )

    response = client.post(
        "/add/jobs/manual",
        data={
            "source_url": REFERENCE_URL,
            "source_text": source_text,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "Manual+job+text+saved" in response.headers["location"]
    assert fetcher.urls == []
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    reference = workspace.session.profile.reference_jobs[0]
    assert reference.input_method == "manual_text"
    assert reference.resolved_url is None
    record = container.repository.list_records()[0]
    job = container.repository.get_current_job(record.id)
    assert job is not None
    assert job.source_type == JobSourceType.MANUAL_TEXT
    assert job.url_checked_at is None

    add_page = client.get("/add")
    detail_page = client.get(f"/jobs/{record.id}")
    refresh = client.post(f"/jobs/{record.id}/refresh", follow_redirects=False)

    assert "Manual input · never rechecked" in add_page.text
    assert "Manual input · its saved text is never fetched or reverified" in detail_page.text
    assert "Manual+input+is+never+fetched+or+reverified" in refresh.headers["location"]
    assert fetcher.urls == []


def test_primary_add_form_uses_manual_text_without_fetching(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)
    source_text = (
        "Platform Engineer at Example. Build reliable developer tooling with a calm "
        "product team and flexible hybrid work. Please send a CV to jobs@example.com."
    )

    response = client.post(
        "/add/jobs",
        data={
            "url": REFERENCE_URL,
            "manual_source_text": source_text,
            "positives": "Calm product team",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "Manual+job+text+saved" in response.headers["location"]
    assert fetcher.urls == []
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert workspace.session.profile.reference_jobs[0].input_method == "manual_text"
    job = container.repository.get_current_job(container.repository.list_records()[0].id)
    assert job is not None
    assert job.source_type == JobSourceType.MANUAL_TEXT


def test_primary_add_form_preserves_input_and_offers_manual_fallback(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher(
        error=UrlIngestionError(
            "robots.txt does not permit fetching this URL",
            kind=UrlFailureKind.BLOCKED,
        )
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)

    response = client.post(
        "/add/jobs",
        data={
            "url": REFERENCE_URL,
            "positives": "Calm product team",
            "negatives": "Weekly travel",
            "learning_enabled": "true",
            "learning_scope": ["culture"],
        },
    )

    assert response.status_code == 200
    assert REFERENCE_URL in response.text
    assert "Calm product team" in response.text
    assert "Weekly travel" in response.text
    assert "Paste the advertisement text" in response.text
    assert "robots.txt does not permit fetching this URL" in response.text
    assert 'id="manual-job-input"' in response.text
    assert 'id="manual-job-input" hidden' not in response.text
    assert container.repository.list_records() == []
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert workspace.session.profile.reference_jobs == []


def test_expired_reference_is_not_archived_or_saved_as_a_reference(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    fetcher = FakeFetcher(
        error=UrlIngestionError(
            "job page returned HTTP 404",
            kind=UrlFailureKind.EXPIRED,
            http_status=404,
        )
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=FakeJobExtractor(),
        )
    )
    workspace_id = start_profile(client)

    response = client.post(
        "/matches/jobs",
        data={"url": REFERENCE_URL},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "could+not+become+a+current+verified+job" in response.headers["location"]
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert workspace.session.profile.reference_jobs == []
    assert container.repository.count_records() == 0


def test_existing_compass_requires_confirmation_before_starting_over(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=FakeExtractor(),
        )
    )
    original_id = start_profile(client)

    refused = client.post("/profile/start", follow_redirects=False)
    restarted = client.post(
        "/profile/start",
        data={
            "confirm_restart": "true",
            "answer": "I want platform engineering with hands-on development.",
        },
        follow_redirects=False,
    )

    assert refused.status_code == 303
    assert str(original_id) in refused.headers["location"]
    assert "Confirm+that+you+want+to+start+a+new+compass" in refused.headers["location"]
    assert restarted.status_code == 303
    assert restarted.headers["location"].endswith("/guided")
    replacement = container.workspaces.latest()
    original = container.workspaces.get(original_id)
    assert replacement is not None
    assert replacement.id != original_id
    assert replacement.active is True
    assert original is not None
    assert original.active is False


def test_workflow_advances_to_the_next_question_without_a_review_stop(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    service = ProfileWorkflowService(container.workspaces, extractor=FakeExtractor())
    workspace = service.start()
    first = service.answer(workspace.id, "I would enjoy platform engineering.")
    second = service.answer(first.id, "Frankfurt and hybrid work.")

    assert first.session.profile.pending_facts == []
    assert second.session.profile.pending_facts == []
    assert second.session.completed_count == 2


def test_follow_up_is_resumable_and_answered_before_the_next_section(tmp_path: Path) -> None:
    extractor = FakeExtractor(follow_up_question="Which aspect matters most?")
    container = build_container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=extractor,
        )
    )
    workspace_id = start_profile(client)
    answer_first_section(client, workspace_id)

    clarification_page = client.get(f"/profile/{workspace_id}/guided")
    assert "Which aspect matters most?" in clarification_page.text
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert (
        progress_for(workspace.session, ProfileSection.DIRECTION).status
        == SectionStatus.CLARIFICATION_PENDING
    )

    response = client.post(
        f"/profile/{workspace_id}/answer",
        data={"answer": "Building internal tools is the most important part."},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/profile/{workspace_id}/guided"
    restored = container.workspaces.get(workspace_id)
    assert restored is not None
    direction = progress_for(restored.session, ProfileSection.DIRECTION)
    assert direction.status == SectionStatus.COMPLETED
    assert direction.clarification_answer == "Building internal tools is the most important part."
    assert restored.session.profile.unresolved_questions == []
    assert extractor.calls[1][0] == ProfileSection.DIRECTION
    assert "Clarification from the user" in extractor.calls[1][1]


def test_all_skipped_sections_can_be_revisited_without_losing_the_workspace(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    service = ProfileWorkflowService(container.workspaces)
    workspace = service.start()
    for _ in range(9):
        workspace = service.skip(workspace.id)

    assert workspace.session.state.value == "ready_with_skips"

    reopened = service.revisit_skipped(workspace.id)

    assert reopened.id == workspace.id
    assert reopened.session.state.value == "active"
    assert all(item.status == SectionStatus.PENDING for item in reopened.session.sections)
    assert container.workspaces.messages(workspace.id)[-1].section == ProfileSection.DIRECTION


def test_profile_start_page_contains_no_bundled_candidate_profile(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get("/profile")

    assert page.status_code == 200
    assert "Tell us what a good working life actually means to you" in page.text
    assert container.workspaces.latest() is None
