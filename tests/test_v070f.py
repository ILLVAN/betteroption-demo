from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from betteroption.background import (
    BackgroundTaskStatus,
    JobImportDestination,
)
from betteroption.container import ApplicationContainer
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.settings import Settings
from betteroption.url_ingestion import UrlFailureKind, UrlIngestionError
from betteroption.web import create_app

from test_opportunity_web import JobExtractor, SequenceFetcher, document


def _settings(tmp_path: Path, name: str, **overrides: object) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        auth_mode="local",
        **overrides,
    )


def _wait_for_terminal_task(client: TestClient, task_id: str) -> dict:
    deadline = monotonic() + 4
    status: dict = {}
    while monotonic() < deadline:
        status = client.get(f"/tasks/{task_id}/status").json()
        if status["status"] in {"succeeded", "failed"}:
            return status
        sleep(0.02)
    raise AssertionError(f"background task {task_id} did not finish: {status}")


def _add_matching_fact(container: ApplicationContainer) -> None:
    workspace = container.workspaces.latest()
    assert workspace is not None
    workspace.session.profile.facts.append(
        ProfileFact(
            key="role.family",
            value="platform engineering",
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.DIRECTION,
                text="platform engineering",
            ),
        )
    )
    container.workspaces.save(workspace)


def test_matching_rediscovers_an_active_explore_import_after_navigation(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "visible-import.db",
            background_worker_enabled=False,
        )
    )
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        workspace = container.workspaces.latest()
        assert workspace is not None
        task = container.background_job_imports.create(
            workspace.id,
            ["https://careers.example.com/jobs/visible-import"],
            JobImportDestination.MATCHING,
        )

        response = client.get("/matches", follow_redirects=False)
        progress = client.get(f"/tasks/{task.id}")

    assert response.status_code == 303
    assert response.headers["location"] == f"/tasks/{task.id}"
    assert "Returning to Match resumes this progress view." in progress.text
    assert "Return to Matching" in progress.text


def test_archive_import_is_not_presented_as_an_active_matching_pipeline(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "archive-import.db",
            background_worker_enabled=False,
        )
    )
    workspace = container.workspaces.create()
    container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/archive-only"],
        JobImportDestination.ARCHIVE,
    )

    assert (
        container.background_job_imports.find_active(
            workspace.id,
            JobImportDestination.MATCHING,
        )
        is None
    )


def test_rejected_403_source_does_not_poison_the_next_save_and_match(
    tmp_path: Path,
) -> None:
    blocked_url = "https://careers.example.com/jobs/blocked"
    valid_url = "https://careers.example.com/jobs/valid"
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "recoverable-import.db",
            background_worker_enabled=True,
            background_worker_poll_seconds=0.05,
        )
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            UrlIngestionError(
                "job page returned HTTP 403",
                kind=UrlFailureKind.BLOCKED,
                http_status=403,
            ),
            *[document(url=valid_url) for _ in range(30)],
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        _add_matching_fact(container)

        rejected = client.post(
            "/explore/save",
            data={"selected_urls": blocked_url, "destination": "matching"},
            follow_redirects=False,
        )
        rejected_id = urlsplit(rejected.headers["location"]).path.rsplit("/", 1)[-1]
        rejected_status = _wait_for_terminal_task(client, rejected_id)

        assert rejected_status["status"] == BackgroundTaskStatus.SUCCEEDED.value
        manual_recovery = urlsplit(rejected_status["result_url"])
        assert manual_recovery.path == "/add"
        assert "url=https%3A%2F%2Fcareers.example.com%2Fjobs%2Fblocked" in (manual_recovery.query)
        assert "manual=true" in manual_recovery.query
        assert manual_recovery.fragment == "manual-job-input"
        assert container.repository.count_records() == 0

        accepted = client.post(
            "/explore/save",
            data={"selected_urls": valid_url, "destination": "matching"},
            follow_redirects=False,
        )
        accepted_id = urlsplit(accepted.headers["location"]).path.rsplit("/", 1)[-1]
        accepted_status = _wait_for_terminal_task(client, accepted_id)

        assert accepted.status_code == 303
        assert accepted_id != rejected_id
        assert accepted_status["status"] == BackgroundTaskStatus.SUCCEEDED.value
        match_path = urlsplit(accepted_status["result_url"]).path
        assert match_path.startswith("/tasks/")
        match_id = match_path.rsplit("/", 1)[-1]
        match_status = _wait_for_terminal_task(client, match_id)
        assert match_status["status"] == BackgroundTaskStatus.SUCCEEDED.value, (
            match_status["error_message"],
            match_status,
        )
        assert match_status["result_url"].startswith("/matches?")
        assert container.repository.count_records() == 1


def test_pageshow_resets_busy_form_submission_state() -> None:
    script = Path("src/betteroption/web/static/app.js").read_text(encoding="utf-8")

    assert 'window.addEventListener("pageshow", resetBusyState)' in script
    assert "delete form.dataset.submitting" in script
    assert 'form.dispatchEvent(new Event("selection:refresh"))' in script
