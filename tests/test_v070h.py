from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.background import BackgroundTaskKind
from betteroption.container import ApplicationContainer
from betteroption.settings import Settings
from betteroption.web import create_app


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v070h.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )


def test_recent_background_activity_is_ordered_by_latest_update(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    first = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.MATCH_RUN,
    )
    second = container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.EXPLORE_SEARCH,
    )

    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.id == first.id

    recent = container.background_tasks.list_recent(limit=2)

    assert [task.id for task in recent] == [first.id, second.id]
    assert recent[0].updated_at >= recent[1].updated_at


def test_operations_exposes_live_task_freshness_and_auto_refresh(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    container.background_tasks.create(
        workspace.id,
        BackgroundTaskKind.JOB_IMPORT,
    )
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        response = client.get("/operations")

    assert response.status_code == 200
    assert "Live view observed" in response.text
    assert "1 workflow still active" in response.text
    assert "Last activity" in response.text
    assert "data-operations-auto-refresh" in response.text


def test_feedback_language_is_general_across_job_types() -> None:
    app_source = Path("src/betteroption/web/app.py").read_text(encoding="utf-8")
    job_template = Path("src/betteroption/web/templates/job_detail.html").read_text(
        encoding="utf-8"
    )
    match_template = Path("src/betteroption/web/templates/match_detail.html").read_text(
        encoding="utf-8"
    )
    combined_templates = f"{job_template}\n{match_template}"

    assert '"Responsibilities do not fit"' in app_source
    assert '"Day-to-day work does not fit"' in app_source
    assert '"Level or scope does not fit"' in app_source
    assert '"Company or work context does not fit"' in app_source
    assert "How does this opportunity feel?" in combined_templates
    assert "What influenced you?" in combined_templates
    assert "Too much consulting" not in app_source
    assert "Too little development" not in app_source
    assert "Too senior" not in app_source


def test_operations_refresh_script_is_visibility_aware() -> None:
    script = Path("src/betteroption/web/static/app.js").read_text(encoding="utf-8")

    assert 'document.querySelector("[data-operations-auto-refresh]")' in script
    assert 'document.visibilityState === "visible"' in script
    assert "window.location.reload()" in script
