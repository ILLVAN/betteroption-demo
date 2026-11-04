from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from sqlalchemy.exc import OperationalError

from betteroption.background import (
    BackgroundTaskKind,
    BackgroundTaskStatus,
    BackgroundWorker,
    JobImportDestination,
)
from betteroption.container import ApplicationContainer
from betteroption.settings import Settings


def _container(tmp_path: Path, name: str) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )


def _waiting_phrases(javascript: str, constant: str) -> list[str]:
    match = re.search(
        rf"const {constant} = \[(.*?)\n  \];",
        javascript,
        flags=re.DOTALL,
    )
    assert match is not None
    return re.findall(r'^\s+"([^"\\]*(?:\\.[^"\\]*)*)",$', match.group(1), re.MULTILINE)


def test_waiting_copy_is_large_local_varied_and_randomly_timed() -> None:
    javascript = Path("src/betteroption/web/static/task_progress.js").read_text(encoding="utf-8")
    common = _waiting_phrases(javascript, "COMMON_WAITING_COPY")
    explore = _waiting_phrases(javascript, "EXPLORE_WAITING_COPY")
    match = _waiting_phrases(javascript, "MATCH_WAITING_COPY")
    all_phrases = common + explore + match

    assert len(all_phrases) >= 130
    assert len(set(all_phrases)) == len(all_phrases)
    assert len(explore) >= 40
    assert len(match) >= 40
    assert len(common) + len(explore) >= 130
    assert len(common) + len(match) >= 130
    assert sum("{location}" in phrase for phrase in explore) >= 8
    assert "24000 + Math.floor(randomUnit() * 60001)" in javascript
    assert "setTimeout" in javascript
    assert "fetch(" not in javascript
    assert "MutationObserver(syncTechnicalStatus)" in javascript
    assert '.replaceAll("{location}", location)' in javascript
    assert "Nothing else needs clicking right now." not in all_phrases
    assert "Your task survived the page load just fine." not in all_phrases
    assert "The result will open automatically when ready." not in all_phrases
    assert "We will bring you back when the useful part is ready." not in all_phrases
    assert "The next useful click belongs to a later minute." not in all_phrases
    assert "Results will be waiting when the task finishes." in all_phrases
    assert "Come back whenever you like and the result will wait here." in all_phrases
    assert "Meanwhile, the rest of the app is still yours to explore." in all_phrases
    assert all(";" not in phrase for phrase in all_phrases)
    assert all(". " not in phrase for phrase in all_phrases)
    assert all("thorough" not in phrase.casefold() for phrase in all_phrases)


def test_progress_template_separates_friendly_and_technical_copy() -> None:
    template = Path("src/betteroption/web/templates/task_progress.html").read_text(encoding="utf-8")

    assert "data-task-waiting-message" in template
    assert "data-task-technical-status" in template
    assert "<span data-task-message>{{ task.message }}</span>" in template
    assert 'aria-atomic="true"\n        hidden' in template
    assert "data-task-location=" in template
    assert "task_progress.js" in template


def test_concurrent_tabs_get_one_active_task(tmp_path: Path) -> None:
    container = _container(tmp_path, "active-task.db")
    workspace = container.workspaces.create()

    def create_task(_position: int):
        return container.background_tasks.get_or_create_active(
            workspace.id,
            BackgroundTaskKind.EXPLORE_SEARCH,
            max_attempts=2,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(create_task, range(16)))

    assert len({task.id for task, _created in outcomes}) == 1
    assert sum(created for _task, created in outcomes) == 1
    assert len(container.background_tasks.list_recent()) == 1


def test_identical_import_submissions_reuse_active_work(tmp_path: Path) -> None:
    container = _container(tmp_path, "active-import.db")
    workspace = container.workspaces.create()
    urls = [
        "https://careers.example/jobs/one",
        "https://careers.example/jobs/two",
    ]

    first, first_created = container.background_job_imports.get_or_create_active(
        workspace.id,
        urls,
        JobImportDestination.MATCHING,
    )
    second, second_created = container.background_job_imports.get_or_create_active(
        workspace.id,
        urls,
        JobImportDestination.MATCHING,
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert len(container.background_tasks.list_recent()) == 1


def test_shutdown_waits_for_handler_unwind_before_requeue(tmp_path: Path) -> None:
    container = _container(tmp_path, "shutdown.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
        max_attempts=2,
    )
    started = Event()
    release = Event()

    def slow_handler(_task, _report) -> str:
        started.set()
        release.wait(timeout=2)
        return "/stale-result"

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: slow_handler},
        poll_interval_seconds=0.05,
    )
    worker.start()
    assert started.wait(timeout=1)

    before_stop = monotonic()
    worker.stop(timeout_seconds=0.02)
    assert monotonic() - before_stop < 0.5
    still_running = container.background_tasks.get(task.id)
    assert still_running is not None
    assert still_running.status == BackgroundTaskStatus.RUNNING
    assert still_running.result_url is None

    release.set()
    deadline = monotonic() + 1
    while worker.is_running and monotonic() < deadline:
        sleep(0.01)
    assert not worker.is_running
    paused = container.background_tasks.get(task.id)
    assert paused is not None
    assert paused.status == BackgroundTaskStatus.QUEUED
    assert paused.phase == "paused_for_restart"
    assert paused.result_url is None

    replacement = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: lambda _task, _report: "/matches"},
    )
    assert replacement.run_once()
    completed = container.background_tasks.get(task.id)
    assert completed is not None
    assert completed.status == BackgroundTaskStatus.SUCCEEDED
    assert completed.result_url == "/matches"
    assert completed.attempt == 2


def test_shutdown_keeps_lease_fresh_until_blocked_handler_unwinds(tmp_path: Path) -> None:
    container = _container(tmp_path, "shutdown-lease.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    started = Event()
    release = Event()

    def blocked_handler(_task, _report) -> str:
        started.set()
        release.wait(timeout=3)
        return "/stale-result"

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: blocked_handler},
        poll_interval_seconds=0.05,
        lease_ttl_seconds=0.2,
        heartbeat_interval_seconds=0.05,
    )
    worker.start()
    assert started.wait(timeout=1)
    worker.stop(timeout_seconds=0.01)

    # The graceful-stop request cannot make a still-live handler stale. Its
    # heartbeat keeps the fence until cooperative unwind or process death.
    sleep(0.35)
    assert container.background_tasks.recover_interrupted() == 0
    running = container.background_tasks.get(task.id)
    assert running is not None
    assert running.status == BackgroundTaskStatus.RUNNING
    assert running.lease_expires_at is not None
    assert running.lease_expires_at > datetime.now(timezone.utc)

    replacement = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: lambda _task, _report: "/matches"},
    )
    assert replacement.run_once() is False

    release.set()
    deadline = monotonic() + 1
    while worker.is_running and monotonic() < deadline:
        sleep(0.01)
    assert not worker.is_running
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.QUEUED
    assert replacement.run_once() is True
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.SUCCEEDED


def test_transient_heartbeat_failure_retries_while_handler_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path, "heartbeat-transient.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    started = Event()
    release = Event()

    def blocked_handler(_task, _report) -> str:
        started.set()
        release.wait(timeout=2)
        return "/matches"

    heartbeat = container.background_tasks.heartbeat
    failures = 0

    def fail_once(*args, **kwargs):
        nonlocal failures
        if failures == 0:
            failures += 1
            raise OperationalError("heartbeat", {}, RuntimeError("temporary"))
        return heartbeat(*args, **kwargs)

    monkeypatch.setattr(container.background_tasks, "heartbeat", fail_once)
    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: blocked_handler},
        poll_interval_seconds=0.05,
        lease_ttl_seconds=0.2,
        heartbeat_interval_seconds=0.05,
    )
    worker.start()
    assert started.wait(timeout=1)
    initial = container.background_tasks.get(task.id)
    assert initial is not None
    assert initial.heartbeat_at is not None
    assert initial.lease_expires_at is not None

    sleep(0.35)
    assert failures == 1
    assert worker.last_loop_error == "OperationalError"
    assert container.background_tasks.recover_interrupted() == 0
    running = container.background_tasks.get(task.id)
    assert running is not None
    assert running.lease_expires_at is not None
    assert running.heartbeat_at is not None
    assert running.heartbeat_at > initial.heartbeat_at
    assert running.lease_expires_at > initial.lease_expires_at

    release.set()
    deadline = monotonic() + 1
    while monotonic() < deadline:
        completed = container.background_tasks.get(task.id)
        if completed is not None and completed.is_terminal:
            break
        sleep(0.01)
    worker.stop()
    assert completed.status == BackgroundTaskStatus.SUCCEEDED


def test_permanent_heartbeat_failure_marks_old_handler_lease_lost(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path, "heartbeat-permanent.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    started = Event()
    release = Event()

    def blocked_handler(_task, _report) -> str:
        started.set()
        release.wait(timeout=2)
        return "/stale-result"

    def fail_heartbeat(*_args, **_kwargs):
        raise OperationalError("heartbeat", {}, RuntimeError("offline"))

    monkeypatch.setattr(container.background_tasks, "heartbeat", fail_heartbeat)
    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: blocked_handler},
        poll_interval_seconds=0.05,
        lease_ttl_seconds=0.2,
        heartbeat_interval_seconds=0.05,
    )
    worker.start()
    assert started.wait(timeout=1)

    sleep(0.3)
    assert worker.last_loop_error == "OperationalError"
    assert container.background_tasks.recover_interrupted() == 1
    replacement_claim = container.background_tasks.claim_next(
        claim_owner="replacement",
        lease_ttl_seconds=30,
    )
    assert replacement_claim is not None
    assert replacement_claim.id == task.id

    release.set()
    sleep(0.1)
    worker.stop()
    still_owned = container.background_tasks.get(task.id)
    assert still_owned is not None
    assert still_owned.status == BackgroundTaskStatus.RUNNING
    assert still_owned.claim_token == replacement_claim.claim_token
    assert still_owned.result_url is None


def test_restart_recovery_copy_is_explicit_and_task_is_claimable(tmp_path: Path) -> None:
    container = _container(tmp_path, "restart.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
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
    assert "restarted" in recovered.message
    assert "queued to resume" in recovered.message
    assert container.background_tasks.claim_next() is not None


def test_restarted_attempt_rejects_updates_from_the_interrupted_attempt(tmp_path: Path) -> None:
    container = _container(tmp_path, "attempt-lease.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    first_claim = container.background_tasks.claim_next()
    assert first_claim is not None
    assert first_claim.claim_token is not None
    assert container.background_tasks.requeue_interrupted(
        task.id,
        expected_attempt=first_claim.attempt,
        claim_token=first_claim.claim_token,
    )
    second_claim = container.background_tasks.claim_next()
    assert second_claim is not None
    assert second_claim.claim_token is not None
    assert second_claim.attempt == first_claim.attempt + 1

    stale_result = container.background_tasks.succeed(
        task.id,
        result_url="/stale-result",
        expected_attempt=first_claim.attempt,
        claim_token=first_claim.claim_token,
    )
    assert stale_result.status == BackgroundTaskStatus.RUNNING
    assert stale_result.result_url is None

    current_result = container.background_tasks.succeed(
        task.id,
        result_url="/matches",
        expected_attempt=second_claim.attempt,
        claim_token=second_claim.claim_token,
    )
    assert current_result.status == BackgroundTaskStatus.SUCCEEDED
    assert current_result.result_url == "/matches"
