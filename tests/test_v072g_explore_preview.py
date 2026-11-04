from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from uuid import UUID

from fastapi.testclient import TestClient

from betteroption.background import BackgroundTaskKind, BackgroundTaskStatus
from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryQuery,
    SeniorityBand,
    SourceReadiness,
    rank_discovered_jobs,
)
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.settings import Settings
from betteroption.web import create_app
from betteroption.web.app import EXPLORE_PROVIDER_LABELS


def _job(
    identity: str,
    *,
    provider: str = "structured-test",
    title: str = "Software Engineer",
    source_readiness: SourceReadiness = SourceReadiness.PROVIDER_LISTED,
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        source_readiness=source_readiness,
        external_id=identity,
        title=title,
        company=f"Employer {identity}",
        location="Berlin",
        summary="Build reliable software products with a small engineering team.",
        source_url=f"https://careers.example/jobs/{identity}",
    )


class _Provider:
    attribution = "Test source"
    attribution_url = "https://example.com/source"

    def __init__(
        self,
        name: str,
        jobs: list[DiscoveredJob],
        *,
        wait_for: Event | None = None,
    ) -> None:
        self.name = name
        self.jobs = jobs
        self.wait_for = wait_for

    def search(self, _query: DiscoveryQuery) -> list[DiscoveredJob]:
        if self.wait_for is not None:
            assert self.wait_for.wait(1)
        return self.jobs


class _NoFetch:
    def fetch(self, _url: str):
        raise AssertionError("first-party published jobs must not use URL preflight")


def _container(
    tmp_path: Path,
    name: str = "preview.db",
    *,
    background_worker_enabled: bool = False,
    explore_preview_limit: int = 9,
) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            auth_mode="local",
            background_worker_enabled=background_worker_enabled,
            background_worker_poll_seconds=0.05,
            explore_preview_limit=explore_preview_limit,
        )
    )


def _wait_for_terminal_task(container: ApplicationContainer, task_id: UUID):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        task = container.background_tasks.get(task_id)
        if task is not None and task.status in {
            BackgroundTaskStatus.SUCCEEDED,
            BackgroundTaskStatus.FAILED,
        }:
            return task
        sleep(0.02)
    raise AssertionError("background Explore task did not finish")


def test_progressive_preview_reorders_deterministically_as_sources_finish() -> None:
    release_strong = Event()
    strong = _Provider(
        "slow-strong",
        [_job("strong", provider="slow-strong", title="Software Engineer")],
        wait_for=release_strong,
    )
    fast = _Provider(
        "fast-low",
        [_job("low", provider="fast-low", title="Software Support Assistant")],
    )
    mesh = DiscoverySourceMesh([strong, fast], search_budget_seconds=60)
    snapshots: list[tuple[str, list[str]]] = []

    def capture(stage: str, jobs: list[DiscoveredJob]) -> None:
        snapshots.append((stage, [job.external_id for job in jobs]))
        if stage == "fast-low":
            release_strong.set()

    final = mesh.search(DiscoveryQuery(text="software engineer"), on_preview=capture)

    assert snapshots[0] == ("fast-low", ["low"])
    assert snapshots[1][0] == "slow-strong"
    assert snapshots[1][1][0] == "strong"
    assert snapshots[-1][0] == "source_checks"
    assert snapshots[-1][1] == [job.external_id for job in final[:7]]
    assert all(len(rows) <= 7 for _stage, rows in snapshots)


def test_preview_callback_oserror_never_interrupts_provider_results() -> None:
    expected = _job("survives", provider="stable-source")
    mesh = DiscoverySourceMesh(
        [_Provider("stable-source", [expected])],
        search_budget_seconds=60,
    )

    def broken_preview(_stage: str, _jobs: list[DiscoveredJob]) -> None:
        raise OSError("preview client disconnected")

    final = mesh.search(
        DiscoveryQuery(text="software engineer"),
        on_preview=broken_preview,
    )

    assert [job.external_id for job in final] == ["survives"]


def test_preview_repository_write_failure_does_not_fail_background_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(
        tmp_path,
        "write-failure.db",
        background_worker_enabled=True,
    )
    workspace = container.workspaces.create()
    discovery = _Provider("stable-source", [_job("final", provider="stable-source")])

    def broken_preview_write(*_args, **_kwargs):
        raise OSError("preview database is temporarily read-only")

    monkeypatch.setattr(container.explore_searches, "update_preview", broken_preview_write)
    with TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data-write-failure",
            discovery_provider=discovery,
        )
    ) as client:
        response = client.post(
            "/explore/search",
            data={"q": "software engineer", "location": "Berlin"},
            follow_redirects=False,
        )
        task_id = UUID(response.headers["location"].rsplit("/", 1)[-1])
        terminal = _wait_for_terminal_task(container, task_id)

    assert response.status_code == 303
    assert terminal.status == BackgroundTaskStatus.SUCCEEDED
    completed = container.explore_searches.latest_completed(workspace.id)
    assert completed is not None
    assert [job.external_id for job in completed.results] == ["final"]


def test_preview_status_write_failure_does_not_fail_background_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(
        tmp_path,
        "status-write-failure.db",
        background_worker_enabled=True,
    )
    workspace = container.workspaces.create()
    discovery = _Provider("stable-source", [_job("final", provider="stable-source")])
    original_update_progress = container.background_tasks.update_progress

    def fail_only_preview_status(task_id, **values):
        if values.get("phase") == "ranking_preview":
            raise OSError("preview status write failed")
        return original_update_progress(task_id, **values)

    monkeypatch.setattr(container.background_tasks, "update_progress", fail_only_preview_status)
    with TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data-status-write-failure",
            discovery_provider=discovery,
        )
    ) as client:
        response = client.post(
            "/explore/search",
            data={"q": "software engineer", "location": "Berlin"},
            follow_redirects=False,
        )
        task_id = UUID(response.headers["location"].rsplit("/", 1)[-1])
        terminal = _wait_for_terminal_task(container, task_id)

    assert response.status_code == 303
    assert terminal.status == BackgroundTaskStatus.SUCCEEDED
    completed = container.explore_searches.latest_completed(workspace.id)
    assert completed is not None
    assert [job.external_id for job in completed.results] == ["final"]


def test_preview_repository_is_bounded_and_cannot_replace_completion(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    query = DiscoveryQuery(text="software engineer")
    container.explore_searches.create(
        task_id=task.id,
        workspace_id=workspace.id,
        query=query,
        query_text=query.text,
        location="",
        compass_used=False,
        hide_remote_only=False,
    )
    jobs = [_job(str(index)) for index in range(9)]

    preview = container.explore_searches.update_preview(task.id, results=jobs)

    assert preview.completed_at is None
    assert len(preview.results) == 9
    completed = container.explore_searches.complete(
        task.id,
        results=jobs,
        regional_result_count=0,
    )
    assert len(completed.results) == 9
    delayed = container.explore_searches.update_preview(task.id, results=jobs[:1])
    assert delayed.completed_at is not None
    assert len(delayed.results) == 9


def test_preview_limit_is_configurable_across_storage_and_source_mesh(tmp_path: Path) -> None:
    container = _container(tmp_path, explore_preview_limit=6)
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    query = DiscoveryQuery(text="software engineer", limit=20)
    container.explore_searches.create(
        task_id=task.id,
        workspace_id=workspace.id,
        query=query,
        query_text=query.text,
        location="",
        compass_used=False,
        hide_remote_only=False,
    )
    jobs = [_job(str(index)) for index in range(12)]

    stored = container.explore_searches.update_preview(task.id, results=jobs)
    mesh = DiscoverySourceMesh(
        [_Provider("all", jobs)],
        search_budget_seconds=60,
        preview_limit=6,
    )
    snapshots: list[list[DiscoveredJob]] = []
    mesh.search(query, on_preview=lambda _stage, rows: snapshots.append(rows))

    assert len(stored.results) == 6
    assert snapshots
    assert all(len(rows) <= 6 for rows in snapshots)


def test_running_task_status_exposes_only_link_free_preview_fields(tmp_path: Path) -> None:
    container = _container(tmp_path, "status.db")
    workspace = container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    query = DiscoveryQuery(text="software engineer")
    container.explore_searches.create(
        task_id=task.id,
        workspace_id=workspace.id,
        query=query,
        query_text=query.text,
        location="Berlin",
        compass_used=False,
        hide_remote_only=False,
    )
    own = DiscoveredJob(
        provider="betteroption-posted",
        source_readiness=SourceReadiness.READY,
        external_id="private-internal-id",
        title="Software Engineer",
        company="Own Employer",
        location="Berlin",
        tags=["All Jobs Scraper", "Hybrid"],
        summary="Build software products.",
        source_url="https://careers.example/jobs/secret?token=never-return-this",
        search_score=88,
        keyword_relevance=91,
    )
    container.explore_searches.update_preview(task.id, results=[own])

    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    status = client.get(f"/tasks/{task.id}/status")
    page = client.get(f"/tasks/{task.id}")

    assert status.status_code == 200
    row = status.json()["preview"][0]
    assert row["provider_label"] == "Own"
    assert row["is_own"] is True
    assert row["tags"] == ["Hybrid"]
    serialized = json.dumps(status.json())
    assert "source_url" not in serialized
    assert "external_id" not in serialized
    assert "never-return-this" not in serialized
    assert "Scraper" not in serialized
    assert page.status_code == 200
    assert "data-explore-progress-preview" in page.text
    assert 'data-preview-limit="9"' in page.text
    assert "0</strong> of 9" in page.text
    assert "never-return-this" not in page.text


def test_missing_seniority_adds_no_positive_evidence() -> None:
    query = DiscoveryQuery(
        text="software engineer",
        seniority_targets=[SeniorityBand.JUNIOR],
    )

    result = rank_discovered_jobs(query, [_job("unknown-level")])[0]

    assert result.seniority_relevance is None
    assert result.seniority_note == "The title does not state a seniority level."
    assert result.compass_relevance == round((result.keyword_relevance or 0) * 0.7)


def test_published_own_job_stays_ready_without_network_preflight() -> None:
    own = _job(
        "own",
        provider="betteroption-posted",
        source_readiness=SourceReadiness.READY,
    )
    availability = DiscoveryAvailabilityFilter(fetcher=_NoFetch())

    kept = availability.keep_open_or_unknown([own])

    assert len(kept) == 1
    assert kept[0].source_readiness == SourceReadiness.READY


def test_explore_uses_own_label_and_no_scraper_job_badge_wording() -> None:
    template = Path("src/betteroption/web/templates/explore.html").read_text(encoding="utf-8")
    progress = Path("src/betteroption/web/templates/task_progress.html").read_text(encoding="utf-8")

    assert EXPLORE_PROVIDER_LABELS["betteroption-posted"] == "Own"
    assert EXPLORE_PROVIDER_LABELS["apify-all-jobs"] == "All Jobs via Apify"
    assert "All Jobs Scraper via Apify" not in EXPLORE_PROVIDER_LABELS.values()
    assert "explore-own-badge" in template
    preview_markup = progress.split("data-explore-progress-preview", 1)[1]
    assert "<a " not in preview_markup
    assert "checkbox" not in preview_markup
