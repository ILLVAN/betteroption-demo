from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.cv import canonical_cv_preview_text, sanitize_cv_text
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.openai_diagnostics import check_openai_model_access
from betteroption.profile import ProfileSection
from betteroption.profile_workflow import ProfileWorkflowError, ProfileWorkflowService
from betteroption.provider_registry import ProviderRegistry
from betteroption.providers.openai import ProfileExtractionError
from betteroption.settings import Settings
from betteroption.web import create_app


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'resilience.db').as_posix()}",
        "auth_mode": "local",
        "background_worker_enabled": False,
        "employer_homepage_research": False,
        "openai_api_key": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _start_workspace(client: TestClient) -> str:
    response = client.post("/profile/start", follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].rsplit("/", 1)[-1]


class InvalidKeyExtractor:
    def __init__(self, leaked_value: str = "") -> None:
        self.leaked_value = leaked_value
        self.calls: list[tuple[ProfileSection, str]] = []

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        self.calls.append((section, user_text))
        raise ProfileExtractionError(
            f"OpenAI rejected the API key. Internal value: {self.leaked_value}"
        )


class CvExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[ProfileSection, str]] = []

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        self.calls.append((section, user_text))
        return SectionExtraction(
            summary="Review the extracted CV evidence.",
            facts=[
                ExtractedFactDraft(
                    key="skill.demonstrated",
                    value="Python",
                    level="open",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="Python",
                )
            ],
            follow_up_question=None,
        )


def test_missing_openai_key_saves_direct_compass_addition_instead_of_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    container = ApplicationContainer(_settings(tmp_path))
    client = TestClient(
        create_app(container, data_directory=tmp_path / "data"),
        raise_server_exceptions=False,
    )
    workspace_id = _start_workspace(client)

    response = client.post(
        f"/profile/{workspace_id}/sections/direction/detail",
        data={"answer": "I want hands-on platform engineering."},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "saved+locally" in response.headers["location"]
    assert "OPENAI_API_KEY" in response.headers["location"]
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert (
        workspace.session.profile.raw_sections[ProfileSection.DIRECTION]
        == "I want hands-on platform engineering."
    )
    assert any(
        fact.value == "I want hands-on platform engineering."
        for fact in workspace.session.profile.confirmed_facts
    )


def test_invalid_key_guided_answer_is_saved_and_error_never_echoes_secret(
    tmp_path: Path,
) -> None:
    leaked_value = "sk-test-do-not-render"
    extractor = InvalidKeyExtractor(leaked_value)
    container = ApplicationContainer(_settings(tmp_path))
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=extractor,
        )
    )
    workspace_id = _start_workspace(client)

    response = client.post(
        f"/profile/{workspace_id}/answer",
        data={"answer": "I prefer embedded test automation."},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "OpenAI+authentication+failed" in response.headers["location"]
    assert leaked_value not in response.headers["location"]
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert workspace.session.completed_count == 1
    assert any(
        fact.value == "I prefer embedded test automation."
        for fact in workspace.session.profile.confirmed_facts
    )
    assert extractor.calls == [(ProfileSection.DIRECTION, "I prefer embedded test automation.")]


def test_local_checkpoint_failure_prevents_provider_call_and_returns_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = CvExtractor()
    container = ApplicationContainer(_settings(tmp_path))
    service = ProfileWorkflowService(container.workspaces, extractor=extractor)
    workspace = service.start()
    leaked_value = "database-password-do-not-render"

    def fail_save(_workspace):
        raise RuntimeError(f"database failed with {leaked_value}")

    monkeypatch.setattr(container.workspaces, "save", fail_save)

    with pytest.raises(ProfileWorkflowError) as failure:
        service.answer(workspace.id, "I want platform engineering.")

    assert "no AI request was made" in str(failure.value)
    assert leaked_value not in str(failure.value)
    assert extractor.calls == []
    assert container.workspaces.messages(workspace.id)[-1].content == (
        "I want platform engineering."
    )


def test_settings_load_openai_key_from_dotenv_and_process_environment_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=from-file-secret\nOPENAI_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "from-process-secret")
    settings = Settings(
        _env_file=env_path,
        database_url=f"sqlite:///{(tmp_path / 'settings.db').as_posix()}",
    )
    registry = ProviderRegistry()
    registry.register_profile(
        "openai",
        lambda *, route, recorder, api_key=None: SimpleNamespace(
            route=route,
            recorder=recorder,
            received_key=api_key,
        ),
    )

    extractor = ApplicationContainer(settings, registry=registry).profile_extractor()

    assert settings.openai_api_key_value == "from-process-secret"
    assert extractor.received_key == "from-process-secret"
    assert "from-process-secret" not in repr(settings.openai_api_key)


def test_cv_preview_crlf_second_confirmation_reaches_provider_once(tmp_path: Path) -> None:
    extractor = CvExtractor()
    container = ApplicationContainer(_settings(tmp_path))
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=extractor,
        )
    )
    workspace_id = _start_workspace(client)
    first_text = (
        "[removed likely name]\r\n"
        "Artist Web: corecut.net\r\n"
        "Embedded engineer using Python for test automation."
    )
    consent = {
        "cv_ai_consent": "true",
        "confirm_no_sensitive_data": "true",
    }

    first = client.post(
        f"/profile/{workspace_id}/cv/confirm",
        data={"selected_text": first_text, **consent},
        follow_redirects=False,
    )
    assert first.status_code == 200
    assert "Additional identifiers were removed" in first.text
    assert "corecut.net" not in first.text
    assert extractor.calls == []

    sanitized = sanitize_cv_text(first_text)
    second = client.post(
        f"/profile/{workspace_id}/cv/confirm",
        data={"selected_text": sanitized.text.replace("\n", "\r\n"), **consent},
        follow_redirects=False,
    )

    assert second.status_code == 303
    assert f"/profile/{workspace_id}/review" in second.headers["location"]
    assert extractor.calls == [(ProfileSection.EXPERIENCE, sanitized.text)]
    assert sanitized.text == canonical_cv_preview_text(sanitized.text.replace("\n", "\r\n"))


def test_labeled_bare_personal_url_is_removed_but_socket_io_is_kept() -> None:
    result = sanitize_cv_text(
        "Email: [removed email address] | Web: [removed personal URL] | "
        "Artist Web: corecut.net\n"
        "Built realtime Python services with socket.io integrations."
    )

    assert "corecut.net" not in result.text
    assert "socket.io" in result.text
    assert result.redactions == ["personal URL"]


def test_manual_openai_diagnostic_sends_no_user_text_and_never_returns_key(
    tmp_path: Path,
) -> None:
    key = "sk-diagnostic-do-not-render"
    calls: list[str] = []
    client = SimpleNamespace(
        models=SimpleNamespace(retrieve=lambda model: calls.append(model)),
    )
    settings = _settings(
        tmp_path,
        openai_api_key=key,
        profile_extraction_model="profile-access-model",
    )

    result = check_openai_model_access(settings, client=client)

    assert result.success is True
    assert calls == ["profile-access-model"]
    assert key not in result.message
    assert "No Compass or CV text was sent" in result.message
