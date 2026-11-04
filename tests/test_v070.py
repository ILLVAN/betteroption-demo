from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from betteroption.accounts import RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime.now(timezone.utc)
PASSWORD = "correct horse battery staple"


def settings(tmp_path: Path, *, auth_mode: str = "accounts") -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'v070.db').as_posix()}",
        auth_mode=auth_mode,
        registration_mode="open",
        background_worker_enabled=False,
        employer_homepage_research=False,
    )


def seed_job(container: ApplicationContainer, slug: str) -> UUID:
    url = f"https://careers.example.com/jobs/{slug}"
    source = f"{slug.title()} Engineer at Example Products. Build useful software."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title=f"{slug.title()} Engineer",
        company="Example Products",
        location="Frankfurt",
        summary="Build useful software.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
    )
    return container.repository.store_revision(
        document,
        job,
        JobObservationKind.NEW,
    ).id


def create_account(container: ApplicationContainer, email: str):
    return container.accounts.create(
        email,
        email.split("@", 1)[0].title(),
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )


def authenticated_client(app, container: ApplicationContainer, account) -> TestClient:
    client = TestClient(app)
    session = container.accounts.create_session(account, ttl=timedelta(days=1))
    client.cookies.set("betteroption_session", session.token)
    return client


def test_local_mode_remains_available_without_authentication(tmp_path: Path) -> None:
    container = ApplicationContainer(settings(tmp_path, auth_mode="local"))
    container.workspaces.create()

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        home = client.get("/")
        login = client.get("/login", follow_redirects=False)

    assert home.status_code == 200
    assert login.status_code == 303
    assert login.headers["location"] == "/"


def test_account_mode_redirects_anonymous_requests_to_login(tmp_path: Path) -> None:
    container = ApplicationContainer(settings(tmp_path))

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        response = client.get("/explore?use_compass=true", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?")
    assert "next=%2Fexplore%3Fuse_compass%3Dtrue" in response.headers["location"]


def test_first_account_claims_existing_local_workspace_and_job_access(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    legacy_workspace = container.workspaces.create()
    job_record_id = seed_job(container, "legacy")

    owner = container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode=RegistrationMode.FIRST_USER,
    )

    claimed = container.workspaces.get(legacy_workspace.id, account_id=owner.id)
    grants = container.results.access_grants(legacy_workspace.id)
    assert claimed is not None
    assert claimed.account_id == owner.id
    assert [grant.job_record_id for grant in grants] == [job_record_id]


def test_accounts_cannot_see_another_accounts_compass_or_saved_jobs(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account_a = create_account(container, "alpha@example.com")
    account_b = create_account(container, "beta@example.com")
    workspace_a = container.workspaces.create(account_id=account_a.id)
    container.workspaces.create(account_id=account_b.id)
    job_record_id = seed_job(container, "tenant-alpha")
    container.results.grant_job(workspace_a.id, job_record_id)
    app = create_app(container, data_directory=tmp_path / "data")

    with (
        authenticated_client(app, container, account_a) as client_a,
        authenticated_client(app, container, account_b) as client_b,
    ):
        archive_a = client_a.get("/jobs")
        archive_b = client_b.get("/jobs")
        detail_a = client_a.get(f"/jobs/{job_record_id}")
        detail_b = client_b.get(f"/jobs/{job_record_id}")
        compass_a = client_a.get(f"/profile/{workspace_a.id}")
        compass_b = client_b.get(f"/profile/{workspace_a.id}")

    assert archive_a.status_code == 200
    assert "Tenant-Alpha Engineer" in archive_a.text
    assert archive_b.status_code == 200
    assert "Tenant-Alpha Engineer" not in archive_b.text
    assert detail_a.status_code == 200
    assert detail_b.status_code == 404
    assert compass_a.status_code == 200
    assert compass_b.status_code == 404


def test_account_page_renders_workspace_counts_without_template_internals(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account = create_account(container, "account-page@example.com")
    container.workspaces.create(account_id=account.id)
    app = create_app(container, data_directory=tmp_path / "data")

    with authenticated_client(app, container, account) as client:
        response = client.get("/account")

    assert response.status_code == 200
    assert "Account-Page" in response.text
    assert "0</strong><span>confirmed statements" in response.text
    assert "0</strong><span>open statements" in response.text


def test_account_export_contains_private_graph_without_authentication_secrets(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account = create_account(container, "export@example.com")
    workspace = container.workspaces.create(account_id=account.id)
    job_record_id = seed_job(container, "exported")
    container.results.grant_job(workspace.id, job_record_id)
    container.accounts.create_session(account, ttl=timedelta(days=1))

    export_text = container.accounts.export_json(account.id)
    export = json.loads(export_text)

    assert export["account"]["email"] == "export@example.com"
    assert export["workspaces"][0]["account_id"] == str(account.id)
    assert export["saved_job_access"][0]["job_record_id"] == str(job_record_id)
    assert "password_hash" not in export_text
    assert "auth_sessions" not in export
    assert "token" not in export_text


def test_account_deletion_removes_private_graph_but_not_shared_public_job(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account = create_account(container, "delete@example.com")
    workspace = container.workspaces.create(account_id=account.id)
    job_record_id = seed_job(container, "shared-source")
    container.results.grant_job(workspace.id, job_record_id)

    assert container.accounts.delete_account(account.id)

    assert container.accounts.get(account.id) is None
    assert container.workspaces.get(workspace.id) is None
    assert container.results.access_grants(workspace.id) == []
    assert container.repository.get_current_job(job_record_id) is not None


def test_explore_progress_uses_slow_started_at_estimate_with_persisted_floor() -> None:
    project_root = Path(__file__).resolve().parents[1]
    template = (project_root / "src/betteroption/web/templates/task_progress.html").read_text(
        encoding="utf-8"
    )
    javascript = (project_root / "src/betteroption/web/static/app.js").read_text(encoding="utf-8")

    assert 'data-task-kind="{{ task.kind.value }}"' in template
    assert "task.progress_indeterminate" in javascript
    assert 'progressBar.removeAttribute("value")' in javascript
    assert "progressBar.value = displayProgress.percent" in javascript
    assert "apparentExploreProgress" not in javascript
    assert "progressStartedAt" not in javascript
    assert "EXPLORE_PROGRESS_CEILING = 94" in javascript
    assert "Math.min(EXPLORE_PROGRESS_CEILING, Math.max(stored, estimate))" in javascript
