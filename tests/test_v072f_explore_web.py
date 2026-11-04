from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from betteroption.background import BackgroundTaskKind, BackgroundTaskStatus
from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveredJob, DiscoveryQuery, SourceReadiness
from betteroption.operations import ProviderOperation, ProviderOperationOutcome
from betteroption.settings import Settings
from betteroption.url_ingestion import UrlFailureKind, UrlIngestionError
from betteroption.web import create_app

from test_opportunity_web import JobExtractor, SequenceFetcher


class StaticDiscoveryProvider:
    name = "static"
    attribution = "Static test source"
    attribution_url = "https://example.com/source"

    def __init__(self, jobs: list[DiscoveredJob]) -> None:
        self.jobs = jobs

    def search(self, _query: DiscoveryQuery) -> list[DiscoveredJob]:
        return self.jobs


def _container(
    tmp_path: Path,
    name: str,
    *,
    background_worker_enabled: bool,
) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            auth_mode="local",
            background_worker_enabled=background_worker_enabled,
            background_worker_poll_seconds=0.05,
        )
    )


def _job(
    provider: str,
    identity: str,
    url: str,
    *,
    title: str,
    source_providers: list[str] | None = None,
) -> DiscoveredJob:
    return DiscoveredJob(
        provider=provider,
        source_providers=source_providers or [],
        external_id=identity,
        title=title,
        company="Example Products",
        location="Berlin",
        summary="Build embedded products.",
        source_url=url,
    )


def _save_completed_search(
    container: ApplicationContainer,
    jobs: list[DiscoveredJob],
):
    workspace = container.workspaces.latest() or container.workspaces.create()
    task = container.background_tasks.create(workspace.id, BackgroundTaskKind.EXPLORE_SEARCH)
    query = DiscoveryQuery(text="embedded engineer")
    container.explore_searches.create(
        task_id=task.id,
        workspace_id=workspace.id,
        query=query,
        query_text=query.text,
        location="",
        compass_used=False,
        hide_remote_only=False,
    )
    container.explore_searches.complete(
        task.id,
        results=jobs,
        regional_result_count=0,
    )
    claimed = container.background_tasks.claim_next()
    assert claimed is not None
    assert claimed.claim_token is not None
    container.background_tasks.succeed(
        task.id,
        result_url="/explore",
        expected_attempt=claimed.attempt,
        claim_token=claimed.claim_token,
    )
    return workspace, task


def _record_discovery_operation(
    container: ApplicationContainer,
    *,
    workflow_id,
    provider: str,
    outcome: ProviderOperationOutcome,
    result_count: int,
) -> None:
    now = datetime.now(timezone.utc)
    container.operations.record(
        ProviderOperation(
            provider=provider,
            purpose="job-discovery",
            outcome=outcome,
            started_at=now,
            finished_at=now + timedelta(milliseconds=10),
            latency_ms=10,
            result_count=result_count,
            workflow_id=workflow_id,
            workflow_type="explore-search",
        )
    )


def test_provider_filters_count_merged_provenance_and_disable_empty_sources(
    tmp_path: Path,
) -> None:
    container = _container(
        tmp_path,
        "provider-filters.db",
        background_worker_enabled=False,
    )
    job = _job(
        "apify-jobspipe",
        "merged",
        "https://careers.example.com/jobs/merged",
        title="Merged Embedded Engineer",
        source_providers=["apify-jobspipe", "exa-fallback"],
    )
    _workspace, task = _save_completed_search(container, [job])
    _record_discovery_operation(
        container,
        workflow_id=task.id,
        provider="apify-jobspipe",
        outcome=ProviderOperationOutcome.SUCCEEDED,
        result_count=8,
    )
    _record_discovery_operation(
        container,
        workflow_id=task.id,
        provider="exa-fallback",
        outcome=ProviderOperationOutcome.SUCCEEDED,
        result_count=5,
    )
    _record_discovery_operation(
        container,
        workflow_id=task.id,
        provider="brave-web",
        outcome=ProviderOperationOutcome.SUCCEEDED,
        result_count=4,
    )
    _record_discovery_operation(
        container,
        workflow_id=task.id,
        provider="you-web",
        outcome=ProviderOperationOutcome.FAILED,
        result_count=0,
    )

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        page = client.get("/explore")

    assert page.status_code == 200
    assert "Found 8 usable job(s); 1 contributed" in page.text
    assert "Found 5 usable job(s); 1 contributed" in page.text
    assert "Found 4 usable job(s); 0 contributed" in page.text
    assert 'value="apify-jobspipe" data-provider-filter aria-label=' in page.text
    assert 'Show results supplied by JobsPipe via Apify" checked' in page.text
    assert 'value="exa-fallback" data-provider-filter aria-label=' in page.text
    assert 'Show results supplied by Exa" checked' in page.text
    assert 'value="brave-web" data-provider-filter aria-label=' in page.text
    assert 'Show results supplied by Brave Search" disabled' in page.text
    assert 'value="you-web" data-provider-filter aria-label=' in page.text
    assert 'Show results supplied by You.com Search" disabled' in page.text
    assert 'data-source-providers="apify-jobspipe|exa-fallback"' in page.text


def test_two_explore_cards_expose_identity_source_and_labeled_date_evidence(
    tmp_path: Path,
) -> None:
    dated_url = "https://careers.example.com/jobs/dated?VacancyId=42"
    manual_url = "https://careers.example.com/jobs/manual?VacancyId=43"
    dated = _job(
        "apify-jobspipe",
        "dated-42",
        dated_url,
        title="Dated Embedded Engineer",
    ).model_copy(update={"published_at": datetime(2026, 8, 2, 9, 30, tzinfo=timezone.utc)})
    manual = _job(
        "you-web",
        "manual-43",
        manual_url,
        title="Manual Embedded Engineer",
    ).model_copy(update={"source_readiness": SourceReadiness.MANUAL_REQUIRED})
    container = _container(tmp_path, "two-card-evidence.db", background_worker_enabled=False)
    _workspace, task = _save_completed_search(container, [dated, manual])

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        page = client.get("/explore")

    soup = BeautifulSoup(page.text, "html.parser")
    cards = {card["data-explore-id"]: card for card in soup.select("[data-explore-card]")}
    assert set(cards) == {"dated-42", "manual-43"}
    assert cards["dated-42"]["data-source-url"] == dated_url
    assert cards["manual-43"]["data-source-url"] == manual_url
    posted_time = cards["dated-42"].select_one(".job-tags time[datetime]")
    assert posted_time is not None
    assert posted_time["datetime"] == "2026-08-02T09:30:00+00:00"
    assert "Posted" in posted_time.parent.get_text(" ", strip=True)
    assert all(card.select_one(".card-footer time") is None for card in cards.values())
    assert all(
        card.select_one(".card-footer").get_text(" ", strip=True) == "Inspect source ↗"
        for card in cards.values()
    )
    manual_cta = cards["manual-43"].select_one("a.explore-readiness-badge.is-manual")
    assert manual_cta is not None
    recovery_url = urlsplit(manual_cta["href"])
    assert recovery_url.path == "/add"
    assert parse_qs(recovery_url.query) == {"url": [manual_url], "manual": ["true"]}
    assert recovery_url.fragment == "manual-job-input"
    assert cards["manual-43"].select_one(".card-footer a")["href"] == manual_url
    origin_input = soup.select_one('input[name="source_explore_task_id"]')
    assert origin_input is not None
    assert origin_input["value"] == str(task.id)


def test_add_manual_recovery_prefills_only_safe_public_source_urls(tmp_path: Path) -> None:
    container = _container(tmp_path, "manual-add-get.db", background_worker_enabled=False)
    container.workspaces.create()
    app = create_app(container, data_directory=tmp_path / "data")
    source_url = "https://careers.example.com/jobs/manual?VacancyId=43&utm_source=explore"

    with TestClient(app) as client:
        safe_page = client.get("/add", params={"url": source_url, "manual": "true"})
        unsafe_page = client.get(
            "/add",
            params={"url": "https://user:secret@careers.example.com/jobs/43", "manual": "true"},
        )

    safe = BeautifulSoup(safe_page.text, "html.parser")
    panel = safe.select_one("#manual-job-input")
    assert panel is not None
    assert not panel.has_attr("hidden")
    assert safe.select_one("#add-job-url")["value"] == (
        "https://careers.example.com/jobs/manual?VacancyId=43"
    )
    assert "Automatic import needs the public advertisement text" in panel.get_text(" ")
    assert panel.select_one("a")["href"] == ("https://careers.example.com/jobs/manual?VacancyId=43")

    unsafe = BeautifulSoup(unsafe_page.text, "html.parser")
    assert unsafe.select_one("#add-job-url")["value"] == ""
    assert unsafe.select_one("#manual-job-input").has_attr("hidden")
    assert "user:secret" not in unsafe_page.text


def test_sync_import_removes_only_expired_and_keeps_manual_recovery_visible(
    tmp_path: Path,
) -> None:
    manual_url = "https://careers.example.com/jobs/blocked"
    expired_url = "https://careers.example.com/jobs/expired"
    jobs = [
        _job(
            "apify-jobspipe",
            "manual",
            manual_url,
            title="Manual Recovery Engineer",
        ),
        _job(
            "apify-all-jobs",
            "expired",
            expired_url,
            title="Expired Engineer",
        ),
    ]
    container = _container(
        tmp_path,
        "sync-recovery.db",
        background_worker_enabled=False,
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        discovery_provider=StaticDiscoveryProvider(jobs),
        job_fetcher=SequenceFetcher(
            UrlIngestionError(
                "robots.txt blocks automatic import",
                kind=UrlFailureKind.BLOCKED,
            ),
            UrlIngestionError(
                "the job has expired",
                kind=UrlFailureKind.EXPIRED,
                http_status=404,
            ),
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        client.post("/profile/start", follow_redirects=False)
        search = client.get("/explore?q=embedded")
        assert "Manual Recovery Engineer" in search.text
        assert "Expired Engineer" in search.text

        saved = client.post(
            "/explore/save",
            data={"selected_urls": [manual_url, expired_url], "destination": "archive"},
            follow_redirects=False,
        )
        page = client.get(saved.headers["location"])

    assert saved.status_code == 303
    assert urlsplit(saved.headers["location"]).path == "/explore"
    assert "Manual Recovery Engineer" in page.text
    assert "Needs pasted text" in page.text
    assert 'data-source-readiness="manual_required"' in page.text
    assert "Expired Engineer" not in page.text
    # The recoverable discovery stays in the Explore snapshot, not in the
    # local Archive slot count as a failed corpus record.
    assert container.repository.list_records() == []


def test_background_import_keeps_failed_source_in_completed_explore_snapshot(
    tmp_path: Path,
) -> None:
    manual_url = "https://careers.example.com/jobs/unreachable"
    expired_url = "https://careers.example.com/jobs/background-expired"
    manual_job = _job(
        "apify-jobspipe",
        "unreachable",
        manual_url,
        title="Still Visible Engineer",
        source_providers=["apify-jobspipe", "exa-fallback"],
    )
    expired_job = _job(
        "apify-all-jobs",
        "background-expired",
        expired_url,
        title="Background Expired Engineer",
    )
    container = _container(
        tmp_path,
        "background-recovery.db",
        background_worker_enabled=True,
    )
    workspace, search_task = _save_completed_search(container, [manual_job, expired_job])
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            UrlIngestionError(
                "the employer page could not be reached",
                kind=UrlFailureKind.UNREACHABLE,
            ),
            UrlIngestionError(
                "the employer page says this job expired",
                kind=UrlFailureKind.EXPIRED,
                http_status=404,
            ),
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/explore/save",
            data={
                "selected_urls": [manual_url, expired_url],
                "destination": "archive",
                "source_explore_task_id": str(search_task.id),
            },
            follow_redirects=False,
        )
        task_id = urlsplit(response.headers["location"]).path.rsplit("/", 1)[-1]
        deadline = monotonic() + 3
        status = None
        while monotonic() < deadline:
            status = client.get(f"/tasks/{task_id}/status").json()
            if status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)
        page = client.get("/explore")

    assert response.status_code == 303
    assert status is not None
    assert status["status"] == BackgroundTaskStatus.SUCCEEDED.value
    assert "Still Visible Engineer" in page.text
    assert "Needs pasted text" in page.text
    assert "Background Expired Engineer" not in page.text
    assert 'Show results supplied by JobsPipe via Apify" checked' in page.text
    assert 'Show results supplied by Exa" checked' in page.text
    restored = container.explore_searches.latest_completed(workspace.id)
    assert restored is not None
    assert len(restored.results) == 1
    assert restored.results[0].source_readiness == SourceReadiness.MANUAL_REQUIRED
    assert restored.results[0].effective_source_providers == (
        "apify-jobspipe",
        "exa-fallback",
    )
    assert container.repository.count_records() == 0


def test_background_multiple_failures_mark_only_the_origin_explore_snapshot(
    tmp_path: Path,
) -> None:
    first_url = "https://careers.example.com/jobs/origin-one"
    second_url = "https://careers.example.com/jobs/origin-two"
    newer_url = "https://careers.example.com/jobs/newer"
    origin_jobs = [
        _job("you-web", "origin-one", first_url, title="Origin One Engineer"),
        _job("you-web", "origin-two", second_url, title="Origin Two Engineer"),
    ]
    newer_job = _job("brave-web", "newer", newer_url, title="Newer Engineer")
    container = _container(
        tmp_path,
        "exact-origin-recovery.db",
        background_worker_enabled=True,
    )
    _workspace, origin_task = _save_completed_search(container, origin_jobs)
    _workspace, newer_task = _save_completed_search(container, [newer_job])
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            UrlIngestionError("first source unavailable", kind=UrlFailureKind.UNREACHABLE),
            UrlIngestionError("second source unavailable", kind=UrlFailureKind.UNREACHABLE),
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/explore/save",
            data={
                "selected_urls": [first_url, second_url],
                "destination": "archive",
                "source_explore_task_id": str(origin_task.id),
            },
            follow_redirects=False,
        )
        import_task_id = urlsplit(response.headers["location"]).path.rsplit("/", 1)[-1]
        deadline = monotonic() + 3
        status = None
        while monotonic() < deadline:
            status = client.get(f"/tasks/{import_task_id}/status").json()
            if status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)
        origin_page = client.get(status["result_url"])

    assert status is not None
    assert status["status"] == BackgroundTaskStatus.SUCCEEDED.value
    result_url = urlsplit(status["result_url"])
    assert result_url.path == "/explore"
    assert parse_qs(result_url.query)["source_explore_task_id"] == [str(origin_task.id)]
    assert "Origin One Engineer" in origin_page.text
    assert "Origin Two Engineer" in origin_page.text
    assert "Needs pasted text" in origin_page.text
    assert "Newer Engineer" not in origin_page.text
    origin = container.explore_searches.get(origin_task.id)
    newer = container.explore_searches.get(newer_task.id)
    assert origin is not None
    assert [job.source_readiness for job in origin.results] == [
        SourceReadiness.MANUAL_REQUIRED,
        SourceReadiness.MANUAL_REQUIRED,
    ]
    assert newer is not None
    assert newer.results[0].source_readiness == SourceReadiness.PROVIDER_LISTED


def test_single_failed_manual_import_redirects_to_prefilled_add_panel(tmp_path: Path) -> None:
    source_url = "https://careers.example.com/jobs/single-manual"
    container = _container(
        tmp_path,
        "single-manual-recovery.db",
        background_worker_enabled=True,
    )
    _workspace, origin_task = _save_completed_search(
        container,
        [_job("you-web", "single-manual", source_url, title="Single Manual Engineer")],
    )
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=SequenceFetcher(
            UrlIngestionError("source unavailable", kind=UrlFailureKind.UNREACHABLE)
        ),
        job_extractor=JobExtractor(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/explore/save",
            data={
                "selected_urls": source_url,
                "destination": "archive",
                "source_explore_task_id": str(origin_task.id),
            },
            follow_redirects=False,
        )
        import_task_id = urlsplit(response.headers["location"]).path.rsplit("/", 1)[-1]
        deadline = monotonic() + 3
        status = None
        while monotonic() < deadline:
            status = client.get(f"/tasks/{import_task_id}/status").json()
            if status["status"] in {"succeeded", "failed"}:
                break
            sleep(0.02)

    assert status is not None
    assert status["status"] == BackgroundTaskStatus.SUCCEEDED.value
    result_url = urlsplit(status["result_url"])
    assert result_url.path == "/add"
    assert parse_qs(result_url.query) == {"url": [source_url], "manual": ["true"]}
    assert result_url.fragment == "manual-job-input"


def test_explore_save_rejects_a_snapshot_owned_by_another_workspace(tmp_path: Path) -> None:
    source_url = "https://careers.example.com/jobs/foreign-origin"
    container = _container(tmp_path, "origin-ownership.db", background_worker_enabled=False)
    _first_workspace, foreign_task = _save_completed_search(
        container,
        [_job("you-web", "foreign", source_url, title="Foreign Engineer")],
    )
    container.workspaces.create()

    with TestClient(create_app(container, data_directory=tmp_path / "data")) as client:
        response = client.post(
            "/explore/save",
            data={
                "selected_urls": source_url,
                "destination": "archive",
                "source_explore_task_id": str(foreign_task.id),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).path == "/explore"
    assert "not+available+in+this+workspace" in response.headers["location"]
    assert container.repository.count_records() == 0
