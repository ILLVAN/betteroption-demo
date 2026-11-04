from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from betteroption.background import (
    BackgroundTaskKind,
    BackgroundTaskRepository,
    BackgroundTaskStatus,
    BackgroundWorker,
)
from betteroption.container import ApplicationContainer
from betteroption.database import Database
from betteroption.operations import ProviderBudgetPolicy, provider_operation_scope
from betteroption.settings import Settings
from betteroption.web import create_app


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v0611.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )


def test_background_task_persists_progress_and_completion(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
        max_attempts=3,
    )

    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.status == BackgroundTaskStatus.RUNNING
    assert claimed.attempt == 1
    assert claimed.claim_token is not None

    updated = container.background_tasks.update_progress(
        task.id,
        phase="routing",
        completed_units=3,
        total_units=10,
        message="Calculating commute evidence.",
        expected_attempt=claimed.attempt,
        claim_token=claimed.claim_token,
    )
    assert updated.progress_percent == 30

    finished = container.background_tasks.succeed(
        task.id,
        result_url="/matches",
        expected_attempt=claimed.attempt,
        claim_token=claimed.claim_token,
    )
    assert finished.status == BackgroundTaskStatus.SUCCEEDED
    assert finished.progress_percent == 100
    assert finished.result_url == "/matches"


def test_background_worker_retries_a_temporary_failure(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
        max_attempts=2,
    )
    calls = 0

    def handler(current, report) -> str:
        nonlocal calls
        calls += 1
        report("matching", 1, 2, "Comparing evidence.")
        if calls == 1:
            raise TimeoutError("temporary provider timeout")
        return "/matches"

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: handler},
        retry_base_seconds=0,
    )

    assert worker.run_once()
    retrying = container.background_tasks.get(task.id)
    assert retrying is not None
    assert retrying.status == BackgroundTaskStatus.RETRY_WAIT
    assert retrying.error_type == "TimeoutError"

    assert worker.run_once()
    succeeded = container.background_tasks.get(task.id)
    assert succeeded is not None
    assert succeeded.status == BackgroundTaskStatus.SUCCEEDED
    assert succeeded.attempt == 2
    assert calls == 2


def test_background_worker_stops_retrying_after_the_configured_limit(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
        max_attempts=1,
    )

    def handler(current, report) -> str:
        report("matching", 1, 2, "Comparing evidence.")
        raise TimeoutError("temporary provider timeout")

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: handler},
        retry_base_seconds=0,
    )

    assert worker.run_once()
    failed = container.background_tasks.get(task.id)
    assert failed is not None
    assert failed.status == BackgroundTaskStatus.FAILED
    assert failed.error_type == "TimeoutError"
    assert failed.finished_at is not None
    assert not worker.run_once()


def test_interrupted_background_work_returns_to_the_queue(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.lease_expires_at is not None

    assert (
        container.background_tasks.recover_interrupted(
            now=claimed.lease_expires_at + timedelta(seconds=1)
        )
        == 1
    )
    recovered = container.background_tasks.get(task.id)
    assert recovered is not None
    assert recovered.status == BackgroundTaskStatus.QUEUED
    assert recovered.phase == "recovered"


def test_per_workflow_budget_is_enforced_before_a_call_is_recorded(tmp_path: Path) -> None:
    container = _container(tmp_path)
    policy = ProviderBudgetPolicy(
        container.operations,
        action_operation_limit=2,
        action_cost_limit_usd=0.03,
    )

    with provider_operation_scope(uuid4(), "match-run"):
        assert policy.allows(proposed_cost_usd=0.01)
        assert policy.allows(proposed_cost_usd=0.01)
        assert not policy.allows(proposed_cost_usd=0.01)


def test_task_schema_has_no_candidate_or_provider_payload_fields() -> None:
    from betteroption.background import BackgroundTask

    fields = set(BackgroundTask.model_fields)
    assert not fields.intersection(
        {"query", "url", "prompt", "response", "job_text", "cv_text", "api_key"}
    )


def test_task_status_is_visible_only_for_the_active_workspace(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get(f"/tasks/{task.id}")
    status = client.get(f"/tasks/{task.id}/status")

    assert page.status_code == 200
    assert "Building your evidence-backed matches" in page.text
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["progress_percent"] == 0
    assert status.json()["worker_running"] is False
    assert status.json()["updated_at"]


def test_returning_to_matching_resumes_the_same_active_task(tmp_path: Path) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'resume.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=True,
            background_worker_poll_seconds=0.05,
        )
    )
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
        max_attempts=2,
    )
    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.claim_token is not None
    container.background_tasks.retry_or_fail(
        task.id,
        error_type="TemporaryProviderError",
        public_message="Temporary provider problem.",
        retry_delay_seconds=3_600,
        expected_attempt=claimed.attempt,
        claim_token=claimed.claim_token,
    )
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        first_return = client.get("/matches", follow_redirects=False)
        duplicate_start = client.post("/matches/run", follow_redirects=False)
        progress = client.get(first_return.headers["location"])
        status = client.get(f"/tasks/{task.id}/status")

    expected_location = f"/tasks/{task.id}"
    assert first_return.status_code == 303
    assert first_return.headers["location"] == expected_location
    assert duplicate_start.status_code == 303
    assert duplicate_start.headers["location"] == expected_location
    assert progress.status_code == 200
    assert "Returning to Match resumes this progress view." in progress.text
    assert status.json()["status"] == "retry_wait"
    assert status.json()["worker_running"] is True
    assert len(container.background_tasks.list_recent()) == 1


def test_completed_task_redirects_without_waiting_for_javascript(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.claim_token is not None
    container.background_tasks.succeed(
        task.id,
        result_url="/matches?notice=Recovered",
        expected_attempt=claimed.attempt,
        claim_token=claimed.claim_token,
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    response = client.get(f"/tasks/{task.id}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/matches?notice=Recovered"


def test_background_repository_accepts_a_standalone_database(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'repository.db').as_posix()}")
    repository = BackgroundTaskRepository(database)

    assert repository.list_recent() == []
    assert datetime.now(timezone.utc).tzinfo is not None
