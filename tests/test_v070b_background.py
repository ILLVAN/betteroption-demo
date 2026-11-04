from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from betteroption.background import (
    BackgroundTaskKind,
    BackgroundTaskStatus,
    JobImportDestination,
)
from betteroption.container import ApplicationContainer
from betteroption.discovery import discovery_query_from_profile
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.settings import Settings
from betteroption.web import create_app

from test_opportunity_web import JobExtractor, SequenceFetcher, document


def _fact(
    key: str,
    value: str,
    *,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=RequirementLevel.PREFERENCE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def _settings(tmp_path: Path, name: str, **overrides: object) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        auth_mode="local",
        **overrides,
    )


def test_newest_confirmed_origin_fact_wins_over_the_legacy_typed_projection() -> None:
    profile = CandidateProfile(
        facts=[
            _fact("role.family", "embedded software"),
            _fact(
                "location.origin",
                "Davao",
                section=ProfileSection.LOCATION_MOBILITY,
            ),
        ],
        location=LocationPreference(origin_label="Leipzig Central Station"),
    )

    query = discovery_query_from_profile(profile)

    assert query.location == "Davao"
    assert query.regional_target == 30


def test_background_import_payload_is_ordered_and_separate_from_task_metadata(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "background-import.db",
            background_worker_enabled=False,
        )
    )
    workspace = container.workspaces.create()
    urls = [
        "https://careers.example.com/jobs/second",
        "https://careers.example.com/jobs/first",
        "https://careers.example.com/jobs/second",
    ]

    task = container.background_job_imports.create(
        workspace.id,
        urls,
        JobImportDestination.MATCHING,
    )
    batch = container.background_job_imports.get(task.id)

    assert task.kind == BackgroundTaskKind.JOB_IMPORT
    assert task.total_units == 2
    assert batch is not None
    assert batch.destination == JobImportDestination.MATCHING
    assert batch.source_urls == urls[:2]
    assert not set(type(task).model_fields).intersection({"source_urls", "destination", "job_text"})


def test_explore_save_queues_verification_instead_of_blocking_the_request(
    tmp_path: Path,
) -> None:
    url = "https://careers.example.com/jobs/background-import"
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "background-web.db",
            background_worker_enabled=True,
            background_worker_poll_seconds=0.05,
        )
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            document(
                url=url,
                checked_at=datetime.now(timezone.utc),
            )
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        response = client.post(
            "/explore/save",
            data={"selected_urls": url, "destination": "archive"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        task_path = urlsplit(response.headers["location"]).path
        assert task_path.startswith("/tasks/")
        task_id = task_path.rsplit("/", 1)[-1]

        deadline = monotonic() + 3
        status = None
        while monotonic() < deadline:
            status = client.get(f"/tasks/{task_id}/status").json()
            if status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)

        assert status is not None
        assert status["status"] == BackgroundTaskStatus.SUCCEEDED.value
        assert status["result_url"].startswith("/jobs?")
        assert container.repository.count_records() == 1


def test_explore_save_chains_verification_into_a_durable_matching_task(
    tmp_path: Path,
) -> None:
    url = "https://careers.example.com/jobs/background-match"
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "background-chain.db",
            background_worker_enabled=True,
            background_worker_poll_seconds=0.05,
        )
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            document(
                url=url,
                checked_at=datetime.now(timezone.utc),
            )
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        workspace = container.workspaces.latest()
        assert workspace is not None
        workspace.session.profile.facts.append(_fact("role.family", "platform engineering"))
        container.workspaces.save(workspace)
        response = client.post(
            "/explore/save",
            data={"selected_urls": url, "destination": "matching"},
            follow_redirects=False,
        )
        import_task_id = urlsplit(response.headers["location"]).path.rsplit("/", 1)[-1]

        deadline = monotonic() + 3
        import_status = None
        while monotonic() < deadline:
            import_status = client.get(f"/tasks/{import_task_id}/status").json()
            if import_status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)

        assert import_status is not None
        assert import_status["status"] == BackgroundTaskStatus.SUCCEEDED.value, import_status
        match_task_path = urlsplit(import_status["result_url"]).path
        assert match_task_path.startswith("/tasks/")
        match_task_id = match_task_path.rsplit("/", 1)[-1]
        completed_task = container.background_tasks.get(import_task_id)
        assert completed_task is not None
        assert completed_task.kind == BackgroundTaskKind.JOB_IMPORT

        # The Match path exercises the complete scoring stack. Keep the
        # polling deadline generous enough for a loaded full-suite runner;
        # this test asserts durable chaining, not a three-second SLA.
        deadline = monotonic() + 8
        match_status = None
        while monotonic() < deadline:
            match_status = client.get(f"/tasks/{match_task_id}/status").json()
            if match_status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)

        assert match_status is not None
        assert match_status["status"] == BackgroundTaskStatus.SUCCEEDED.value, match_status
        assert urlsplit(match_status["result_url"]).path == "/matches"
        match_task = container.background_tasks.get(match_task_id)
        assert match_task is not None
        assert match_task.kind == BackgroundTaskKind.MATCH_RUN
        latest_run = container.results.latest_run(workspace.id)
        assert latest_run is not None
        assert latest_run.metrics is not None
        assert latest_run.metrics.jobs_evaluated == 1


def test_import_retry_keeps_payload_and_reuses_its_match_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://careers.example.com/jobs/retry-import"
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "background-import-retry.db",
            background_worker_enabled=False,
            background_task_retry_seconds=0,
        )
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            document(url=url, checked_at=datetime.now(timezone.utc)),
            document(url=url, checked_at=datetime.now(timezone.utc)),
        ),
        job_extractor=JobExtractor(),
    )
    workspace = container.workspaces.create()
    workspace.session.profile.facts.append(_fact("role.family", "platform engineering"))
    container.workspaces.save(workspace)
    import_task = container.background_job_imports.create(
        workspace.id,
        [url],
        JobImportDestination.MATCHING,
    )
    worker = app.state.background_worker
    succeed = container.background_tasks.succeed
    calls = 0

    def fail_first_succeed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("succeed", {}, RuntimeError("temporary"))
        return succeed(*args, **kwargs)

    monkeypatch.setattr(container.background_tasks, "succeed", fail_first_succeed)

    with pytest.raises(OperationalError):
        worker.run_once()

    interrupted = container.background_tasks.get(import_task.id)
    assert interrupted is not None
    assert interrupted.status == BackgroundTaskStatus.RUNNING
    assert interrupted.lease_expires_at is not None
    assert container.background_job_imports.get(import_task.id) is not None
    first_children = [
        task
        for task in container.background_tasks.list_recent()
        if task.kind == BackgroundTaskKind.MATCH_RUN
    ]
    assert len(first_children) == 1

    recovered = container.background_tasks.recover_interrupted(
        now=interrupted.lease_expires_at + timedelta(microseconds=1)
    )
    assert recovered == 1
    assert worker.run_once() is True

    completed = container.background_tasks.get(import_task.id)
    assert completed is not None
    assert completed.status == BackgroundTaskStatus.SUCCEEDED
    assert completed.attempt == 2
    assert completed.result_url == f"/tasks/{first_children[0].id}"
    assert container.background_job_imports.get(import_task.id) is None
    assert container.repository.count_records() == 1
    assert (
        len(
            [
                task
                for task in container.background_tasks.list_recent()
                if task.kind == BackgroundTaskKind.MATCH_RUN
            ]
        )
        == 1
    )


def test_terminal_import_cleanup_retries_after_database_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://careers.example.com/jobs/cleanup-retry"
    container = ApplicationContainer(
        _settings(
            tmp_path,
            "background-cleanup-retry.db",
            background_worker_enabled=False,
        )
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(document(url=url)),
        job_extractor=JobExtractor(),
    )
    workspace = container.workspaces.create()
    task = container.background_job_imports.create(
        workspace.id,
        [url],
        JobImportDestination.ARCHIVE,
    )
    cleanup = container.background_job_imports.delete_terminal
    failures = 0

    def fail_first_terminal_cleanup() -> int:
        nonlocal failures
        current = container.background_tasks.get(task.id)
        if current is not None and current.is_terminal and failures == 0:
            failures += 1
            raise OperationalError("cleanup", {}, RuntimeError("temporary"))
        return cleanup()

    monkeypatch.setattr(
        container.background_job_imports,
        "delete_terminal",
        fail_first_terminal_cleanup,
    )
    worker = app.state.background_worker

    assert worker.run_once() is True
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.SUCCEEDED
    assert container.background_job_imports.get(task.id) is not None
    assert worker.last_loop_error == "OperationalError"

    assert worker.run_once() is False
    assert failures == 1
    assert container.background_job_imports.get(task.id) is None


def test_explore_remote_switch_is_a_current_result_filter() -> None:
    template = Path("src/betteroption/web/templates/explore.html").read_text(encoding="utf-8")
    javascript = Path("src/betteroption/web/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("src/betteroption/web/static/app.css").read_text(encoding="utf-8")

    assert "data-remote-filter" in template
    assert 'name="hide_remote_only"' not in template
    assert "This filters the current results instantly" in template
    assert "betteroption:explore:hide-remote-only" in javascript
    assert "data-provider-filter-all" in template
    assert "data-provider-filter" in template
    assert "card.dataset.sourceProviders" in javascript
    assert "selectedProviders.has(provider)" in javascript
    assert "providerFilterAll.indeterminate" in javascript
    assert "card.hidden = hidden" in javascript
    assert ".explore-card[hidden]" in stylesheet
    assert "display: none !important" in stylesheet


def test_guided_compass_keeps_topic_suggestions_for_clarifications() -> None:
    template = Path("src/betteroption/web/templates/profile_conversation.html").read_text(
        encoding="utf-8"
    )

    assert "definition.suggestions" in template
    assert "{% if not clarification_question %}" not in template
