from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep

from fastapi.testclient import TestClient

from betteroption.background import BackgroundTaskStatus
from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.settings import Settings
from betteroption.web import create_app


class BlockingDiscoveryProvider:
    name = "blocking-test"
    attribution = "Test discovery source"
    attribution_url = "https://example.com/discovery"

    def __init__(self, *, blocked: bool = True) -> None:
        self.started = Event()
        self.release = Event()
        if not blocked:
            self.release.set()
        self.calls = 0
        self.last_regional_count = 1

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test discovery provider was not released")
        return [
            DiscoveredJob(
                provider=self.name,
                external_id="embedded-1",
                title=f"{query.text.title()} Engineer",
                company="Example Systems",
                location=query.location or "Frankfurt",
                source_url="https://example.com/jobs/embedded-1",
                summary="Build and test embedded products.",
                distance_km=8.0,
                search_score=87,
            )
        ]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'v0611c.db').as_posix()}",
        auth_mode="local",
        background_worker_enabled=True,
        background_worker_poll_seconds=0.05,
        background_task_retry_seconds=0,
    )


def _wait_for_terminal_task(
    container: ApplicationContainer,
    task_id,
    *,
    timeout_seconds: float = 5,
):
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        task = container.background_tasks.get(task_id)
        if task is not None and task.status in {
            BackgroundTaskStatus.SUCCEEDED,
            BackgroundTaskStatus.FAILED,
        }:
            return task
        sleep(0.02)
    raise AssertionError("background Explore task did not finish")


def test_explore_search_survives_navigation_without_duplicate_provider_calls(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    container = ApplicationContainer(settings)
    container.workspaces.create()
    discovery = BlockingDiscoveryProvider()

    with TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=discovery,
        )
    ) as client:
        started = client.post(
            "/explore/search",
            data={"q": "embedded software", "location": "Frankfurt"},
            follow_redirects=False,
        )
        assert started.status_code == 303
        task_location = started.headers["location"]
        task_id = task_location.rsplit("/", 1)[-1]
        assert discovery.started.wait(timeout=2)

        returned = client.get("/explore", follow_redirects=False)
        duplicate = client.post(
            "/explore/search",
            data={"q": "another query", "location": "Berlin"},
            follow_redirects=False,
        )
        progress = client.get(task_location)

        assert returned.status_code == 303
        assert returned.headers["location"] == task_location
        assert duplicate.status_code == 303
        assert duplicate.headers["location"] == task_location
        assert "Searching public feeds and employer job boards." in progress.text
        assert "Continue browsing" not in progress.text
        assert discovery.calls == 1

        discovery.release.set()
        finished = _wait_for_terminal_task(container, task_id)
        assert finished.status == BackgroundTaskStatus.SUCCEEDED

        results = client.get("/explore")
        repeated = client.get(
            "/explore?q=embedded%20software&location=Frankfurt",
        )

        assert results.status_code == 200
        assert "Embedded Software Engineer" in results.text
        assert repeated.status_code == 200
        assert "Embedded Software Engineer" in repeated.text
        assert discovery.calls == 1


def test_completed_explore_snapshot_is_restored_after_application_restart(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    first_container = ApplicationContainer(settings)
    first_container.workspaces.create()
    first_discovery = BlockingDiscoveryProvider(blocked=False)

    with TestClient(
        create_app(
            first_container,
            data_directory=tmp_path / "first-data",
            discovery_provider=first_discovery,
        )
    ) as client:
        response = client.post(
            "/explore/search",
            data={"q": "test automation", "location": "Frankfurt"},
            follow_redirects=False,
        )
        task_id = response.headers["location"].rsplit("/", 1)[-1]
        assert _wait_for_terminal_task(first_container, task_id).status == (
            BackgroundTaskStatus.SUCCEEDED
        )
        assert first_discovery.calls == 1

    restarted_container = ApplicationContainer(settings)
    restarted_discovery = BlockingDiscoveryProvider(blocked=False)
    with TestClient(
        create_app(
            restarted_container,
            data_directory=tmp_path / "second-data",
            discovery_provider=restarted_discovery,
        )
    ) as client:
        restored = client.get("/explore")

    assert restored.status_code == 200
    assert "Test Automation Engineer" in restored.text
    assert restarted_discovery.calls == 0
