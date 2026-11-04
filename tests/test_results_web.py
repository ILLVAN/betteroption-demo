from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.job_context import EmployerContextService
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import (
    JobFact,
    JobFactKind,
    JobPosting,
    JobSourceType,
    JobUrlStatus,
)
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.result_repository import (
    ApplicationState,
    FeedbackState,
    InteractionEventKind,
)
from betteroption.results import ResultService
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument, UrlFailureKind
from betteroption.web import create_app


NOW = datetime.now(timezone.utc)


def build_container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'results.db').as_posix()}",
            auth_mode="local",
            employer_homepage_research=False,
            background_worker_enabled=False,
        )
    )


def confirmed_fact(
    key: str,
    value: str,
    level: RequirementLevel,
    *,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def seed_workspace(container: ApplicationContainer):
    session = new_session()
    session.profile.facts = [
        confirmed_fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
        confirmed_fact("work_model.remote", "hybrid remote", RequirementLevel.MUST_HAVE),
        confirmed_fact("industry.sector", "defense", RequirementLevel.EXCLUSION),
        confirmed_fact(
            "employment.arrangement",
            "temporary agency",
            RequirementLevel.EXCLUSION,
        ),
        confirmed_fact(
            "skill.demonstrated",
            "Python",
            RequirementLevel.OPEN,
            section=ProfileSection.EXPERIENCE,
        ),
    ]
    return container.workspaces.create(session)


def seed_job(
    container: ApplicationContainer,
    slug: str,
    *,
    defense: bool = False,
    temporary_agency: bool = False,
    remote_only: bool = False,
) -> tuple[UUID, JobPosting]:
    url = f"https://careers.example.com/jobs/{slug}"
    source_parts = [
        f"{slug.title()} Engineer at Example Products.",
        "Embedded software product development.",
        "Python is required.",
        "This is a fully remote role." if remote_only else "Hybrid remote work is available.",
    ]
    facts = [
        JobFact(
            key="role.family",
            value="embedded software",
            kind=JobFactKind.CONTEXT,
            evidence_quote="Embedded software",
        ),
        JobFact(
            key="skill.name",
            value="Python",
            kind=JobFactKind.REQUIREMENT,
            evidence_quote="Python",
        ),
        JobFact(
            key="work_model.remote",
            value="fully remote" if remote_only else "hybrid remote",
            kind=JobFactKind.OFFER,
            evidence_quote="fully remote" if remote_only else "Hybrid remote",
        ),
    ]
    if defense:
        source_parts.append("The product is built for the defense sector.")
        facts.append(
            JobFact(
                key="industry.sector",
                value="defense",
                kind=JobFactKind.CONTEXT,
                evidence_quote="defense",
            )
        )
    if temporary_agency:
        source_parts.append("This role uses a temporary agency arrangement.")
        facts.append(
            JobFact(
                key="employment.arrangement",
                value="temporary agency",
                kind=JobFactKind.CONTEXT,
                evidence_quote="temporary agency",
            )
        )
    source = " ".join(source_parts)
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
        location="Remote – Europe" if remote_only else "Frankfurt",
        summary="Build embedded products in a hybrid engineering team.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
        facts=facts,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return record.id, job


class CountingMobility:
    def __init__(self) -> None:
        self.record_ids: list[UUID] = []

    def assess(self, _workspace_id, record_id, _profile, _destination, **_kwargs):
        self.record_ids.append(record_id)
        return []


def service(
    container: ApplicationContainer,
    mobility: CountingMobility | None = None,
) -> ResultService:
    return ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        mobility,
        job_overrides=container.job_overrides,
    )


def test_result_run_persists_twenty_five_free_recommendations_and_keeps_blocked_visible(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    for index in range(26):
        seed_job(container, f"top-{index}")
    seed_job(container, "blocked", defense=True, temporary_agency=True)

    mobility = CountingMobility()
    groups = service(container, mobility).run(workspace)

    assert len(groups.top) == 26
    assert len(groups.stretch) == 0
    assert len(groups.blocked) == 1
    assert sum(item.accessible for item in groups.top) == 25
    assert not [item for item in groups.top if not item.accessible][0].accessible
    assert groups.blocked[0].accessible
    assert groups.locked_count == 1
    assert groups.granted_count == 25
    assert groups.algorithm_is_current
    assert groups.run.algorithm_version == "matching-v0.7.2i"
    assert len(mobility.record_ids) == 25
    assert container.results.count_runs(workspace.id) == 1
    assert service(container).latest(workspace).run.id == groups.run.id
    assert groups.run.metrics is not None
    assert groups.run.metrics.jobs_evaluated == 27
    assert groups.run.metrics.exact_route_jobs == 25
    assert groups.run.metrics.included_slots == 25
    assert groups.run.metrics.top_count == 26
    assert groups.run.metrics.stretch_count == 0
    assert groups.run.metrics.blocked_count == 1
    assert groups.run.metrics.provider_operations == 0

    second = service(container).run(workspace)

    assert second.granted_count == 25
    assert len(container.results.access_grants(workspace.id)) == 25
    assert container.results.count_runs(workspace.id) == 2


def test_remote_only_result_skips_mobility_provider_call(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _job = seed_job(container, "remote-only", remote_only=True)
    mobility = CountingMobility()

    groups = service(container, mobility).run(workspace)

    assert mobility.record_ids == []
    assert groups.run.metrics is not None
    assert groups.run.metrics.exact_route_jobs == 0
    item = next(item for item in [*groups.top, *groups.stretch] if item.record.id == record_id)
    assert item.stored.result.remote_only_mobility


def test_single_job_full_rematch_accepts_a_semantic_compass_change(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _job = seed_job(container, "stale-single-rematch")
    kept_id, _kept_job = seed_job(container, "stale-single-rematch-kept")
    service(container).run(workspace)
    workspace.session.profile.facts.append(
        confirmed_fact("culture.preference", "calm team", RequirementLevel.PREFERENCE)
    )
    workspace.session.profile.updated_at = datetime.now(timezone.utc)
    workspace.session.updated_at = datetime.now(timezone.utc)
    container.workspaces.save(workspace)

    refreshed = service(container).run(workspace, record_ids={record_id})

    assert container.results.count_runs(workspace.id) == 2
    assert refreshed.has_partial_job_refresh
    assert not refreshed.profile_is_current
    assert {result.job_record_id for result in refreshed.run.results} == {
        record_id,
        kept_id,
    }


def test_feedback_and_application_state_keep_current_state_and_append_only_history(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "feedback")
    groups = service(container).run(workspace)

    container.results.set_feedback(
        workspace.id,
        record_id,
        FeedbackState.TOO_MUCH_CONSULTING,
        note="Technically relevant, but the delivery model is wrong.",
    )
    interaction = container.results.set_application_state(
        workspace.id,
        record_id,
        ApplicationState.SAVED,
    )
    events = container.results.interaction_events(workspace.id, record_id)

    assert interaction.feedback == FeedbackState.TOO_MUCH_CONSULTING
    assert interaction.application_state == ApplicationState.SAVED
    assert interaction.note == "Technically relevant, but the delivery model is wrong."
    assert [event.kind for event in events] == [
        InteractionEventKind.MATCH,
        InteractionEventKind.FEEDBACK,
        InteractionEventKind.APPLICATION,
    ]
    assert service(container).detail(workspace, groups.run.id, record_id).events == events


def test_web_results_show_groups_evidence_unknowns_and_protect_the_twenty_sixth_result(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    for index in range(26):
        seed_job(container, f"recommended-{index}")
    seed_job(container, "stretch", defense=True)
    seed_job(container, "blocked", defense=True, temporary_agency=True)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    created = client.post("/matches/run", follow_redirects=False)
    page = client.get("/matches")
    groups = service(container).latest(workspace)
    locked = next(item for item in [*groups.top, *groups.stretch] if not item.accessible)
    included = next(item for item in groups.top if item.accessible)

    assert created.status_code == 303
    assert created.headers["location"].startswith("/matches?notice=")
    assert page.status_code == 200
    assert "Top matches" in page.text
    assert "Stretch matches" in page.text
    assert "Blocked by your boundaries" in page.text
    assert "Another matched opportunity is ready" in page.text
    assert "Beyond free 25" in page.text
    assert page.text.count("See evidence") == 27
    assert 'class="opportunity-card result-card selectable-card"' in page.text
    assert 'class="card-body-link card-link"' in page.text
    assert client.get(f"/matches/{groups.run.id}/{locked.record.id}").status_code == 403
    locked_inbox_detail = client.get(f"/jobs/{locked.record.id}")
    assert "Compatibility" not in locked_inbox_detail.text
    assert "Why it was rated this way" not in locked_inbox_detail.text

    detail = client.get(f"/matches/{groups.run.id}/{included.record.id}")
    canonical_detail = client.get(f"/jobs/{included.record.id}")

    assert detail.status_code == 200
    assert included.stored.job.title in detail.text
    assert str(included.stored.job.source_url) in detail.text
    assert "Open verified job page" in detail.text
    assert "Why it landed here" in detail.text
    assert "Compass checks" in detail.text
    assert "Python" in detail.text
    assert re.search(r"\d+%.*Boundary evidence", detail.text, flags=re.DOTALL)
    assert canonical_detail.status_code == 200
    assert 'aria-label="Previous opportunity"' in canonical_detail.text
    assert 'aria-label="Next opportunity"' in canonical_detail.text
    assert re.search(r"\d+\s*/\s*\d+", canonical_detail.text)


def test_match_action_is_disabled_when_archive_has_only_closed_jobs(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    seed_workspace(container)
    record_id, job = seed_job(container, "closed-only")
    container.repository.record_failure(
        str(job.source_url),
        UrlFailureKind.EXPIRED,
        "job page returned HTTP 410",
        http_status=410,
        checked_at=NOW,
    )
    assert container.repository.get_current_job(record_id) is not None
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get("/matches")

    assert page.status_code == 200
    assert "Save an open, extracted job through Add or Explore" in page.text
    assert re.search(r"<button[^>]+disabled[^>]*>Create my matches", page.text)


def test_web_feedback_and_application_actions_persist(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "decision")
    groups = service(container).run(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    detail_path = f"/matches/{groups.run.id}/{record_id}"

    feedback = client.post(
        f"{detail_path}/feedback",
        data={"feedback": "too_little_development", "note": "Too operational."},
        follow_redirects=False,
    )
    application = client.post(
        f"{detail_path}/application",
        data={"application_state": "applied"},
        follow_redirects=False,
    )
    detail = client.get(detail_path)
    matches = client.get("/matches")
    interaction = container.results.get_interaction(workspace.id, record_id)

    assert feedback.status_code == 303
    assert application.status_code == 303
    assert interaction.feedback == FeedbackState.TOO_LITTLE_DEVELOPMENT
    assert interaction.application_state == ApplicationState.APPLIED
    assert "Too operational." in detail.text
    assert "Decision history" in detail.text
    assert "Application · Applied" in detail.text
    assert 'data-application-state-card="applied"' in matches.text
    assert '<option value="applied" selected>Applied</option>' in matches.text
    assert f"/jobs/{record_id}/application-state" in matches.text


def test_rejected_and_withdrawn_states_render_as_ended_cards(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "ended")
    service(container).run(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    for state in (ApplicationState.REJECTED, ApplicationState.WITHDRAWN):
        saved = client.post(
            f"/jobs/{record_id}/application-state",
            data={"application_state": state.value},
            headers={"Accept": "application/json"},
        )
        matches = client.get("/matches")

        assert saved.status_code == 200
        assert saved.json()["state"] == state.value
        assert f'data-application-state-card="{state.value}"' in matches.text


def test_home_excludes_rejected_and_withdrawn_but_archive_keeps_them(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    rejected_id, rejected_job = seed_job(container, "rejected-home")
    withdrawn_id, withdrawn_job = seed_job(container, "withdrawn-home")
    _current_id, current_job = seed_job(container, "current-home")
    service(container).run(workspace)
    container.results.set_application_state(
        workspace.id,
        rejected_id,
        ApplicationState.REJECTED,
    )
    container.results.set_application_state(
        workspace.id,
        withdrawn_id,
        ApplicationState.WITHDRAWN,
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    home = client.get("/")
    archive = client.get("/jobs")

    assert home.status_code == 200
    assert current_job.title in home.text
    assert rejected_job.title not in home.text
    assert withdrawn_job.title not in home.text
    assert rejected_job.title in archive.text
    assert withdrawn_job.title in archive.text


def test_missing_required_skill_can_be_added_once_to_the_active_persona_compass(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, job = seed_job(container, "compass-skill")
    updated_source = f"{job.source_text} Kotlin is required for the role."
    updated_job_payload = job.model_dump()
    updated_job_payload.update(
        source_text=updated_source,
        content_hash="",
        facts=[
            *job.facts,
            JobFact(
                key="skill.name",
                value="Kotlin",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Kotlin is required",
            ),
        ],
    )
    updated_job = JobPosting.model_validate(updated_job_payload)
    container.repository.store_revision(
        FetchedDocument(
            requested_url=str(job.requested_url),
            final_url=str(job.source_url),
            status_code=200,
            content_type="text/html",
            text=updated_source,
            fetched_at=NOW,
        ),
        updated_job,
        JobObservationKind.CHANGED,
    )
    groups = service(container).run(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    before = client.get(f"/jobs/{record_id}")
    added = client.post(
        f"/jobs/{record_id}/evidence/skill/add-to-compass",
        data={"skill": "Kotlin"},
        follow_redirects=False,
    )
    repeated = client.post(
        f"/jobs/{record_id}/evidence/skill/add-to-compass",
        data={"skill": "kOtLiN"},
        follow_redirects=False,
    )
    saved_workspace = container.workspaces.latest()
    saved_skills = [
        fact
        for fact in saved_workspace.session.profile.confirmed_candidate_evidence
        if fact.key == "skill.demonstrated" and str(fact.value).casefold() == "kotlin"
    ]
    latest_groups = service(container).latest(saved_workspace)

    assert before.status_code == 200
    assert "Also update my Compass from skill changes" in before.text
    assert added.status_code == 303
    assert "rematch=1" not in added.headers["location"]
    assert "Fully+rematch+this+job" in added.headers["location"]
    assert repeated.status_code == 303
    assert len(saved_skills) == 1
    assert saved_skills[0].source.section == ProfileSection.EXPERIENCE
    assert latest_groups.run.id == groups.run.id
    assert not latest_groups.profile_is_current


def test_confirmed_archive_deletion_cascades_match_access_and_interaction_history(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "delete-me")
    groups = service(container).run(workspace)
    container.results.set_feedback(
        workspace.id,
        record_id,
        FeedbackState.INTERESTED,
        note="Useful before deletion.",
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    response = client.post(
        f"/jobs/{record_id}/delete",
        data={"confirm_delete": "true"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert container.repository.count_records() == 0
    stored_run = container.results.get_run(groups.run.id)
    assert stored_run is not None
    assert stored_run.results == []
    assert container.results.access_grants(workspace.id) == []
    assert container.results.interaction_events(workspace.id, record_id) == []
    assert client.get(f"/matches/{groups.run.id}/{record_id}").status_code == 404


def test_proven_exclusion_is_blocked_and_does_not_encourage_an_application(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "stretch-only", defense=True)
    groups = service(container).run(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    assert len(groups.blocked) == 1
    assert groups.blocked[0].accessible

    detail = client.get(f"/matches/{groups.run.id}/{record_id}")

    assert detail.status_code == 200
    assert "Why still apply?" not in detail.text
    assert "Example Products" in detail.text
    assert "The advertisement shows relevant potential" not in detail.text
    assert "contains an excluded characteristic" in detail.text
    assert "“defense”" in detail.text


def test_canonical_job_detail_shows_saved_company_intelligence(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "company-context", defense=True)
    rich_service = ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        employer_context=EmployerContextService(research_homepages=False),
    )
    groups = rich_service.run(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    detail = client.get(f"/matches/{groups.run.id}/{record_id}")

    assert detail.status_code == 200
    assert "Company product profile" in detail.text
    assert "Defence products, systems, or services" in detail.text
    assert "Employer reputation check" in detail.text
    assert "Current review profiles" in detail.text
    assert "Find this employer on Kununu" in detail.text


def test_saved_result_discloses_when_the_compass_changed_after_matching(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    seed_job(container, "profile-change")
    service(container).run(workspace)
    workspace.session.profile.facts.append(
        confirmed_fact("work_model.hours_weekly", "35 hours", RequirementLevel.PREFERENCE)
    )
    updated = container.workspaces.save(workspace)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    groups = service(container).latest(updated)
    page = client.get("/matches")

    assert not groups.profile_is_current
    assert "Your compass changed after this result set was created" in page.text


def test_saved_result_withholds_verified_link_after_the_job_revision_changes(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, original = seed_job(container, "job-change")
    groups = service(container).run(workspace)
    changed_source = f"{original.source_text} The responsibilities have changed."
    changed_document = FetchedDocument(
        requested_url=str(original.requested_url),
        final_url=str(original.source_url),
        status_code=200,
        content_type="text/html",
        text=changed_source,
        fetched_at=NOW,
    )
    changed_job = JobPosting(
        title="Changed Job Engineer",
        company=original.company,
        location=original.location,
        summary=original.summary,
        source_type=original.source_type,
        source_name=original.source_name,
        source_url=original.source_url,
        requested_url=original.requested_url,
        url_status=original.url_status,
        url_http_status=original.url_http_status,
        url_checked_at=NOW,
        source_text=changed_source,
        observed_at=NOW,
        facts=original.facts,
    )
    container.repository.store_revision(
        changed_document,
        changed_job,
        JobObservationKind.CHANGED,
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    latest = service(container).latest(workspace)
    item = next(item for item in latest.top if item.record.id == record_id)
    detail = client.get(f"/matches/{groups.run.id}/{record_id}")

    assert not item.source_is_current
    assert "Open verified job page" not in detail.text
    assert "The source has changed or closed since this result was created" in detail.text


def test_job_evidence_correction_updates_the_saved_score_without_a_full_rematch(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    record_id, _ = seed_job(container, "inline-correction")
    initial = service(container).run(workspace)
    item = next(item for item in initial.top if item.record.id == record_id)
    reason = next(
        reason for reason in item.stored.result.reasons if reason.profile_key == "work_model.remote"
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get(f"/jobs/{record_id}")
    saved = client.post(
        f"/jobs/{record_id}/evidence/reason",
        data={"target_key": str(reason.profile_fact_id), "value": "violated"},
        follow_redirects=False,
    )

    assert page.status_code == 200
    assert "Automatic comparison" in page.text
    assert "Your value" in page.text
    assert "Your correction layer" not in page.text
    assert "Why? <small>Optional</small>" not in page.text
    assert saved.status_code == 303
    assert saved.headers["location"].startswith(f"/jobs/{record_id}?notice=")
    assert "compatibility+score+was+updated" in saved.headers["location"]
    assert container.results.count_runs(workspace.id) == 1
    assert container.results.latest_run(workspace.id).id == initial.run.id
    override = container.job_overrides.list_for_job(workspace.id, record_id)[0]
    assert override.reason_value == "violated"
    assert override.note is None

    refreshed = service(container).latest(workspace)

    assert refreshed is not None
    corrected = next(
        result for result in refreshed.run.results if result.job_record_id == record_id
    )
    corrected_reason = next(
        item for item in corrected.result.reasons if item.profile_fact_id == reason.profile_fact_id
    )
    assert corrected_reason.outcome.value == "violated"
    assert corrected.result.score < item.stored.result.score


def test_explicit_single_job_rematch_keeps_other_results_and_applies_saved_value(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    target_id, _ = seed_job(container, "rematch-target")
    kept_id, _ = seed_job(container, "rematch-kept")
    initial = service(container).run(workspace)
    target = next(item for item in initial.top if item.record.id == target_id)
    reason = next(
        reason
        for reason in target.stored.result.reasons
        if reason.profile_key == "work_model.remote"
    )
    kept_before = next(result for result in initial.run.results if result.job_record_id == kept_id)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    client.post(
        f"/jobs/{target_id}/evidence/reason",
        data={"target_key": str(reason.profile_fact_id), "value": "violated"},
        follow_redirects=False,
    )

    response = client.post(
        f"/jobs/{target_id}/evidence/rematch",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/tasks/")
    assert container.results.count_runs(workspace.id) == 1
    task_id = UUID(response.headers["location"].removeprefix("/tasks/"))
    payload = container.background_single_job_matches.get(task_id)
    assert payload is not None
    assert payload.job_record_id == target_id
    assert client.app.state.background_worker.run_once()
    finished = container.background_tasks.get(task_id)
    assert finished is not None
    assert finished.status.value == "succeeded"
    assert "other+saved+match+results+were+kept" in finished.result_url
    assert container.results.count_runs(workspace.id) == 2
    latest = service(container).latest(workspace)
    assert latest is not None
    assert {result.job_record_id for result in latest.run.results} == {target_id, kept_id}
    kept_after = next(result for result in latest.run.results if result.job_record_id == kept_id)
    assert kept_after.result == kept_before.result
    target_after = next(
        item
        for item in [*latest.top, *latest.stretch, *latest.blocked]
        if item.record.id == target_id
    )
    corrected_reason = next(
        row
        for row in target_after.stored.result.reasons
        if row.profile_fact_id == reason.profile_fact_id
    )
    assert corrected_reason.user_overridden
    assert corrected_reason.automatic_outcome is not None
    assert corrected_reason.outcome.value == "violated"
    assert len(container.job_overrides.list_for_job(workspace.id, target_id)) == 1
    detail_page = client.get(f"/jobs/{target_id}")
    match_page = client.get("/matches")
    assert 'class="evidence-comparison reason-comparison violated has-user-override"' in (
        detail_page.text
    )
    assert "× Blocker" in detail_page.text
    assert "One job is newer:" in match_page.text
    assert "other saved scores were preserved" in match_page.text
