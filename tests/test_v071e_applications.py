from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from betteroption.applications import (
    ApplicationDraftError,
    ApplicationDraftRow,
    ApplicationDraftService,
    DraftAction,
    minimized_application_facts,
)
from betteroption.container import ApplicationContainer
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.llm import InMemoryInvocationRecorder, ModelRoute, TokenUsage, estimate_cost
from betteroption.matching import MatchDisposition, MatchResult, MatchRun
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.providers.openai_application import (
    CoverLetterOutput,
    OpenAIApplicationDrafter,
)
from betteroption.retention import RetentionPolicy, run_retention
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
JOB_URL = "https://careers.example.com/jobs/embedded-application"


class FakeApplicationDrafter:
    model = "fake-application-model"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def draft(
        self,
        *,
        job: JobPosting,
        confirmed_facts: list[ProfileFact],
        action: str,
        existing_text: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "job": job,
                "confirmed_facts": confirmed_facts,
                "action": action,
                "existing_text": existing_text,
            }
        )
        return f"{action.title()} letter for {job.title}; facts={len(confirmed_facts)}"


def build_container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'applications.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )


def profile_fact(
    key: str,
    value: str,
    section: ProfileSection,
    *,
    evidence_status: EvidenceStatus = EvidenceStatus.CONFIRMED,
    level: RequirementLevel = RequirementLevel.PREFERENCE,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=evidence_status,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def create_workspace(container: ApplicationContainer):
    session = new_session()
    session.profile.facts = [
        profile_fact("role.family", "Embedded software", ProfileSection.DIRECTION),
        profile_fact("skill.demonstrated", "Python", ProfileSection.EXPERIENCE),
        profile_fact(
            "location.origin",
            "Private exact address",
            ProfileSection.LOCATION_MOBILITY,
        ),
        profile_fact(
            "industry.excluded",
            "Weapons",
            ProfileSection.EXCLUSIONS,
            level=RequirementLevel.EXCLUSION,
        ),
        profile_fact(
            "preference.rejected",
            "Rejected idea",
            ProfileSection.PREFERENCES,
            evidence_status=EvidenceStatus.REJECTED,
        ),
    ]
    return container.workspaces.create(session)


def seed_job(container: ApplicationContainer) -> tuple[UUID, JobPosting]:
    source = "Example Products needs Python for an Embedded Engineer in Frankfurt."
    document = FetchedDocument(
        requested_url=JOB_URL,
        final_url=JOB_URL,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title="Embedded Engineer",
        company="Example Products",
        location="Frankfurt",
        summary="Build reliable embedded products.",
        facts=[
            JobFact(
                key="skill.name",
                value="Python",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Python",
            )
        ],
        source_type=JobSourceType.URL_TEXT,
        source_name=JOB_URL,
        source_url=JOB_URL,
        requested_url=JOB_URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
    )
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return record.id, job


def seed_distinct_job(
    container: ApplicationContainer,
    *,
    url: str,
    title: str,
    company: str,
) -> tuple[UUID, JobPosting]:
    source = f"{company} needs Python for a {title} in Frankfurt."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title=title,
        company=company,
        location="Frankfurt",
        summary=f"Build reliable products for {company}.",
        facts=[
            JobFact(
                key="skill.name",
                value="Python",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Python",
            )
        ],
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
    record = container.repository.store_revision(document, job, JobObservationKind.NEW)
    return record.id, job


def save_match_set(
    container: ApplicationContainer,
    workspace,
    records_and_jobs: list[tuple[UUID, JobPosting]],
) -> None:
    run = MatchRun(
        profile_id=workspace.session.profile.id,
        created_at=NOW,
        results=[
            MatchResult(
                job_id=job.id,
                job_url=job.source_url,
                url_status=job.url_status,
                url_http_status=job.url_http_status,
                url_verified_at=job.url_checked_at,
                score=84,
                hard_evidence_coverage=80,
                disposition=MatchDisposition.TOP,
                hard_violations=0,
            )
            for _record_id, job in records_and_jobs
        ],
    )
    container.results.save_run(
        workspace.id,
        run,
        workspace.session.profile,
        {job.id: job for _record_id, job in records_and_jobs},
        {job.id: record_id for record_id, job in records_and_jobs},
    )
    container.results.grant_initial_results(workspace.id, run.id, limit=25)


def save_match(
    container: ApplicationContainer,
    workspace,
    record_id: UUID,
    job: JobPosting,
    disposition: MatchDisposition,
    *,
    created_at: datetime = NOW,
) -> None:
    run = MatchRun(
        profile_id=workspace.session.profile.id,
        created_at=created_at,
        results=[
            MatchResult(
                job_id=job.id,
                job_url=job.source_url,
                url_status=job.url_status,
                url_http_status=job.url_http_status,
                url_verified_at=job.url_checked_at,
                score=84,
                hard_evidence_coverage=80,
                disposition=disposition,
                hard_violations=1 if disposition == MatchDisposition.BLOCKED else 0,
            )
        ],
    )
    container.results.save_run(
        workspace.id,
        run,
        workspace.session.profile,
        {job.id: job},
        {job.id: record_id},
    )
    container.results.grant_initial_results(workspace.id, run.id, limit=25)


def test_application_service_minimizes_facts_and_supports_complete_draft_lifecycle(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    drafter = FakeApplicationDrafter()
    service = ApplicationDraftService(container.application_drafts, drafter)

    selected = minimized_application_facts(workspace)
    assert [(fact.key, fact.value) for fact in selected] == [
        ("role.family", "Embedded software"),
        ("skill.demonstrated", "Python"),
    ]
    with pytest.raises(ApplicationDraftError, match="Create a cover letter"):
        service.generate(workspace, record_id, job, DraftAction.LONGER)

    created = service.generate(workspace, record_id, job, DraftAction.CREATE)
    assert created.generator_model == drafter.model
    assert created.generated_action == DraftAction.CREATE
    assert not created.manually_edited
    assert [fact.key for fact in drafter.calls[-1]["confirmed_facts"]] == [
        "role.family",
        "skill.demonstrated",
    ]

    edited = container.application_drafts.save(
        workspace.id,
        record_id,
        "Human-edited grounded letter",
        generator_model=created.generator_model,
        generated_action=created.generated_action,
        manually_edited=True,
    )
    assert edited.manually_edited

    longer = service.generate(workspace, record_id, job, DraftAction.LONGER)
    assert drafter.calls[-1]["existing_text"] == "Human-edited grounded letter"
    assert longer.generated_action == DraftAction.LONGER
    shorter = service.generate(workspace, record_id, job, DraftAction.SHORTER)
    assert shorter.generated_action == DraftAction.SHORTER
    recreated = service.generate(workspace, record_id, job, DraftAction.RECREATE)
    assert recreated.generated_action == DraftAction.RECREATE
    assert [call["action"] for call in drafter.calls] == [
        "create",
        "longer",
        "shorter",
        "recreate",
    ]

    assert container.application_drafts.delete(workspace.id, record_id)
    assert container.application_drafts.get(workspace.id, record_id) is None


def test_shorter_action_enforces_a_material_word_reduction_when_provider_does_not(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)

    class UncooperativeShorterDrafter(FakeApplicationDrafter):
        def draft(
            self,
            *,
            job: JobPosting,
            confirmed_facts: list[ProfileFact],
            action: str,
            existing_text: str | None = None,
        ) -> str:
            super().draft(
                job=job,
                confirmed_facts=confirmed_facts,
                action=action,
                existing_text=existing_text,
            )
            return " ".join(f"candidate-{index}" for index in range(150))

    drafter = UncooperativeShorterDrafter()
    service = ApplicationDraftService(container.application_drafts, drafter)
    created = service.generate(workspace, record_id, job, DraftAction.CREATE)
    existing_text = " ".join(f"original-{index}" for index in range(120))
    container.application_drafts.save(
        workspace.id,
        record_id,
        existing_text,
        generator_model=created.generator_model,
        generated_action=created.generated_action,
        manually_edited=True,
        draft_id=created.id,
    )

    shorter = service.generate(
        workspace,
        record_id,
        job,
        DraftAction.SHORTER,
        draft_id=created.id,
    )

    assert len(shorter.content.split()) == 90
    assert len(existing_text.split()) - len(shorter.content.split()) == 30


def test_v071g_keeps_three_named_drafts_and_blocks_a_fourth_before_provider_use(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    drafter = FakeApplicationDrafter()
    service = ApplicationDraftService(container.application_drafts, drafter)

    drafts = [
        service.generate(
            workspace,
            record_id,
            job,
            DraftAction.CREATE,
            name=name,
        )
        for name in ("Concise", "Technical", "Warm")
    ]

    assert [(draft.slot, draft.name) for draft in drafts] == [
        (1, "Concise"),
        (2, "Technical"),
        (3, "Warm"),
    ]
    assert len(drafter.calls) == 3
    with pytest.raises(ApplicationDraftError, match="already has 3 drafts"):
        service.generate(workspace, record_id, job, DraftAction.CREATE)
    assert len(drafter.calls) == 3

    second = drafts[1]
    renamed = container.application_drafts.save(
        workspace.id,
        record_id,
        "Edited technical version",
        draft_id=second.id,
        name="Technical lead",
        generator_model=second.generator_model,
        generated_action=second.generated_action,
        manually_edited=True,
    )
    assert renamed.slot == 2
    assert renamed.name == "Technical lead"
    assert container.application_drafts.delete(workspace.id, record_id, second.id)

    replacement = service.generate(
        workspace,
        record_id,
        job,
        DraftAction.CREATE,
        name="Replacement",
    )
    assert replacement.slot == 2


def test_apply_web_flow_creates_edits_transforms_and_deletes_a_grounded_letter(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    save_match(container, workspace, record_id, job, MatchDisposition.TOP)
    drafter = FakeApplicationDrafter()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    page = client.get(f"/apply?job={record_id}")
    detail = client.get(f"/jobs/{record_id}")
    assert page.status_code == 200
    assert "Embedded Engineer" in page.text
    assert 'class="apply-candidate' in page.text
    assert 'class="apply-candidate-copy"' in page.text
    assert f"/apply?job={record_id}" in detail.text
    assert 'class="panel application-draft-launcher"' in detail.text
    assert 'class="panel application-state-panel"' in detail.text
    assert detail.text.index("Prepare your cover letter") < detail.text.index(
        "Application tracking"
    )

    generated = client.post(
        "/apply/generate",
        data={
            "record_ids": str(record_id),
            "confirm_ai_processing": "true",
        },
        follow_redirects=False,
    )
    assert generated.status_code == 303
    draft = container.application_drafts.get(workspace.id, record_id)
    assert draft is not None
    assert draft.generated_action == DraftAction.CREATE

    saved = client.post(
        f"/apply/{record_id}/save",
        data={"content": "My carefully edited letter."},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert container.application_drafts.get(workspace.id, record_id).manually_edited

    for action in ("longer", "shorter", "recreate"):
        transformed = client.post(
            f"/apply/{record_id}/transform",
            data={"action": action, "confirm_ai_processing": "true"},
            follow_redirects=False,
        )
        assert transformed.status_code == 303
        assert container.application_drafts.get(
            workspace.id, record_id
        ).generated_action == DraftAction(action)

    refused_delete = client.post(
        f"/apply/{record_id}/delete",
        follow_redirects=False,
    )
    assert "Confirm+cover-letter+deletion" in refused_delete.headers["location"]
    deleted = client.post(
        f"/apply/{record_id}/delete",
        data={"confirm_delete": "true"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert container.application_drafts.get(workspace.id, record_id) is None


def test_apply_uses_latest_compass_facts_without_requiring_a_redundant_full_match(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    save_match(container, workspace, record_id, job, MatchDisposition.TOP)
    latest_preference = profile_fact(
        "application.preference",
        "Emphasize practical product ownership",
        ProfileSection.PREFERENCES,
    )
    workspace.session.profile.facts.append(latest_preference)
    container.workspaces.save(workspace)
    drafter = FakeApplicationDrafter()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    page = client.get(f"/apply?job={record_id}")
    generated = client.post(
        "/apply/generate",
        data={
            "record_ids": str(record_id),
            "confirm_ai_processing": "true",
        },
        follow_redirects=False,
    )

    assert page.status_code == 200
    assert "Drafts use its latest confirmed facts" in page.text
    assert re.search(
        rf'name="record_ids" value="{record_id}"\s+checked',
        page.text,
    )
    assert generated.status_code == 303
    assert drafter.calls
    assert any(
        fact.key == latest_preference.key and fact.value == latest_preference.value
        for fact in drafter.calls[-1]["confirmed_facts"]
    )


def test_apply_groups_drafts_by_job_and_preserves_exact_draft_focus(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    first_record_id, first_job = seed_job(container)
    second_record_id, second_job = seed_distinct_job(
        container,
        url="https://careers.example.com/jobs/controls-application",
        title="Controls Engineer",
        company="Second Products",
    )
    save_match_set(
        container,
        workspace,
        [(first_record_id, first_job), (second_record_id, second_job)],
    )
    drafter = FakeApplicationDrafter()
    service = ApplicationDraftService(container.application_drafts, drafter)
    first_draft = service.generate(
        workspace,
        first_record_id,
        first_job,
        DraftAction.CREATE,
        name="Concise",
    )
    selected_draft = service.generate(
        workspace,
        first_record_id,
        first_job,
        DraftAction.CREATE,
        name="Technical",
    )
    other_job_draft = service.generate(
        workspace,
        second_record_id,
        second_job,
        DraftAction.CREATE,
        name="Second role",
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    page = client.get(f"/apply?job={first_record_id}&draft={selected_draft.id}")

    assert page.status_code == 200
    assert '<details class="apply-selection-disclosure"' not in page.text
    assert (
        'role="group" aria-label="Matched jobs available for cover-letter generation"' in page.text
    )
    assert 'class="apply-consent-zone"' in page.text
    assert page.text.count("data-job-draft-group=") == 2
    assert page.text.count("data-draft-id=") == 3
    assert f'data-job-draft-group="{first_record_id}" open' in page.text
    assert f'data-job-draft-group="{second_record_id}" open' not in page.text
    assert f'data-draft-id="{selected_draft.id}" open' in page.text
    assert f'data-draft-id="{first_draft.id}" open' not in page.text
    assert f'data-draft-id="{other_job_draft.id}" open' not in page.text
    assert "2 Cover Letters" in page.text
    assert "1 Cover Letter" in page.text

    first_before = container.application_drafts.get_by_id(
        workspace.id,
        first_record_id,
        first_draft.id,
    )
    saved = client.post(
        f"/apply/{first_record_id}/save",
        data={
            "draft_id": str(selected_draft.id),
            "name": "Technical revised",
            "content": "A targeted manual revision.",
        },
        follow_redirects=False,
    )
    location = urlsplit(saved.headers["location"])
    parameters = parse_qs(location.query)
    assert saved.status_code == 303
    assert parameters["job"] == [str(first_record_id)]
    assert parameters["draft"] == [str(selected_draft.id)]
    assert location.fragment == f"draft-{selected_draft.id}"
    assert (
        container.application_drafts.get_by_id(
            workspace.id,
            first_record_id,
            selected_draft.id,
        ).content
        == "A targeted manual revision."
    )
    assert (
        container.application_drafts.get_by_id(
            workspace.id,
            first_record_id,
            first_draft.id,
        ).content
        == first_before.content
    )

    mismatch = client.get(f"/apply?job={first_record_id}&draft={other_job_draft.id}")
    assert mismatch.status_code == 404


def test_job_detail_creation_focus_keeps_all_candidates_and_other_drafts_collapsed(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    first_record_id, first_job = seed_job(container)
    second_record_id, second_job = seed_distinct_job(
        container,
        url="https://careers.example.com/jobs/second-application",
        title="Second Engineer",
        company="Other Products",
    )
    save_match_set(
        container,
        workspace,
        [(first_record_id, first_job), (second_record_id, second_job)],
    )
    drafter = FakeApplicationDrafter()
    ApplicationDraftService(container.application_drafts, drafter).generate(
        workspace,
        second_record_id,
        second_job,
        DraftAction.CREATE,
        name="Existing other-job draft",
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    detail = client.get(f"/jobs/{first_record_id}")
    page = client.get(f"/apply?job={first_record_id}&create=true")

    assert detail.status_code == 200
    assert f"/apply?job={first_record_id}&create=true" in detail.text
    assert page.status_code == 200
    assert f'data-generation-focus="{first_record_id}"' in page.text
    assert "Generate up to 5 cover letters at once" in page.text
    assert '<details class="apply-selection-disclosure"' not in page.text
    assert (
        'role="group" aria-label="Matched jobs available for cover-letter generation"' in page.text
    )
    assert 'class="apply-consent-zone"' in page.text
    generator = page.text[page.text.index('<form class="panel apply-picker"') :]
    generator = generator[: generator.index("</form>")]
    assert first_job.title in generator
    assert second_job.title in generator
    assert re.search(
        rf'name="record_ids" value="{first_record_id}"\s+checked',
        generator,
    )
    assert not re.search(
        rf'name="record_ids" value="{second_record_id}"\s+checked',
        generator,
    )
    assert f'data-job-draft-group="{second_record_id}"' in page.text
    assert f'data-job-draft-group="{second_record_id}" open' not in page.text
    assert "Existing other-job draft" in page.text


def test_job_detail_creation_focus_expands_only_the_target_job_when_it_has_drafts(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    first_record_id, first_job = seed_job(container)
    second_record_id, second_job = seed_distinct_job(
        container,
        url="https://careers.example.com/jobs/second-application-focus",
        title="Second Engineer",
        company="Other Products",
    )
    save_match_set(
        container,
        workspace,
        [(first_record_id, first_job), (second_record_id, second_job)],
    )
    drafter = FakeApplicationDrafter()
    drafts = ApplicationDraftService(container.application_drafts, drafter)
    target_draft = drafts.generate(
        workspace,
        first_record_id,
        first_job,
        DraftAction.CREATE,
        name="Existing target draft",
    )
    drafts.generate(
        workspace,
        second_record_id,
        second_job,
        DraftAction.CREATE,
        name="Existing other draft",
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    page = client.get(f"/apply?job={first_record_id}&create=true")

    assert page.status_code == 200
    assert f'data-job-draft-group="{first_record_id}" open' in page.text
    assert f'data-job-draft-group="{second_record_id}" open' not in page.text
    assert f'data-draft-id="{target_draft.id}" open' not in page.text
    assert first_job.title in page.text
    assert second_job.title in page.text


def test_apply_rejects_blocked_result_even_when_directly_posted(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    save_match(
        container,
        workspace,
        record_id,
        job,
        MatchDisposition.BLOCKED,
        created_at=NOW + timedelta(seconds=1),
    )
    drafter = FakeApplicationDrafter()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            application_drafter=drafter,
        )
    )

    response = client.post(
        "/apply/generate",
        data={
            "record_ids": str(record_id),
            "confirm_ai_processing": "true",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Blocked jobs are excluded from cover-letter generation" in response.text
    assert drafter.calls == []
    assert container.application_drafts.get(workspace.id, record_id) is None


def test_explicit_zero_model_price_means_unpriced_not_free() -> None:
    route = ModelRoute(
        task="application_draft",
        provider="openai",
        model="test-model",
        prompt_version="test",
        input_cost_per_million_usd=0,
        output_cost_per_million_usd=2,
    )

    assert estimate_cost(route, TokenUsage(input_tokens=100, output_tokens=50)) is None


def test_openai_application_adapter_disables_response_storage_and_bounds_output(
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.request: dict | None = None

        def parse(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(
                output_parsed=CoverLetterOutput(
                    letter=(
                        "Dear Hiring Team,\n\nMy confirmed embedded-software and Python "
                        "experience aligns with this role's published requirements. I would "
                        "welcome a conversation about the engineering work described.\n\nKind regards"
                    )
                ),
                usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
            )

    responses = FakeResponses()
    recorder = InMemoryInvocationRecorder()
    drafter = OpenAIApplicationDrafter(
        client=SimpleNamespace(responses=responses),
        recorder=recorder,
        model="test-model",
    )
    _record_id, job = seed_job(build_container(tmp_path))
    fact = profile_fact("skill.demonstrated", "Python", ProfileSection.EXPERIENCE)

    result = drafter.draft(
        job=job,
        confirmed_facts=[fact],
        action="create",
    )

    assert result.startswith("Dear Hiring Team")
    assert responses.request is not None
    assert responses.request["store"] is False
    assert responses.request["max_output_tokens"] == 1_200
    prompt = responses.request["input"][1]["content"]
    assert "skill.demonstrated: Python" in prompt
    assert "Return only the structured cover-letter output" in prompt
    assert len(recorder.invocations) == 1


def test_retention_deletes_application_draft_after_finite_inactivity(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = create_workspace(container)
    record_id, job = seed_job(container)
    service = ApplicationDraftService(container.application_drafts, FakeApplicationDrafter())
    service.generate(workspace, record_id, job, DraftAction.CREATE)
    old_update = NOW - timedelta(days=181)
    with container.database.session_factory.begin() as session:
        session.execute(
            update(ApplicationDraftRow)
            .where(ApplicationDraftRow.workspace_id == str(workspace.id))
            .values(updated_at=old_update)
        )

    report = run_retention(
        container.database,
        RetentionPolicy(application_draft_days=180),
        now=NOW,
    )

    assert report.application_drafts == 1
    assert container.application_drafts.get(workspace.id, record_id) is None
