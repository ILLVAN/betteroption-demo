from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from betteroption.background import (
    BackgroundTaskCommitRejected,
    BackgroundTaskKind,
    BackgroundTaskStatus,
    BackgroundWorker,
)
from betteroption.concurrency import (
    CooperativeControlFlow,
    check_cooperative_control,
    cooperative_control,
)
from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.job_corpus import JobCorpusService
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import (
    JobFact,
    JobFactKind,
    JobPosting,
    JobSourceType,
    JobUrlStatus,
)
from betteroption.operations import ProviderBudgetPolicy, RecordingDiscoveryProvider
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.results import ResultService
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _container(tmp_path: Path, name: str) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )


class _BlockedProvider:
    name = "blocked-provider"
    attribution = "Blocked provider"
    attribution_url = "https://example.com/provider"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.last_request_count = 0

    @staticmethod
    def maximum_request_count(_query: DiscoveryQuery) -> int:
        return 1

    def search(self, _query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 1
        self.started.set()
        self.release.wait(timeout=30)
        return []


def test_explore_abort_is_terminal_and_unwinds_provider_wait_without_result_commit(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "explore-cancel.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.EXPLORE_SEARCH,
    )
    provider = _BlockedProvider()
    budget = ProviderBudgetPolicy(
        container.operations,
        daily_operation_limit=1,
        daily_cost_limit_usd=0.20,
    )
    recorded_provider = RecordingDiscoveryProvider(
        provider,
        container.operations,
        budget,
        estimated_cost_usd=0.20,
        cost_is_per_request=True,
    )
    mesh = DiscoverySourceMesh([recorded_provider], search_budget_seconds=30)
    handler_unwound = Event()
    committed: list[bool] = []

    def handler(_task, report) -> str:
        try:
            mesh.search(
                DiscoveryQuery(text="embedded engineer"),
                check_control=report.checkpoint,
            )
            committed.append(True)
            return "/explore"
        finally:
            handler_unwound.set()

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.EXPLORE_SEARCH: handler},
        poll_interval_seconds=0.05,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
    )
    worker.start()
    assert provider.started.wait(timeout=2)

    cancelled = container.background_tasks.request_cancel(task.id)
    assert worker.cancel(task.id) is True

    assert cancelled.status == BackgroundTaskStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.claim_token is None
    assert handler_unwound.wait(timeout=1)
    assert committed == []
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.CANCELLED

    provider.release.set()
    deadline = monotonic() + 1
    summary = container.operations.summary_today()
    while summary.failed_operations == 0 and monotonic() < deadline:
        sleep(0.01)
        summary = container.operations.summary_today()
    usage = container.operations.budget_usage_today()
    assert usage.operation_count == 1
    assert usage.estimated_cost_usd == pytest.approx(0.20)
    assert summary.total_operations == 1
    assert summary.failed_operations == 1

    # A fresh policy models a new process: durable cancelled-call telemetry,
    # not an in-memory reservation, must close the relaunch/abort budget gap.
    restarted_budget = ProviderBudgetPolicy(
        container.operations,
        daily_operation_limit=1,
        daily_cost_limit_usd=0.20,
    )
    assert (
        restarted_budget.allows(
            proposed_operation_count=1,
            proposed_cost_usd=0.20,
        )
        is False
    )
    worker.stop()


def test_nested_provider_control_records_and_reconciles_incurred_usage(tmp_path: Path) -> None:
    container = _container(tmp_path, "nested-provider-cancel.db")

    class StopWork(CooperativeControlFlow):
        pass

    class NestedProvider:
        name = "nested-provider"
        attribution = "Nested provider"
        attribution_url = "https://example.com/nested"
        last_request_count = 0

        @staticmethod
        def maximum_request_count(_query: DiscoveryQuery) -> int:
            return 3

        def search(self, _query: DiscoveryQuery) -> list[DiscoveredJob]:
            self.last_request_count = 2
            check_cooperative_control()
            raise AssertionError("control checkpoint did not stop provider output")

    raw = NestedProvider()
    budget = ProviderBudgetPolicy(container.operations, daily_operation_limit=3)
    provider = RecordingDiscoveryProvider(raw, container.operations, budget)
    checkpoints = 0

    def checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1
        # Initial admission and the new post-reservation fence must both pass;
        # stop only at the checkpoint inside the provider call.
        if checkpoints >= 3:
            raise StopWork

    with cooperative_control(checkpoint), pytest.raises(StopWork):
        provider.search(DiscoveryQuery(text="embedded engineer"))

    usage = container.operations.budget_usage_today()
    summary = container.operations.summary_today()
    assert raw.last_request_count == 2
    # Cancellation may leave an in-flight request with an unknowable outcome,
    # so the durable reservation deliberately retains the provider maximum.
    assert usage.operation_count == 3
    assert summary.total_operations == 1
    assert summary.failed_operations == 1


class _BlockingMobility:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def assess(self, *_args, **_kwargs):
        self.started.set()
        self.release.wait(timeout=30)
        return []


def _seed_match_input(container: ApplicationContainer):
    session = new_session()
    session.profile.facts = [
        ProfileFact(
            key="role.family",
            value="embedded software",
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.DIRECTION,
                text="embedded software",
            ),
        )
    ]
    workspace = container.workspaces.create(session)
    url = "https://careers.example.com/jobs/cancellable-match"
    source = "Embedded software engineer. Hybrid work. Python is required."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title="Embedded Software Engineer",
        company="Example Products",
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
        observed_at=NOW,
        facts=[
            JobFact(
                key="role.family",
                value="embedded software",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Embedded software engineer",
            )
        ],
    )
    container.repository.store_revision(document, job, JobObservationKind.NEW)
    return workspace


def test_match_abort_does_not_wait_for_slow_route_or_save_a_run(tmp_path: Path) -> None:
    container = _container(tmp_path, "match-cancel.db")
    workspace = _seed_match_input(container)
    mobility = _BlockingMobility()
    service = ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        mobility,
        job_overrides=container.job_overrides,
    )
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    handler_unwound = Event()

    def handler(active_task, report) -> str:
        try:
            service.run(
                workspace,
                workflow_id=active_task.id,
                progress=report,
            )
            return "/matches"
        finally:
            handler_unwound.set()

    worker = BackgroundWorker(
        container.background_tasks,
        {BackgroundTaskKind.MATCH_RUN: handler},
        poll_interval_seconds=0.05,
    )
    worker.start()
    assert mobility.started.wait(timeout=2)

    container.background_tasks.request_cancel(task.id)
    worker.cancel(task.id)

    assert handler_unwound.wait(timeout=1)
    assert container.background_tasks.get(task.id).status == BackgroundTaskStatus.CANCELLED
    assert container.results.get_run(task.id) is None

    mobility.release.set()
    worker.stop()


def test_cancelled_claim_atomically_fences_late_explore_and_match_snapshots(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "commit-fence.db")
    workspace = _seed_match_input(container)

    explore_task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.EXPLORE_SEARCH,
    )
    container.explore_searches.create(
        task_id=explore_task.id,
        workspace_id=workspace.id,
        query=DiscoveryQuery(text="embedded engineer"),
        query_text="embedded engineer",
        location="Frankfurt",
        compass_used=False,
        hide_remote_only=False,
    )
    explore_claim = container.background_tasks.claim_next()
    assert explore_claim is not None and explore_claim.claim_token is not None
    container.background_tasks.request_cancel(explore_task.id)

    with pytest.raises(BackgroundTaskCommitRejected):
        container.explore_searches.complete(
            explore_task.id,
            results=[],
            regional_result_count=0,
            expected_task_attempt=explore_claim.attempt,
            task_claim_token=explore_claim.claim_token,
        )
    assert container.explore_searches.get(explore_task.id).completed_at is None

    match_task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    match_claim = container.background_tasks.claim_next()
    assert match_claim is not None and match_claim.claim_token is not None
    container.background_tasks.request_cancel(match_task.id)
    service = ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        job_overrides=container.job_overrides,
    )

    with pytest.raises(BackgroundTaskCommitRejected):
        service.run(
            workspace,
            workflow_id=match_task.id,
            task_attempt=match_claim.attempt,
            task_claim_token=match_claim.claim_token,
        )
    assert container.results.get_run(match_task.id) is None


def test_cancelled_job_import_claim_fences_corpus_and_access_grant(tmp_path: Path) -> None:
    container = _container(tmp_path, "job-import-fence.db")
    workspace = container.workspaces.create()
    url = "https://careers.example.com/jobs/import-fence"
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text="Example needs Python for an embedded software engineering position.",
        fetched_at=NOW,
    )

    class Fetcher:
        @staticmethod
        def fetch(_url: str) -> FetchedDocument:
            return document

    class Extractor:
        @staticmethod
        def extract(source_text: str, **metadata) -> JobPosting:
            extraction = JobExtraction(
                title="Embedded Software Engineer",
                company="Example Products",
                location="Frankfurt",
                summary="Build embedded products.",
                facts=[
                    JobFactDraft(
                        key="skill.name",
                        value="Python",
                        kind="requirement",
                        evidence_quote="Python",
                    )
                ],
            )
            return extraction.to_job_posting(source_text=source_text, **metadata)

    snapshots = tmp_path / "import-snapshots"
    service = JobCorpusService(
        container.repository,
        fetcher=Fetcher(),
        extractor=Extractor(),
        source_snapshot_directory=snapshots,
        canonical_job_directory=tmp_path / "import-jobs",
    )
    import_task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.JOB_IMPORT,
    )
    import_claim = container.background_tasks.claim_next()
    assert import_claim is not None and import_claim.claim_token is not None
    container.background_tasks.request_cancel(import_task.id)

    with pytest.raises(BackgroundTaskCommitRejected):
        service.import_url(
            url,
            commit_task_id=import_task.id,
            expected_task_attempt=import_claim.attempt,
            task_claim_token=import_claim.claim_token,
        )

    assert container.repository.count_records() == 0
    assert list(snapshots.glob("source-snapshot-*.json")) == []

    imported = service.import_url(url)
    assert imported.record is not None
    grant_task = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.JOB_IMPORT,
    )
    grant_claim = container.background_tasks.claim_next()
    assert grant_claim is not None and grant_claim.claim_token is not None
    container.background_tasks.request_cancel(grant_task.id)

    with pytest.raises(BackgroundTaskCommitRejected):
        container.results.grant_job(
            workspace.id,
            imported.record.id,
            commit_task_id=grant_task.id,
            expected_task_attempt=grant_claim.attempt,
            task_claim_token=grant_claim.claim_token,
        )

    assert container.results.access_grants(workspace.id) == []


def test_preview_cosmetic_errors_are_ignored_but_worker_control_is_not() -> None:
    job = DiscoveredJob(
        provider="instant",
        external_id="one",
        title="Embedded Engineer",
        company="Example",
        source_url="https://careers.example.com/jobs/one",
    )

    class InstantProvider:
        name = "instant"
        attribution = "Instant"
        attribution_url = "https://example.com"

        @staticmethod
        def search(_query: DiscoveryQuery) -> list[DiscoveredJob]:
            return [job]

    mesh = DiscoverySourceMesh([InstantProvider()], search_budget_seconds=30)
    assert mesh.search(
        DiscoveryQuery(text="embedded engineer"),
        on_preview=lambda _stage, _jobs: (_ for _ in ()).throw(OSError("presentation")),
    )

    class StopWork(BaseException):
        pass

    with pytest.raises(StopWork):
        mesh.search(
            DiscoveryQuery(text="embedded engineer"),
            on_preview=lambda _stage, _jobs: (_ for _ in ()).throw(StopWork()),
        )


def test_progress_contract_restores_slow_explore_estimate_and_started_timestamp(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path, "progress.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    claim = container.background_tasks.claim_next()
    assert claim is not None

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        status = client.get(f"/tasks/{task.id}/status").json()

    javascript = (PROJECT_ROOT / "src/betteroption/web/static/app.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "src/betteroption/web/templates/task_progress.html").read_text(
        encoding="utf-8"
    )

    assert status["started_at"]
    assert "EXPLORE_PROGRESS_CEILING = 94" in javascript
    assert "EXPLORE_PROGRESS_HORIZON_MS = 9 * 60 * 1000" in javascript
    assert "Math.min(EXPLORE_PROGRESS_CEILING, Math.max(stored, estimate))" in javascript
    assert 'task.kind !== "explore_search"' in javascript
    assert "Cancelling…" not in javascript
    assert "Cancelling…" not in template
    assert "data-task-stopping" in template


def test_one_sigint_exits_without_joining_stuck_provider_io() -> None:
    code = r"""
import os
import signal
import tempfile
from pathlib import Path
from threading import Event

from betteroption.background import BackgroundTaskKind, BackgroundWorker
from betteroption.concurrency import DaemonThreadPoolExecutor
from betteroption.container import ApplicationContainer
from betteroption.settings import Settings

root = Path(tempfile.mkdtemp(prefix="betteroption-shutdown-"))
container = ApplicationContainer(Settings(
    _env_file=None,
    database_url=f"sqlite:///{(root / 'shutdown.db').as_posix()}",
    auth_mode="local",
    background_worker_enabled=False,
))
workspace = container.workspaces.create()
container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
started = Event()
never = Event()
stopping = Event()

def handler(_task, _report):
    pool = DaemonThreadPoolExecutor(1, thread_name_prefix="stuck-provider")
    future = pool.submit(never.wait, 60)
    started.set()
    try:
        future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return "/explore"

def request_stop(_signum, _frame):
    stopping.set()

signal.signal(signal.SIGINT, request_stop)
worker = BackgroundWorker(
    container.background_tasks,
    {BackgroundTaskKind.EXPLORE_SEARCH: handler},
    poll_interval_seconds=0.05,
)
worker.start()
assert started.wait(timeout=2)
signal.raise_signal(signal.SIGINT)
assert stopping.wait(timeout=1)
worker.stop(timeout_seconds=0.05, cancel_running=True)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    started = monotonic()
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert monotonic() - started < 5
    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr


def test_cancel_route_never_renders_a_cancelling_button(tmp_path: Path) -> None:
    container = _container(tmp_path, "cancel-ui.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.MATCH_RUN)
    container.background_tasks.claim_next()

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        response = client.post(f"/tasks/{task.id}/cancel", follow_redirects=True)
        payload = client.get(f"/tasks/{task.id}/status").json()

    assert response.status_code == 200
    assert payload["status"] == BackgroundTaskStatus.CANCELLED.value
    assert payload["cancellable"] is False
    assert "Cancelling…" not in response.text
    assert "data-task-cancel-form" in response.text
    assert "Cancelled" in response.text
