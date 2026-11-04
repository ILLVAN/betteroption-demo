from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.job_repository import JobObservationKind
from betteroption.matching import MatchDisposition, MatchResult, MatchRun, save_match_run
from betteroption.posting_date import PostingDateAssessment, PostingFreshness
from betteroption.session import new_session, save_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
URL = "https://jobs.example.com/embedded/123"


def build_container(tmp_path: Path) -> ApplicationContainer:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'dashboard.db').as_posix()}",
        auth_mode="local",
    )
    return ApplicationContainer(settings)


def seed_opportunity(
    container: ApplicationContainer,
    *,
    slug: str = "123",
    title: str = "Embedded Engineer",
):
    url = f"https://jobs.example.com/embedded/{slug}"
    source = "Acme needs Python for an Embedded Engineer in Frankfurt."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobExtraction(
        title=title,
        company="Acme",
        location="Frankfurt",
        summary="Build embedded products with a small engineering team.",
        facts=[
            JobFactDraft(
                key="skill.name",
                value="Python",
                kind="requirement",
                evidence_quote="Python",
            )
        ],
    ).to_job_posting(
        source_text=source,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_http_status=200,
        url_checked_at=NOW,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return record, job


def test_empty_dashboard_has_a_calm_actionable_home(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(tmp_path), data_directory=tmp_path / "data"))

    response = client.get("/")

    assert response.status_code == 200
    assert "Welcome home." in response.text
    assert "Your compass is ready to be drawn" in response.text
    assert '<main id="main-content"' in response.text
    assert 'class="skip-link"' in response.text
    assert 'aria-label="Primary navigation"' in response.text
    assert "Provider use today" not in response.text
    assert "/operations" not in response.text


def test_dashboard_lists_a_verified_job_and_saved_match(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    record, job = seed_opportunity(container)
    data = tmp_path / "data"
    save_session(new_session(), data / "sessions")
    save_match_run(
        MatchRun(
            profile_id=new_session().profile.id,
            results=[
                MatchResult(
                    job_id=job.id,
                    job_url=job.source_url,
                    url_status=job.url_status,
                    url_http_status=job.url_http_status,
                    url_verified_at=job.url_checked_at,
                    score=82,
                    hard_evidence_coverage=75,
                    disposition=MatchDisposition.TOP,
                    hard_violations=0,
                    posting_date=PostingDateAssessment(
                        automatic_date=date(2025, 12, 1),
                        effective_date=date(2025, 12, 1),
                        automatic_freshness=PostingFreshness.OLD,
                        freshness=PostingFreshness.OLD,
                        evaluated_on=NOW.date(),
                        score_adjustment=-4,
                    ),
                )
            ],
        ),
        data / "matches",
    )
    client = TestClient(create_app(container, data_directory=data))

    home = client.get("/")
    listing = client.get("/jobs?status=live")
    detail = client.get(f"/jobs/{record.id}")

    assert home.status_code == 200
    assert "Embedded Engineer" in home.text
    assert "Strong fit" in home.text
    assert "82" in home.text
    assert "data-opportunity-carousel" in home.text
    assert "data-carousel-previous" in home.text
    assert "data-carousel-next" in home.text
    assert 'data-posting-freshness="old"' in home.text
    assert "> Old</span>" in home.text
    assert listing.status_code == 200
    assert "Open now" in listing.text
    assert detail.status_code == 200
    assert URL in detail.text
    assert "Open verified job page" in detail.text
    assert "Fresh and traceable" in detail.text


def test_home_carousel_contains_every_current_top_and_stretch_but_not_blocked(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    seeded = [
        seed_opportunity(container, slug=str(index), title=f"Role {index}") for index in range(1, 6)
    ]
    data = tmp_path / "data"
    session = new_session()
    save_session(session, data / "sessions")
    dispositions = [
        MatchDisposition.TOP,
        MatchDisposition.STRETCH,
        MatchDisposition.TOP,
        MatchDisposition.STRETCH,
        MatchDisposition.BLOCKED,
    ]
    save_match_run(
        MatchRun(
            profile_id=session.profile.id,
            results=[
                MatchResult(
                    job_id=job.id,
                    job_url=job.source_url,
                    url_status=job.url_status,
                    url_http_status=job.url_http_status,
                    url_verified_at=job.url_checked_at,
                    score=90 - index,
                    hard_evidence_coverage=75,
                    disposition=dispositions[index],
                    hard_violations=1 if dispositions[index] == MatchDisposition.BLOCKED else 0,
                    posting_date=(
                        PostingDateAssessment(
                            automatic_date=date(2025, 12, 1),
                            effective_date=date(2025, 12, 1),
                            automatic_freshness=PostingFreshness.OLD,
                            freshness=PostingFreshness.OLD,
                            evaluated_on=NOW.date(),
                            score_adjustment=-4,
                        )
                        if index == 0
                        else None
                    ),
                )
                for index, (_record, job) in enumerate(seeded)
            ],
        ),
        data / "matches",
    )
    client = TestClient(create_app(container, data_directory=data))

    home = client.get("/")

    assert home.status_code == 200
    for index in range(1, 5):
        assert f"Role {index}" in home.text
    assert "Role 5" not in home.text
    assert home.text.count('class="opportunity-card"') == 4
    assert 'data-posting-freshness="old"' in home.text
    assert "> Old</span>" in home.text
    assert "Showing opportunities" not in home.text  # populated by the accessible JS status


def test_dashboard_filters_validate_status_and_keep_delivery_read_only(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(tmp_path), data_directory=tmp_path / "data"))

    assert client.get("/jobs?status=unknown").status_code == 400
    assert client.post("/jobs").status_code == 405
    assert client.post("/").status_code == 405


def test_dashboard_health_and_local_styles_are_available(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(tmp_path), data_directory=tmp_path / "data"))

    health = client.get("/health")
    styles = client.get("/static/app.css")
    script = client.get("/static/app.js")

    assert health.json() == {
        "status": "ok",
        "version": "0.7.2k",
        "mode": "match-results",
    }
    assert client.get("/health/live").json() == {
        "status": "live",
        "version": "0.7.2k",
    }
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["database"] == "sqlite"
    assert styles.status_code == 200
    assert "prefers-reduced-motion" in styles.text
    assert ":focus-visible" in styles.text
    assert script.status_code == 200
    assert "data-autogrow" in script.text
    assert "data-opportunity-carousel" in script.text

    home = client.get("/")
    assert "<built-in method copy" not in home.text
    assert "/static/app.css?v=0.7.2k" in home.text
    assert "/static/app.js?v=0.7.2k" in home.text


def test_unknown_opportunity_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(tmp_path), data_directory=tmp_path / "data"))

    response = client.get("/jobs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 404


def test_browser_errors_return_a_friendly_way_home(tmp_path: Path) -> None:
    client = TestClient(create_app(build_container(tmp_path), data_directory=tmp_path / "data"))

    response = client.get(
        "/jobs/11111111-1111-1111-1111-111111111111",
        headers={"accept": "text/html"},
    )

    assert response.status_code == 404
    assert "A small detour" in response.text
    assert "Return home" in response.text
