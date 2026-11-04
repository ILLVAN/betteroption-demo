from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.job_context import EmployerContextService, EmployerKind
from betteroption.job_overrides import JobEvidenceOverrideKind
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
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


PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
JOB_URL = "https://careers.example.com/jobs/evidence-workflow"


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'web-i.db').as_posix()}",
            app_environment="local",
            auth_mode="accounts",
            registration_mode="open",
            account_personas_enabled=True,
            background_worker_enabled=False,
            employer_homepage_research=False,
            transitous_enabled=False,
            valhalla_enabled=False,
            osm_geocoder_enabled=False,
        )
    )


def _register(client: TestClient) -> None:
    response = client.post(
        "/register",
        data={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": PASSWORD,
            "accept_terms": "yes",
            "acknowledge_privacy": "yes",
            "confirm_adult": "yes",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _seed_workspace_and_job(container: ApplicationContainer):
    (account,) = container.accounts.list_accounts()
    (persona,) = container.personas.list_for_account(account.id)
    session = new_session()
    session.profile.facts = [
        ProfileFact(
            key="skill.demonstrated",
            value="Python",
            level=RequirementLevel.OPEN,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(section=ProfileSection.EXPERIENCE, text="Python"),
        )
    ]
    workspace = container.workspaces.create(
        session,
        account_id=account.id,
        persona_id=persona.id,
    )
    source = (
        "Example Products seeks a Product Designer. Kotlin is required. Date posted: 2026-07-20."
    )
    # Reachability freshness is operational state, not the historical posting
    # date under test.  Keep this check current so the fixture does not cross
    # the production 24-hour refresh boundary and attempt to resolve the
    # intentionally fictional example.com host.
    checked_at = datetime.now(timezone.utc)
    document = FetchedDocument(
        requested_url=JOB_URL,
        final_url=JOB_URL,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=checked_at,
    )
    job = JobPosting(
        title="Product Designer",
        company="Example Products GmbH",
        location="Berlin",
        summary="Design accessible products.",
        source_type=JobSourceType.URL_TEXT,
        source_name=JOB_URL,
        source_url=JOB_URL,
        requested_url=JOB_URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=checked_at,
        source_text=source,
        observed_at=NOW,
        facts=[
            JobFact(
                key="skill.name",
                value="Kotlin",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Kotlin",
            )
        ],
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        employer_context=EmployerContextService(research_homepages=False),
        job_overrides=container.job_overrides,
    ).run(workspace)
    return account, persona, workspace, record


def _store_related_job(
    container: ApplicationContainer,
    template_record,
    *,
    slug: str,
    company: str,
):
    template = container.repository.get_current_job(template_record.id)
    assert template is not None
    url = f"https://careers.example.com/jobs/{slug}"
    checked_at = datetime.now(timezone.utc)
    source_text = f"{company} advertises {slug}. {template.source_text}"
    job = JobPosting.model_validate(
        {
            **template.model_dump(),
            "id": uuid4(),
            "title": slug.replace("-", " ").title(),
            "company": company,
            "source_name": url,
            "source_url": url,
            "requested_url": url,
            "url_checked_at": checked_at,
            "observed_at": checked_at,
            "source_text": source_text,
            "content_hash": "",
        }
    )
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=job.source_text,
        fetched_at=checked_at,
    )
    return container.repository.store_revision(document, job, JobObservationKind.NEW)


def test_job_detail_saves_private_stars_and_posting_date_override(tmp_path: Path) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, persona, workspace, record = _seed_workspace_and_job(container)

        page = client.get(f"/jobs/{record.id}")
        assert page.status_code == 200
        assert 'id="employer-reputation-rating"' in page.text
        assert "Posting date" in page.text
        assert "20 Jul 2026" in page.text
        assert "Also update my Compass from skill changes" in page.text

        rated = client.post(
            f"/jobs/{record.id}/employer-rating",
            data={"stars": "4"},
            follow_redirects=False,
        )
        corrected = client.post(
            f"/jobs/{record.id}/evidence/posting-date",
            data={"posting_date": "2025-10-01"},
            follow_redirects=False,
        )

        assert rated.status_code == 303
        assert corrected.status_code == 303
        assert "rematch=1" not in corrected.headers["location"]
        assert "compatibility+score+was+updated" in corrected.headers["location"]
        rating = container.employer_reputation.get(
            persona.id,
            "example products g.m.b.h.",
            account_id=account.id,
        )
        assert rating is not None
        assert rating.stars == 4
        (override,) = container.job_overrides.list_for_job(workspace.id, record.id)
        assert override.kind == JobEvidenceOverrideKind.POSTING_DATE
        assert override.posting_date.isoformat() == "2025-10-01"

        refreshed = client.get(f"/jobs/{record.id}")
        assert "4 of 5 stars · private to this persona" in refreshed.text
        assert "Saved correction" in refreshed.text

        cleared = client.post(
            f"/jobs/{record.id}/employer-rating/clear",
            follow_redirects=False,
        )
        restored = client.post(
            f"/jobs/{record.id}/evidence/delete",
            data={"kind": "posting_date", "target_key": "posting_date"},
            follow_redirects=False,
        )
        assert cleared.status_code == 303
        assert restored.status_code == 303
        assert (
            container.employer_reputation.get(
                persona.id,
                "Example Products GmbH",
                account_id=account.id,
            )
            is None
        )
        assert container.job_overrides.list_for_job(workspace.id, record.id) == []


def test_job_rating_json_api_keeps_zero_distinct_from_unrated(tmp_path: Path) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, persona, _workspace, record = _seed_workspace_and_job(container)

        for path in ("/", "/jobs", "/matches"):
            page = client.get(path)
            assert page.status_code == 200
            assert "Your ratings" in page.text
            assert f"/jobs/{record.id}/job-rating" in page.text
            assert f"/jobs/{record.id}/employer-rating" in page.text
            assert "data-employer-rating-control" in page.text
            assert 'aria-label="0 of 5 job stars; strongest compatibility reduction"' in page.text
            assert (
                'aria-label="0 of 5 employer stars; strongest compatibility reduction"' in page.text
            )

        zero_rated = client.post(
            f"/jobs/{record.id}/job-rating",
            data={"stars": "0"},
            headers={"Accept": "application/json"},
        )

        assert zero_rated.status_code == 200
        assert zero_rated.json()["stars"] == 0
        assert zero_rated.json()["needs_rematch"] is False
        assert zero_rated.json()["rematch_url"] is None
        assert zero_rated.json()["disposition"] == "stretch"
        assert zero_rated.json()["projection_status"] == "updated"
        assert zero_rated.json()["rating_record_ids"] == [str(record.id)]
        assert zero_rated.json()["score_updates"] == [
            {
                "record_id": str(record.id),
                "score": 0,
                "disposition": "stretch",
                "disposition_label": "Stretch match",
            }
        ]
        assert "existing evidence" not in zero_rated.json()["message"].casefold()

        employer = client.post(
            f"/jobs/{record.id}/employer-rating",
            data={"stars": "4"},
            headers={"Accept": "application/json"},
        )
        assert employer.status_code == 200
        assert employer.json()["stars"] == 4
        assert employer.json()["needs_rematch"] is False
        assert employer.json()["score"] is not None
        assert employer.json()["rating_record_ids"] == [str(record.id)]
        assert employer.json()["score_updates"][0]["record_id"] == str(record.id)
        assert "existing evidence" not in employer.json()["message"].casefold()
        rated_archive = client.get("/jobs")
        assert 'data-current-rating="0"' in rated_archive.text
        assert ">0/5<" in rated_archive.text
        assert (
            container.job_ratings.get(
                persona.id,
                record.id,
                account_id=account.id,
            ).stars
            == 0
        )

        cleared = client.post(
            f"/jobs/{record.id}/job-rating/clear",
            headers={"Accept": "application/json"},
        )

        assert cleared.status_code == 200
        assert cleared.json()["stars"] is None
        assert (
            container.job_ratings.get(
                persona.id,
                record.id,
                account_id=account.id,
            )
            is None
        )


def test_employer_rating_json_returns_all_cross_job_quickscore_updates(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first = _seed_workspace_and_job(container)
        second = _store_related_job(
            container,
            first,
            slug="second-role",
            company="Example Products G.m.b.H.",
        )
        unrelated = _store_related_job(
            container,
            first,
            slug="unrelated-role",
            company="Other Machines AG",
        )
        ResultService(
            container.repository,
            container.job_corpus_service(),
            container.results,
            container.access_policy,
            employer_context=EmployerContextService(research_homepages=False),
            job_overrides=container.job_overrides,
            employer_reputation=container.employer_reputation,
            job_ratings=container.job_ratings,
        ).run(workspace)

        response = client.post(
            f"/jobs/{first.id}/employer-rating",
            data={"stars": "5"},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert set(payload["rating_record_ids"]) == {str(first.id), str(second.id)}
        assert {update["record_id"] for update in payload["score_updates"]} == {
            str(first.id),
            str(second.id),
        }
        assert str(unrelated.id) not in payload["rating_record_ids"]
        match_page = client.get("/matches")
        assert match_page.status_code == 200
        for update in payload["score_updates"]:
            assert f'data-match-record-id="{update["record_id"]}"' in match_page.text
            assert f"data-match-score>{update['score']}</strong>" in match_page.text


def test_job_detail_uses_one_dirty_bulk_editor_and_keeps_ratings_distinct(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)

        page = client.get(f"/jobs/{record.id}")

    assert page.status_code == 200
    assert page.text.count('id="evidence-bulk-form"') == 1
    assert "data-evidence-bulk-actions hidden" in page.text
    assert "data-evidence-input" in page.text
    assert "Save changes and update score" in page.text
    assert "Save my value" not in page.text
    assert "Your rating of this job" in page.text
    assert "Your rating of this exact job" not in page.text
    assert "data-job-rating-control" in page.text
    assert 'id="employer-reputation-rating"' in page.text
    assert "The point rules are fixed and published" in page.text


def test_job_detail_keeps_unknown_salary_orientation_visible_and_editable(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")

        assert page.status_code == 200
        assert "Expected salary orientation" in page.text
        assert "No attributable salary orientation is available." in page.text
        assert "WorkLifeBalance does not invent a range" in page.text
        assert "data-salary-range-min" in page.text
        assert "data-salary-range-max" in page.text
        assert 'name="evidence_key" value="salary.orientation.annual_range_eur"' in page.text

        saved = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "context",
                "evidence_key": "salary.orientation.annual_range_eur",
                "evidence_initial": ":",
                "evidence_value": "55000:65000",
            },
            follow_redirects=False,
        )

        assert saved.status_code == 303
        assert "rematch=1" not in saved.headers["location"]
        assert "compatibility+score+was+updated" in saved.headers["location"]
        salary_override = next(
            item
            for item in container.job_overrides.list_for_job(workspace.id, record.id)
            if item.target_key == "salary.orientation.annual_range_eur"
        )
        assert salary_override.kind == JobEvidenceOverrideKind.CONTEXT
    assert salary_override.text_value == "55000:65000"


def test_employer_facts_group_supports_multi_type_corrections(tmp_path: Path) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")

        assert page.status_code == 200
        job_facts = page.text.index('id="job-facts-heading"')
        job_relationship = page.text.index('<h3 class="subheading">Job relationship')
        job_rating = page.text.index('<h3 class="subheading">Your rating of this job')
        salary = page.text.index('<h3 class="subheading">Expected salary orientation')
        posting_date = page.text.index('id="posting-date"')
        employer_facts = page.text.index('id="employer-facts-heading"')
        compass_checks = page.text.index("Compass checks")
        assert (
            job_facts
            < job_relationship
            < job_rating
            < salary
            < posting_date
            < employer_facts
            < compass_checks
        )
        assert "Published location" not in page.text
        assert "Employer facts" in page.text
        assert "Job relationship" in page.text
        assert "data-employer-types-editor" in page.text
        assert 'class="employer-type-options" role="group"' in page.text
        assert "Healthcare provider" in page.text
        assert "Start-up / scale-up" in page.text
        assert 'name="evidence_key" value="company.employer.types"' in page.text

        saved = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "context",
                "evidence_key": "company.employer.types",
                "evidence_initial": "",
                "evidence_value": "consultancy,healthcare_provider",
            },
            follow_redirects=False,
        )

        assert saved.status_code == 303
        assert "compatibility+score+was+updated" in saved.headers["location"]
        override = next(
            item
            for item in container.job_overrides.list_for_job(workspace.id, record.id)
            if item.target_key == "company.employer.types"
        )
        assert override.kind == JobEvidenceOverrideKind.CONTEXT
        assert override.text_value == "consultancy,healthcare_provider"

        refreshed = client.get(f"/jobs/{record.id}")
        assert 'value="consultancy" checked' in refreshed.text
        assert 'value="healthcare_provider" checked' in refreshed.text


def test_employer_context_shared_from_another_job_is_labeled_and_not_restored_locally(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first_record = _seed_workspace_and_job(container)
        saved = client.post(
            f"/jobs/{first_record.id}/evidence/bulk",
            data={
                "evidence_kind": "context",
                "evidence_key": "employer.reputation.summary",
                "evidence_initial": "automatic",
                "evidence_value": "Good accessibility practice; verify the current team.",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

        second_url = "https://careers.example.com/jobs/second-role"
        second_source = "Example Products seeks a second Product Designer in Berlin."
        second_checked_at = datetime.now(timezone.utc)
        second_document = FetchedDocument(
            requested_url=second_url,
            final_url=second_url,
            status_code=200,
            content_type="text/html",
            text=second_source,
            fetched_at=second_checked_at,
        )
        second_job = JobPosting(
            title="Senior Product Designer",
            company="Example Products GmbH",
            location="Berlin",
            summary="Design another accessible product.",
            source_type=JobSourceType.URL_TEXT,
            source_name=second_url,
            source_url=second_url,
            requested_url=second_url,
            url_status=JobUrlStatus.VERIFIED_REACHABLE,
            url_http_status=200,
            url_checked_at=second_checked_at,
            source_text=second_source,
            observed_at=NOW,
        )
        second_record = container.repository.store_revision(
            second_document,
            second_job,
            JobObservationKind.NEW,
        )
        ResultService(
            container.repository,
            container.job_corpus_service(),
            container.results,
            container.access_policy,
            employer_context=EmployerContextService(research_homepages=False),
            job_overrides=container.job_overrides,
        ).run(workspace)

        page = client.get(f"/jobs/{second_record.id}")

    assert page.status_code == 200
    assert "Good accessibility practice; verify the current team." in page.text
    assert "Shared across jobs for Example Products GmbH" in page.text
    assert "Editing creates a value for this job." in page.text
    assert "Restore automatic context" not in page.text


def test_bulk_evidence_endpoint_validates_every_item_before_atomic_write(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)

        rejected = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": ["posting_date", "context"],
                "evidence_key": ["posting_date", "not.a.displayed.context"],
                "evidence_initial": ["2026-07-20", "automatic"],
                "evidence_value": ["2025-10-01", "changed"],
            },
            follow_redirects=False,
        )

        assert rejected.status_code == 303
        assert "No+evidence+changes+were+saved" in rejected.headers["location"]
        assert container.job_overrides.list_for_job(workspace.id, record.id) == []

        saved = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": ["posting_date", "skill"],
                "evidence_key": ["posting_date", "kotlin"],
                "evidence_initial": ["2026-07-20", "missing"],
                "evidence_value": ["2025-10-01", "matched"],
            },
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert "rematch=1" not in saved.headers["location"]
    assert "Run+complete+Match" in saved.headers["location"]
    overrides = container.job_overrides.list_for_job(workspace.id, record.id)
    assert {item.kind for item in overrides} == {
        JobEvidenceOverrideKind.POSTING_DATE,
        JobEvidenceOverrideKind.SKILL,
    }


def test_bulk_skill_capability_adds_to_compass_once_when_default_option_is_sent(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")

        assert 'name="also_update_compass_skills" value="true" checked' in page.text
        assert "Not currently in this persona’s Compass" in page.text
        assert "Add to persona Compass" not in page.text

        for initial, value in (("missing", "matched"), ("missing", "matched")):
            response = client.post(
                f"/jobs/{record.id}/evidence/bulk",
                data={
                    "evidence_kind": "skill",
                    "evidence_key": "kotlin",
                    "evidence_initial": initial,
                    "evidence_value": value,
                    "also_update_compass_skills_present": "true",
                    "also_update_compass_skills": "true",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

        changed_to_missing = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "skill",
                "evidence_key": "kotlin",
                "evidence_initial": "matched",
                "evidence_value": "missing",
                "also_update_compass_skills_present": "true",
                "also_update_compass_skills": "true",
            },
            follow_redirects=False,
        )

    assert changed_to_missing.status_code == 303
    saved_workspace = container.workspaces.latest()
    kotlin_facts = [
        fact
        for fact in saved_workspace.session.profile.confirmed_candidate_evidence
        if fact.key == "skill.demonstrated" and str(fact.value).casefold() == "kotlin"
    ]
    assert len(kotlin_facts) == 1
    assert kotlin_facts[0].source.section == ProfileSection.EXPERIENCE
    assert kotlin_facts[0].user_note == "Added explicitly from bulk job-evidence corrections"
    (override,) = [
        item
        for item in container.job_overrides.list_for_job(workspace.id, record.id)
        if item.kind == JobEvidenceOverrideKind.SKILL
    ]
    assert override.skill_value.value == "missing"


def test_skill_compass_preference_persists_and_marker_tracks_current_persona(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, persona, _workspace, record = _seed_workspace_and_job(container)

        disabled = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "skill",
                "evidence_key": "kotlin",
                "evidence_initial": "missing",
                "evidence_value": "missing",
                "also_update_compass_skills_present": "true",
            },
            follow_redirects=False,
        )
        assert disabled.status_code == 303
        assert not container.personas.get(
            persona.id,
            account_id=account.id,
        ).also_update_compass_skills
        page = client.get(f"/jobs/{record.id}")
        assert 'name="also_update_compass_skills" value="true" checked' not in page.text

        added = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "skill",
                "evidence_key": "kotlin",
                "evidence_initial": "missing",
                "evidence_value": "matched",
                "also_update_compass_skills_present": "true",
                "also_update_compass_skills": "true",
            },
            follow_redirects=False,
        )
        assert added.status_code == 303
        assert container.personas.get(
            persona.id,
            account_id=account.id,
        ).also_update_compass_skills
        marked = client.get(f"/jobs/{record.id}")
        assert "✓ Already in this persona’s Compass" in marked.text

        current = container.workspaces.latest(persona_id=persona.id)
        assert current is not None
        current.session.profile.facts = [
            fact
            for fact in current.session.profile.facts
            if not (fact.key == "skill.demonstrated" and str(fact.value).casefold() == "kotlin")
        ]
        current.session.profile.updated_at = NOW
        current.session.updated_at = NOW
        container.workspaces.save(current)
        unmarked = client.get(f"/jobs/{record.id}")

    assert "✓ Already in this persona’s Compass" not in unmarked.text
    assert "Not currently in this persona’s Compass" in unmarked.text


def test_prepare_package_uses_published_address_and_safe_job_page_fallback(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, _workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")

    assert page.status_code == 200
    assert "Published address" in page.text
    assert "Postal address" not in page.text
    assert "Job page ↗" in page.text
    assert "Verified source link; not a confirmed application channel." in page.text


def test_employer_relationship_editor_supports_nuanced_preserved_categories(
    tmp_path: Path,
) -> None:
    assert EmployerKind.DIRECT_EMPLOYER.value == "direct_employer"
    assert EmployerKind.STAFFING_AGENCY.value == "staffing_agency"
    assert EmployerKind.RECRUITMENT_AGENCY.value == "recruitment_agency"
    assert EmployerKind.DIRECT_EMPLOYER.likely_direct_contract is True
    assert EmployerKind.STAFFING_AGENCY.likely_direct_contract is False
    for kind in (
        EmployerKind.FREELANCE,
        EmployerKind.CONTRACTOR,
        EmployerKind.INTERMEDIARY,
        EmployerKind.PLATFORM,
        EmployerKind.CONSULTANCY,
        EmployerKind.OTHER,
        EmployerKind.UNKNOWN,
    ):
        assert kind.likely_direct_contract is None

    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")
    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")
        saved = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "context",
                "evidence_key": "employer.relationship.kind",
                "evidence_initial": "unknown",
                "evidence_value": "consultancy",
            },
            follow_redirects=False,
        )

    assert saved.status_code == 303
    for value in (
        "freelance",
        "contractor",
        "intermediary",
        "platform",
        "consultancy",
        "other",
    ):
        assert f'<option value="{value}"' in page.text
    assert "Choose after checking the contract model" in page.text
    (relationship,) = [
        item
        for item in container.job_overrides.list_for_job(workspace.id, record.id)
        if item.target_key == "employer.relationship.kind"
    ]
    assert relationship.text_value == "consultancy"


def test_evidence_workbench_is_wide_and_no_result_edits_are_useful_prompts(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")
    with TestClient(app) as client:
        _register(client)
        _account, _persona, _workspace, record = _seed_workspace_and_job(container)
        page = client.get(f"/jobs/{record.id}")

    css = Path("src/betteroption/web/static/app.css").read_text(encoding="utf-8")
    assert "evidence-workbench" in page.text
    assert "Research prompt: what does the company sell" in page.text
    assert "About these research prompts" in page.text
    assert "They are editable starting points, not automatic evidence." in page.text
    assert "evidence-suggestion-input" in page.text
    assert (
        ".result-detail-grid { grid-template-columns: minmax(0,1.72fr) minmax(19rem,.68fr); }"
        in css
    )
    assert "grid-template-columns: minmax(22rem,2fr) minmax(18rem,1fr)" in css
    assert ".evidence-comparison.company-intelligence > .evidence-auto" in css
    assert "color: var(--ink-soft); font-family: inherit" in css
    assert "font-weight: 400" in css
