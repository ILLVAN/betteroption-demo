from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from betteroption.background import (
    BackgroundTaskRepository,
    BackgroundTaskKind,
    BackgroundTaskRow,
    BackgroundTaskStatus,
    BackgroundWorker,
    JobImportDestination,
)
from betteroption.container import ApplicationContainer
from betteroption.settings import Settings
from betteroption.web import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _container(tmp_path: Path, name: str, **overrides: object) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            **overrides,
        )
    )


class NeverCalledDiscovery:
    name = "never-called"
    attribution = "Never called"
    attribution_url = "https://example.com"

    def __init__(self) -> None:
        self.called = False

    def search(self, _query):
        self.called = True
        raise AssertionError("external-worker web request used the synchronous fallback")


def test_settings_reject_two_worker_modes_but_allow_sync_mode() -> None:
    with pytest.raises(ValidationError, match="cannot both be true"):
        Settings(
            _env_file=None,
            background_worker_enabled=True,
            background_worker_external=True,
        )
    settings = Settings(
        _env_file=None,
        background_worker_enabled=False,
        background_worker_external=False,
    )
    assert settings.background_worker_enabled is False
    assert settings.background_worker_external is False


def test_recovery_preserves_fresh_lease_and_recovers_expired_or_legacy_claims(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "lease-recovery.db")
    workspace = container.workspaces.create()
    anchor = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    fresh_task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    fresh_claim = container.background_tasks.claim_next(
        claim_owner="worker-a",
        lease_ttl_seconds=30,
        now=anchor,
    )
    assert fresh_claim is not None
    assert fresh_claim.id == fresh_task.id
    assert fresh_claim.claim_token is not None
    assert fresh_claim.claim_owner == "worker-a"
    assert fresh_claim.heartbeat_at == anchor
    assert fresh_claim.lease_expires_at == anchor + timedelta(seconds=30)

    assert container.background_tasks.recover_interrupted(now=anchor + timedelta(seconds=29)) == 0
    assert container.background_tasks.get(fresh_task.id).status == BackgroundTaskStatus.RUNNING

    assert container.background_tasks.recover_interrupted(now=anchor + timedelta(seconds=31)) == 1
    assert container.background_tasks.get(fresh_task.id).status == BackgroundTaskStatus.QUEUED
    container.background_tasks.request_cancel(fresh_task.id)

    legacy_task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    legacy_claim = container.background_tasks.claim_next(now=anchor + timedelta(minutes=1))
    assert legacy_claim is not None
    assert legacy_claim.id == legacy_task.id
    with container.database.session_factory.begin() as session:
        row = session.get(BackgroundTaskRow, str(legacy_task.id))
        assert row is not None
        row.lease_expires_at = None
    assert container.background_tasks.recover_interrupted(now=anchor) == 1
    assert container.background_tasks.get(legacy_task.id).status == BackgroundTaskStatus.QUEUED


def test_recovery_locks_expired_claims_before_requeueing() -> None:
    statement = BackgroundTaskRepository._recoverable_claims(
        datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in sql


def test_stale_transition_rechecks_token_after_waiting_for_session_row_lock() -> None:
    task_id = uuid4()
    workspace_id = uuid4()
    first_token = uuid4()
    replacement_token = uuid4()
    now = datetime.now(timezone.utc)
    row = BackgroundTaskRow(
        id=str(task_id),
        workspace_id=str(workspace_id),
        kind=BackgroundTaskKind.MATCH_RUN.value,
        status=BackgroundTaskStatus.RUNNING.value,
        phase="running",
        message="Running.",
        completed_units=0,
        total_units=1,
        attempt=1,
        max_attempts=2,
        claim_token=str(first_token),
        claim_owner="old-worker",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=30),
        created_at=now,
        updated_at=now,
    )
    row_lock = Lock()
    row_lock.acquire()
    get_started = Event()
    flushed = False

    class LockedSession:
        def get(self, model, key, *, with_for_update=False):
            assert model is BackgroundTaskRow
            assert key == str(task_id)
            assert with_for_update is True
            get_started.set()
            row_lock.acquire()
            row_lock.release()
            return row

        def flush(self) -> None:
            nonlocal flushed
            flushed = True

    class Transaction:
        def __enter__(self):
            return LockedSession()

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    class SessionFactory:
        @staticmethod
        def begin():
            return Transaction()

    repository = BackgroundTaskRepository(
        SimpleNamespace(session_factory=SessionFactory())  # type: ignore[arg-type]
    )
    outcome: dict[str, object] = {}

    def finish_stale_attempt() -> None:
        try:
            outcome["task"] = repository.succeed(
                task_id,
                result_url="/stale-result",
                expected_attempt=1,
                claim_token=first_token,
            )
        except Exception as exc:  # pragma: no cover - makes thread failures visible
            outcome["error"] = exc

    stale_thread = Thread(target=finish_stale_attempt)
    stale_thread.start()
    assert get_started.wait(timeout=1)

    # Model the transaction holding the row lock recovering and claiming the
    # expired task before the stale attempt gets to inspect the row.
    row.attempt = 2
    row.claim_token = str(replacement_token)
    row.claim_owner = "replacement-worker"
    row_lock.release()
    stale_thread.join(timeout=1)

    assert not stale_thread.is_alive()
    assert "error" not in outcome
    current = outcome["task"]
    assert current.status == BackgroundTaskStatus.RUNNING
    assert current.claim_token == replacement_token
    assert current.result_url is None
    assert flushed is False


def test_stale_claim_token_cannot_finish_current_attempt(tmp_path: Path) -> None:
    container = _container(tmp_path, "token-fence.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    claim = container.background_tasks.claim_next(claim_owner="worker-a")
    assert claim is not None
    assert claim.claim_token is not None

    stale = container.background_tasks.succeed(
        task.id,
        result_url="/stale",
        expected_attempt=claim.attempt,
        claim_token=uuid4(),
    )
    assert stale.status == BackgroundTaskStatus.RUNNING
    assert stale.result_url is None

    current = container.background_tasks.succeed(
        task.id,
        result_url="/matches",
        expected_attempt=claim.attempt,
        claim_token=claim.claim_token,
    )
    assert current.status == BackgroundTaskStatus.SUCCEEDED


def test_queued_and_retry_wait_cancellation_is_terminal_idempotent_and_unclaimable(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "cancel-waiting.db")
    workspace = container.workspaces.create()
    queued = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)

    first = container.background_tasks.request_cancel(queued.id)
    second = container.background_tasks.request_cancel(queued.id)
    assert first.status == BackgroundTaskStatus.CANCELLED
    assert first.cancel_requested_at is not None
    assert first.cancelled_at is not None
    assert second.cancel_requested_at == first.cancel_requested_at
    assert second.cancelled_at == first.cancelled_at
    assert container.background_tasks.claim_next() is None

    retrying = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.EXPLORE_SEARCH,
        max_attempts=2,
    )
    retry_claim = container.background_tasks.claim_next()
    assert retry_claim is not None
    assert retry_claim.claim_token is not None
    container.background_tasks.retry_or_fail(
        retrying.id,
        error_type="TimeoutError",
        public_message="Temporary failure.",
        retry_delay_seconds=0,
        expected_attempt=retry_claim.attempt,
        claim_token=retry_claim.claim_token,
    )
    cancelled_retry = container.background_tasks.request_cancel(retrying.id)
    assert cancelled_retry.status == BackgroundTaskStatus.CANCELLED
    assert container.background_tasks.claim_next() is None


def test_running_cancellation_is_terminal_while_late_handler_output_is_fenced(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "cancel-running.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    provider_started = Event()
    provider_release = Event()

    def handler(_task, report) -> str:
        provider_started.set()
        provider_release.wait(timeout=3)
        report("after_provider", 1, 2, "Provider call returned.")
        return "/matches"

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: handler},
        poll_interval_seconds=0.05,
        lease_ttl_seconds=0.2,
        heartbeat_interval_seconds=0.05,
    )
    worker.start()
    assert provider_started.wait(timeout=2)

    cancelling = container.background_tasks.request_cancel(task.id)
    assert cancelling.status == BackgroundTaskStatus.CANCELLED
    assert cancelling.phase == "cancelled"
    assert cancelling.cancel_requested_at is not None
    assert cancelling.cancelled_at is not None
    assert cancelling.claim_token is None

    sleep(0.35)
    assert container.background_tasks.recover_interrupted() == 0
    still_cancelling = container.background_tasks.get(task.id)
    assert still_cancelling is not None
    assert still_cancelling.status == BackgroundTaskStatus.CANCELLED
    assert still_cancelling.phase == "cancelled"

    provider_release.set()
    deadline = monotonic() + 2
    final = cancelling
    while monotonic() < deadline:
        final = container.background_tasks.get(task.id)
        if final is not None and final.is_terminal:
            break
        sleep(0.02)
    worker.stop()

    assert final is not None
    assert final.status == BackgroundTaskStatus.CANCELLED
    assert final.cancelled_at is not None
    assert final.result_url is None


def test_cancel_route_is_scoped_idempotent_and_exposes_cancelled_payload_and_ui(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "cancel-web.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        page = client.get(f"/tasks/{task.id}")
        initial = client.get(f"/tasks/{task.id}/status").json()
        cancelled = client.post(f"/tasks/{task.id}/cancel", follow_redirects=False)
        repeated = client.post(f"/tasks/{task.id}/cancel", follow_redirects=False)
        payload = client.get(f"/tasks/{task.id}/status").json()
        cancelled_page = client.get(f"/tasks/{task.id}")

    assert page.status_code == 200
    assert "Abort task" in page.text
    assert initial["progress_indeterminate"] is True
    assert initial["cancel_requested_at"] is None
    assert cancelled.status_code == 303
    assert repeated.status_code == 303
    assert payload["status"] == "cancelled"
    assert payload["cancellable"] is False
    assert payload["cancel_requested_at"]
    assert payload["cancelled_at"]
    assert "Cancelled" in cancelled_page.text
    assert container.background_tasks.claim_next() is None


def test_queued_import_cancel_route_deletes_private_payload(tmp_path: Path) -> None:
    container = _container(tmp_path, "cancel-import-web.db")
    workspace = container.workspaces.create()
    task = container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/cancel-me"],
        JobImportDestination.ARCHIVE,
    )

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        cancelled = client.post(f"/tasks/{task.id}/cancel", follow_redirects=False)

    assert cancelled.status_code == 303
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.CANCELLED
    assert container.background_job_imports.get(task.id) is None


def test_terminal_import_payload_cleanup_keeps_only_retryable_batch(tmp_path: Path) -> None:
    container = _container(tmp_path, "terminal-import-cleanup.db")
    workspace = container.workspaces.create()

    succeeded = container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/succeeded"],
        JobImportDestination.ARCHIVE,
    )
    success_claim = container.background_tasks.claim_next()
    assert success_claim is not None and success_claim.claim_token is not None
    container.background_tasks.succeed(
        succeeded.id,
        result_url="/jobs",
        expected_attempt=success_claim.attempt,
        claim_token=success_claim.claim_token,
    )

    cancelled = container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/cancelled"],
        JobImportDestination.ARCHIVE,
    )
    container.background_tasks.request_cancel(cancelled.id)

    failed = container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/failed"],
        JobImportDestination.ARCHIVE,
        max_attempts=1,
    )
    failed_claim = container.background_tasks.claim_next()
    assert failed_claim is not None and failed_claim.claim_token is not None
    container.background_tasks.retry_or_fail(
        failed.id,
        error_type="PermanentError",
        public_message="No more retries.",
        retry_delay_seconds=0,
        expected_attempt=failed_claim.attempt,
        claim_token=failed_claim.claim_token,
    )

    retrying = container.background_job_imports.create(
        workspace.id,
        ["https://careers.example.com/jobs/retrying"],
        JobImportDestination.ARCHIVE,
        max_attempts=2,
    )
    retry_claim = container.background_tasks.claim_next()
    assert retry_claim is not None and retry_claim.claim_token is not None
    container.background_tasks.retry_or_fail(
        retrying.id,
        error_type="TemporaryError",
        public_message="Retry later.",
        retry_delay_seconds=60,
        expected_attempt=retry_claim.attempt,
        claim_token=retry_claim.claim_token,
    )

    assert container.background_job_imports.delete_terminal() == 3
    assert container.background_job_imports.get(succeeded.id) is None
    assert container.background_job_imports.get(cancelled.id) is None
    assert container.background_job_imports.get(failed.id) is None
    assert container.background_job_imports.get(retrying.id) is not None


def test_cancel_route_cannot_cross_active_persona_workspace(tmp_path: Path) -> None:
    container = _container(tmp_path, "cancel-scope.db")
    original_workspace = container.workspaces.create()
    task = container.background_tasks.create(
        original_workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    container.workspaces.create()

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        response = client.post(f"/tasks/{task.id}/cancel", follow_redirects=False)

    assert response.status_code == 404
    unchanged = container.background_tasks.get(task.id)
    assert unchanged is not None
    assert unchanged.status == BackgroundTaskStatus.QUEUED
    assert unchanged.cancel_requested_at is None


def test_cancel_route_is_account_and_persona_owned_and_switch_does_not_cancel(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'cancel-account-scope.db').as_posix()}",
            app_environment="local",
            auth_mode="accounts",
            registration_mode="open",
            background_worker_enabled=False,
        )
    )
    app = create_app(container, data_directory=tmp_path / "account-data")
    registration = {
        "display_name": "Owner",
        "password": "correct horse battery staple",
        "accept_terms": "yes",
        "acknowledge_privacy": "yes",
        "confirm_adult": "yes",
    }

    with TestClient(app) as owner_client, TestClient(app) as other_client:
        assert (
            owner_client.post(
                "/register",
                data={"email": "owner@example.com", **registration},
                follow_redirects=False,
            ).status_code
            == 303
        )
        owner = container.accounts.list_accounts()[0]
        main_persona = container.personas.list_for_account(owner.id)[0]
        owner_client.post("/profile/start", follow_redirects=False)
        workspace = container.workspaces.latest(
            account_id=owner.id,
            persona_id=main_persona.id,
        )
        assert workspace is not None
        task = container.background_tasks.create(
            workspace.id,
            BackgroundTaskKind.MATCH_RUN,
        )

        assert (
            owner_client.post(
                "/personas",
                data={"display_name": "Second persona"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        refused_persona = owner_client.post(
            f"/tasks/{task.id}/cancel",
            follow_redirects=False,
        )
        assert refused_persona.status_code == 404
        assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.QUEUED

        assert (
            other_client.post(
                "/register",
                data={"email": "other@example.com", **registration, "display_name": "Other"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        refused_account = other_client.post(
            f"/tasks/{task.id}/cancel",
            follow_redirects=False,
        )
        assert refused_account.status_code == 404

        owner_client.post(
            f"/personas/{main_persona.id}/switch",
            follow_redirects=False,
        )
        accepted = owner_client.post(
            f"/tasks/{task.id}/cancel",
            follow_redirects=False,
        )

    assert accepted.status_code == 303
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.CANCELLED


def test_external_mode_queues_without_sync_fallback_and_reports_worker_available(
    tmp_path: Path,
) -> None:
    discovery = NeverCalledDiscovery()
    container = _container(
        tmp_path,
        "external-web.db",
        background_worker_external=True,
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        discovery_provider=discovery,
    )

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        response = client.post(
            "/explore/search",
            data={"q": "embedded engineer"},
            follow_redirects=False,
        )
        task_path = urlsplit(response.headers["location"]).path
        payload = client.get(f"{task_path}/status").json()

    assert response.status_code == 303
    assert task_path.startswith("/tasks/")
    assert discovery.called is False
    assert payload["status"] == "queued"
    assert payload["worker_running"] is True
    assert app.state.background_worker.is_running is False


def test_web_restart_does_not_recover_fresh_external_worker_lease(tmp_path: Path) -> None:
    container = _container(
        tmp_path,
        "external-restart.db",
        background_worker_external=True,
    )
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    claim = container.background_tasks.claim_next(
        claim_owner="standalone-worker",
        lease_ttl_seconds=60,
    )
    assert claim is not None

    for _restart in range(2):
        app = create_app(container, data_directory=tmp_path / "data")
        with TestClient(app) as client:
            payload = client.get(f"/tasks/{task.id}/status").json()
            assert payload["status"] == "running"
            assert payload["worker_running"] is True

    preserved = container.background_tasks.get(task.id)
    assert preserved is not None
    assert preserved.status == BackgroundTaskStatus.RUNNING
    assert preserved.claim_token == claim.claim_token
    assert preserved.claim_owner == "standalone-worker"


def test_expired_external_lease_reports_recovery_instead_of_running(tmp_path: Path) -> None:
    container = _container(
        tmp_path,
        "external-expired.db",
        background_worker_external=True,
    )
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    claim = container.background_tasks.claim_next(
        claim_owner="dead-worker",
        lease_ttl_seconds=1,
        now=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert claim is not None

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        payload = client.get(f"/tasks/{task.id}/status").json()
        page = client.get(f"/tasks/{task.id}")

    assert payload["status"] == "running"
    assert payload["lease_fresh"] is False
    assert payload["worker_running"] is False
    assert "The worker lease expired." in page.text
    assert "waiting for a worker to recover it safely" in page.text


def test_external_worker_topology_cli_migration_and_progress_source_are_explicit() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    migrate_section = compose.split("\n  migrate:", 1)[1].split("\n  app:", 1)[0]
    app_section = compose.split("\n  app:", 1)[1].split("\n  worker:", 1)[0]
    worker_section = compose.split("\n  worker:", 1)[1].split("\n  retention:", 1)[0]
    worker_module = (PROJECT_ROOT / "src/betteroption/worker.py").read_text(encoding="utf-8")
    migration = (
        PROJECT_ROOT / "src/betteroption/migrations/versions/0033_background_task_leases.py"
    ).read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "src/betteroption/web/static/app.js").read_text(encoding="utf-8")

    assert 'BETTEROPTION_BACKGROUND_WORKER_ENABLED: "false"' in app_section
    assert 'BETTEROPTION_BACKGROUND_WORKER_EXTERNAL: "true"' in app_section
    assert 'BETTEROPTION_RUN_STARTUP_MIGRATIONS: "false"' in app_section
    assert 'command: ["-m", "betteroption.deployment", "migrate"]' in migrate_section
    assert "condition: service_completed_successfully" in app_section
    assert 'command: ["-m", "betteroption.worker"]' in worker_section
    assert "condition: service_completed_successfully" in worker_section
    assert "\n    ports:" not in worker_section
    assert "\n    expose:" not in worker_section
    assert "app.state.background_worker" in worker_module
    assert "signal.SIGTERM" in worker_module
    assert 'revision = "0033_background_task_leases"' in migration
    assert 'down_revision = "0032_explore_import_origin"' in migration
    assert "apparentExploreProgress" not in javascript
    assert "progressStartedAt" not in javascript
    assert "EXPLORE_PROGRESS_CEILING = 94" in javascript
    assert "progressBar.value = displayProgress.percent" in javascript
