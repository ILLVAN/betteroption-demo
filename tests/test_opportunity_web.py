from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from betteroption.access import ProductAccessPolicy
from betteroption.container import ApplicationContainer
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.job_repository import JobAvailability, JobObservationKind
from betteroption.settings import Settings
from betteroption.url_ingestion import (
    FetchedDocument,
    UrlFailureKind,
    UrlIngestionError,
)
from betteroption.web import create_app


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
URL = "https://careers.example.com/jobs/platform-123"


class SequenceFetcher:
    def __init__(self, *results: FetchedDocument | Exception) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchedDocument:
        self.calls.append(url)
        if not self.results:
            raise AssertionError("fetch called more often than expected")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class JobExtractor:
    model = "job-test-model"

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[str] = []

    def extract(self, source_text: str, **metadata):
        self.calls.append(source_text)
        if self.failure:
            raise self.failure
        version = "v2" if "version two" in source_text else "v1"
        return JobExtraction(
            title=f"Platform Engineer {version}",
            company="Example Product Studio",
            location="Leipzig",
            summary="Build reliable internal developer tools.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="Python",
                    kind="requirement",
                    evidence_quote="Python",
                )
            ],
        ).to_job_posting(source_text=source_text, **metadata)


def document(
    text: str = (
        "Example Product Studio needs Python for a Platform Engineer role, "
        "building reliable internal developer tools, version one."
    ),
    *,
    checked_at: datetime = NOW,
    url: str = URL,
) -> FetchedDocument:
    return FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=text,
        fetched_at=checked_at,
    )


def build_container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'opportunities.db').as_posix()}",
            auth_mode="local",
        )
    )


def build_client(
    tmp_path: Path,
    fetcher: SequenceFetcher,
    extractor: JobExtractor,
) -> tuple[TestClient, ApplicationContainer]:
    container = build_container(tmp_path)
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        job_fetcher=fetcher,
        job_extractor=extractor,
    )
    return TestClient(app), container


def detail_path(response) -> str:
    assert response.status_code == 303
    path = urlsplit(response.headers["location"]).path
    assert path.startswith("/jobs/")
    return path


def redirect_message(response, key: str) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)[key][0]


def test_opportunity_inbox_imports_a_verified_url_and_shows_its_source(
    tmp_path: Path,
) -> None:
    fetcher = SequenceFetcher(document())
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)

    response = client.post(
        "/jobs/import",
        data={"url": URL},
        follow_redirects=False,
    )
    path = detail_path(response)
    detail = client.get(path)
    inbox = client.get("/jobs")

    assert "Job verified, extracted, and added" in redirect_message(response, "notice")
    assert detail.status_code == 200
    assert "Platform Engineer v1" in detail.text
    assert "Open verified job page" in detail.text
    assert URL in detail.text
    assert "Saved versions" in detail.text
    assert inbox.status_code == 200
    assert "Platform Engineer v1" in inbox.text
    assert 'class="opportunity-card selectable-card"' in inbox.text
    assert 'class="card-body-link card-link"' in inbox.text
    assert "Everything you chose to keep" in inbox.text
    assert "1/25" in inbox.text
    assert container.access_policy.free_match_result_limit == 25
    assert container.access_policy.max_stored_jobs == 25
    assert len(container.repository.list_records()) == 1
    assert len(extractor.calls) == 1


def test_refresh_reuses_unchanged_extraction_and_records_the_check(
    tmp_path: Path,
) -> None:
    fetcher = SequenceFetcher(document(), document(checked_at=NOW + timedelta(hours=1)))
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)
    imported = client.post("/jobs/import", data={"url": URL}, follow_redirects=False)
    path = detail_path(imported)
    record_id = path.rsplit("/", 1)[-1]

    refreshed = client.post(
        f"/jobs/{record_id}/refresh",
        follow_redirects=False,
    )
    detail = client.get(detail_path(refreshed))
    record = container.repository.list_records()[0]

    assert "already known" in redirect_message(refreshed, "notice")
    assert len(extractor.calls) == 1
    assert record.revision_count == 1
    assert [
        observation.kind for observation in container.repository.list_observations(record.id)
    ] == [JobObservationKind.NEW, JobObservationKind.UNCHANGED]
    assert "Unchanged" in detail.text


def test_changed_job_creates_visible_revision_history(tmp_path: Path) -> None:
    changed = document(
        "Example Product Studio needs Python for a Platform Engineer role, "
        "building reliable internal developer tools, version two.",
        checked_at=NOW + timedelta(hours=2),
    )
    fetcher = SequenceFetcher(document(), changed)
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)
    first = client.post("/jobs/import", data={"url": URL}, follow_redirects=False)
    path = detail_path(first)
    record_id = path.rsplit("/", 1)[-1]

    changed_response = client.post(
        f"/jobs/{record_id}/refresh",
        follow_redirects=False,
    )
    detail = client.get(detail_path(changed_response))
    record = container.repository.list_records()[0]

    assert "advertisement changed" in redirect_message(changed_response, "notice")
    assert "Platform Engineer v2" in detail.text
    assert "Version 2" in detail.text
    assert "Version 1" in detail.text
    assert record.revision_count == 2
    assert len(extractor.calls) == 2


def test_http_404_is_kept_as_a_closed_inbox_item(tmp_path: Path) -> None:
    failure = UrlIngestionError(
        "job page returned HTTP 404",
        kind=UrlFailureKind.EXPIRED,
        http_status=404,
    )
    fetcher = SequenceFetcher(failure)
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)

    response = client.post("/jobs/import", data={"url": URL}, follow_redirects=False)
    detail = client.get(detail_path(response))
    closed = client.get("/jobs?status=expired")
    record = container.repository.list_records()[0]

    assert "closed+or+expired" in response.headers["location"]
    assert detail.status_code == 200
    assert "Closed job link" in detail.text
    assert "HTTP 404" in detail.text
    assert "Check this link again" in detail.text
    assert "Closed job link" in closed.text
    assert record.availability == JobAvailability.EXPIRED
    assert record.revision_count == 0
    assert extractor.calls == []


def test_extraction_failure_is_visible_and_retryable(tmp_path: Path) -> None:
    fetcher = SequenceFetcher(document())
    extractor = JobExtractor(failure=RuntimeError("provider temporarily unavailable"))
    client, container = build_client(tmp_path, fetcher, extractor)

    response = client.post("/jobs/import", data={"url": URL}, follow_redirects=False)
    detail = client.get(detail_path(response))
    attention = client.get("/jobs?status=needs_attention")
    record = container.repository.list_records()[0]

    assert "could+not+be+extracted" in response.headers["location"]
    assert "Job needs extraction" in detail.text
    assert "provider temporarily unavailable" in detail.text
    assert "Job needs extraction" in attention.text
    assert record.availability == JobAvailability.NEEDS_ATTENTION
    assert record.last_observation_kind == JobObservationKind.EXTRACTION_FAILED
    assert record.last_http_status == 200


def test_copied_job_text_is_rejected_before_fetch(tmp_path: Path) -> None:
    fetcher = SequenceFetcher()
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)

    response = client.post(
        "/jobs/import",
        data={"url": "Platform Engineer with Python and remote work"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).path == "/jobs"
    assert "job+URL+must+use+http" in response.headers["location"]
    assert fetcher.calls == []
    assert container.repository.list_records() == []


def test_free_workspace_stores_twenty_five_jobs_and_confirmed_deletion_frees_a_slot(
    tmp_path: Path,
) -> None:
    urls = [f"https://careers.example.com/jobs/slot-{index}" for index in range(26)]
    fetcher = SequenceFetcher(*(document(url=url) for url in urls))
    extractor = JobExtractor()
    client, container = build_client(tmp_path, fetcher, extractor)
    workspace_response = client.post("/profile/start", follow_redirects=False)
    workspace_id = workspace_response.headers["location"].rsplit("/", 1)[-1]

    for index, url in enumerate(urls[:25], start=1):
        response = client.post(
            "/add/jobs",
            data={
                "url": url,
                "positives": f"Positive signal {index}",
                "negatives": "Long commute",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"{index}%2F25" in response.headers["location"]

    rejected = client.post(
        "/add/jobs",
        data={"url": urls[25]},
        follow_redirects=False,
    )
    assert "stores+up+to+25+jobs" in rejected.headers["location"]
    assert len(fetcher.calls) == 25
    assert container.repository.count_records() == 25
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert len(workspace.session.profile.reference_jobs) == 25

    deleted_record = container.repository.list_records()[-1]
    deleted_job = container.repository.get_current_job(deleted_record.id)
    assert deleted_job is not None
    canonical_copy = tmp_path / "data" / "jobs" / f"job-{deleted_job.id}.json"
    assert canonical_copy.exists()

    refused = client.post(
        f"/jobs/{deleted_record.id}/delete",
        follow_redirects=False,
    )
    assert "Confirm+deletion" in refused.headers["location"]
    assert container.repository.count_records() == 25

    deleted = client.post(
        f"/jobs/{deleted_record.id}/delete",
        data={"confirm_delete": "true"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert "One+slot+is+free+again" in deleted.headers["location"]
    assert container.repository.count_records() == 24
    assert not canonical_copy.exists()
    workspace = container.workspaces.get(workspace_id)
    assert workspace is not None
    assert len(workspace.session.profile.reference_jobs) == 24

    replacement = client.post(
        "/add/jobs",
        data={"url": urls[25], "positives": "Replacement role"},
        follow_redirects=False,
    )
    assert replacement.status_code == 303
    assert "25%2F25" in replacement.headers["location"]
    assert container.repository.count_records() == 25
    assert len(fetcher.calls) == 26


def test_page_story_has_one_job_input_archive_only_opportunities_and_restart_controls(
    tmp_path: Path,
) -> None:
    fetcher = SequenceFetcher()
    extractor = JobExtractor()
    client, _container = build_client(tmp_path, fetcher, extractor)
    started = client.post("/profile/start", follow_redirects=False)
    profile_path = started.headers["location"]

    profile = client.get(profile_path)
    add = client.get("/add")
    matches = client.get("/matches")
    archive = client.get("/jobs")
    legacy_reference_page = client.get(
        f"{profile_path}/references",
        follow_redirects=False,
    )

    assert "Start an entirely new Compass" in profile.text
    assert "Start from scratch" in profile.text
    assert ">Compass</a>" in profile.text
    assert ">My compass</a>" not in profile.text
    assert 'action="http://testserver/add/jobs"' in add.text
    assert "What appeals to you?" in add.text
    assert "What does not fit?" in add.text
    assert "Allowed learning scope" in add.text
    assert 'action="http://testserver/add/jobs"' not in matches.text
    assert "/jobs/import" not in archive.text
    assert ">Archive</a>" in archive.text
    assert ">Match</a>" in matches.text
    assert ">Explore</a>" in matches.text
    assert "Change one thing without starting over" in profile.text
    assert 'data-suggestion-target="section-input-direction"' in profile.text
    assert "Target role and seniority" in profile.text
    assert "brand-wave-pink" in profile.text
    assert "brand-wave-teal" in profile.text
    assert legacy_reference_page.status_code == 303
    assert legacy_reference_page.headers["location"].startswith("/add?notice=")


def test_archive_bulk_delete_removes_complete_job_aggregates_and_references(
    tmp_path: Path,
) -> None:
    urls = [f"https://careers.example.com/jobs/bulk-{index}" for index in range(2)]
    fetcher = SequenceFetcher(*(document(url=url) for url in urls))
    client, container = build_client(tmp_path, fetcher, JobExtractor())
    client.post("/profile/start", follow_redirects=False)

    for url in urls:
        response = client.post(
            "/add/jobs",
            data={"url": url, "positives": "Interesting product work"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    records = container.repository.list_records()
    archive = client.get("/jobs")
    assert "/jobs/bulk-delete" in archive.text
    assert "Delete selected and free slots" in archive.text
    assert 'name="confirm_delete" value="true"' in archive.text
    assert 'class="opportunity-card selectable-card"' in archive.text
    assert 'class="card-selector delete-selector"' in archive.text
    assert "Delete job" in archive.text
    assert all(str(record.id) in archive.text for record in records)

    refused = client.post(
        "/jobs/bulk-delete",
        data={"record_ids": [str(record.id) for record in records]},
        follow_redirects=False,
    )
    assert "Confirm+complete+deletion" in refused.headers["location"]
    assert container.repository.count_records() == 2

    deleted = client.post(
        "/jobs/bulk-delete",
        data={
            "record_ids": [str(record.id) for record in records],
            "confirm_delete": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert "2+slot%28s%29+are+free+again" in deleted.headers["location"]
    assert container.repository.count_records() == 0
    workspace = container.workspaces.latest()
    assert workspace is not None
    assert workspace.session.profile.reference_jobs == []


def test_matching_reference_can_delete_its_complete_saved_job(tmp_path: Path) -> None:
    fetcher = SequenceFetcher(document())
    client, container = build_client(tmp_path, fetcher, JobExtractor())
    client.post("/profile/start", follow_redirects=False)
    client.post(
        "/add/jobs",
        data={"url": URL, "positives": "Interesting product work"},
        follow_redirects=False,
    )
    workspace = container.workspaces.latest()
    assert workspace is not None
    reference = workspace.session.profile.reference_jobs[0]

    add = client.get("/add")
    assert f"/add/references/{reference.id}/delete" in add.text
    assert "Delete this saved job" in add.text

    deleted = client.post(
        f"/add/references/{reference.id}/delete",
        data={"confirm_delete": "true"},
        follow_redirects=False,
    )

    assert deleted.status_code == 303
    assert "archived+job%2C+match+history" in deleted.headers["location"]
    assert container.repository.count_records() == 0
    workspace = container.workspaces.latest()
    assert workspace is not None
    assert workspace.session.profile.reference_jobs == []


def test_legacy_matching_post_aliases_remain_compatible(tmp_path: Path) -> None:
    fetcher = SequenceFetcher(document())
    client, container = build_client(tmp_path, fetcher, JobExtractor())
    client.post("/profile/start", follow_redirects=False)

    saved = client.post(
        "/matches/jobs",
        data={"url": URL, "positives": "Interesting product work"},
        follow_redirects=False,
    )
    workspace = container.workspaces.latest()
    assert workspace is not None
    reference = workspace.session.profile.reference_jobs[0]
    assert saved.status_code == 303
    assert urlsplit(saved.headers["location"]).path == "/add"

    deleted = client.post(
        f"/matches/references/{reference.id}/delete",
        data={"confirm_delete": "true"},
        follow_redirects=False,
    )

    assert deleted.status_code == 303
    assert urlsplit(deleted.headers["location"]).path == "/add"
    assert container.repository.count_records() == 0


def test_expired_explore_selection_is_not_saved_or_matched(tmp_path: Path) -> None:
    failure = UrlIngestionError(
        "the job URL appears to be expired or unavailable",
        kind=UrlFailureKind.EXPIRED,
        http_status=200,
    )
    fetcher = SequenceFetcher(failure)
    client, container = build_client(tmp_path, fetcher, JobExtractor())
    with client:
        client.post("/profile/start", follow_redirects=False)
        response = client.post(
            "/explore/save",
            data={"selected_urls": URL, "destination": "matching"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        task_path = urlsplit(response.headers["location"]).path
        assert task_path.startswith("/tasks/")
        deadline = monotonic() + 5
        status = None
        while monotonic() < deadline:
            status = client.get(f"{task_path}/status").json()
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            sleep(0.02)

        assert status is not None
        assert status["status"] == "succeeded", status
        assert urlsplit(status["result_url"]).path == "/explore"
        assert "expired+or+unavailable" in status["result_url"]
    assert container.repository.count_records() == 0
    workspace = container.workspaces.latest()
    assert workspace is not None
    assert container.results.latest_run(workspace.id) is None


def test_explore_slot_overflow_is_rejected_before_any_selected_url_is_fetched(
    tmp_path: Path,
) -> None:
    first_url = "https://careers.example.com/jobs/existing"
    second_url = "https://careers.example.com/jobs/new"
    fetcher = SequenceFetcher(document(url=first_url), document(url=second_url))
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'slots.db').as_posix()}",
            auth_mode="local",
        ),
        access_policy=ProductAccessPolicy(
            free_match_result_limit=1,
            max_stored_jobs=1,
            exact_route_match_limit=1,
        ),
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            job_fetcher=fetcher,
            job_extractor=JobExtractor(),
        )
    )
    client.post("/profile/start", follow_redirects=False)
    client.post("/add/jobs", data={"url": first_url}, follow_redirects=False)

    rejected = client.post(
        "/explore/save",
        data={"selected_urls": second_url, "destination": "matching"},
        follow_redirects=False,
    )

    assert rejected.status_code == 303
    assert "only+0+remain" in rejected.headers["location"]
    assert "Nothing+was+added" in rejected.headers["location"]
    assert fetcher.calls == [first_url]
    assert container.repository.count_records() == 1
