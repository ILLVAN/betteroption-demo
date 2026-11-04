from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from betteroption.application_guidance import ApplicationGuidanceField
from betteroption.job_overrides import JobEvidenceOverride, JobEvidenceOverrideKind
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.matching import (
    CONTEXT_COMPANY_NAME,
    CONTEXT_EMPLOYER_TYPES,
    CONTEXT_REPUTATION_SUMMARY,
)
from betteroption.profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.session import new_session
from betteroption.web import create_app
from test_v071i_evidence_web import (
    _container,
    _register,
    _seed_workspace_and_job,
)


def _confirmed_workspace(container):
    (account,) = container.accounts.list_accounts()
    (persona,) = container.personas.list_for_account(account.id)
    session = new_session()
    session.profile.facts = [
        ProfileFact(
            key="skill.name",
            value="Python",
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.DIRECTION,
                text="I want a Python engineering role.",
            ),
        )
    ]
    workspace = container.workspaces.create(
        session,
        account_id=account.id,
        persona_id=persona.id,
    )
    return account, persona, workspace


def _manual_job(
    container,
    workspace,
    slug: str,
    *,
    with_source_url: bool = True,
    company: str = "Example Products GmbH",
):
    source_url = f"https://careers.example.com/jobs/{slug}" if with_source_url else None
    source = (
        f"Manual advertisement {slug}. Example Products needs a Python engineer to "
        "design, test, and document reliable embedded product software with a calm team."
    )
    job = JobPosting(
        title=f"Manual {slug.title()} Engineer",
        company=company,
        location="Berlin",
        summary="Develop and test embedded products.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name=source_url or "Manual input",
        source_url=source_url,
        requested_url=source_url,
        source_text=source,
        observed_at=datetime.now(timezone.utc),
    )
    record = container.repository.store_manual_revision(
        source_url or f"https://manual.betteroption.local/{slug}",
        job,
        JobObservationKind.NEW,
    )
    container.results.grant_job(workspace.id, record.id)
    return record


def _manual_job_with_override_sources(container, workspace):
    source_url = "https://manual.example/jobs/override-evidence"
    source = """Example Products GmbH is a SaaS product company and software product
manufacturer in Berlin. We seek a Python engineer for our industrial product platform.
Ansprechpartnerin: Dr. Anna Muster, Talent Acquisition
Bitte senden Sie Ihren Lebenslauf und Ihr Anschreiben per E-Mail an jobs@example.com.
Attachments may be a maximum 5 MB.
Bewerbungsschluss: 31. August 2026.
"""
    job = JobPosting(
        title="Manual Product Engineer",
        company="Example Products GmbH",
        location="Berlin",
        summary="Build and maintain a SaaS product.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name=source_url,
        source_url=source_url,
        requested_url=source_url,
        source_text=source,
        observed_at=datetime.now(timezone.utc),
    )
    record = container.repository.store_manual_revision(
        source_url,
        job,
        JobObservationKind.NEW,
    )
    container.results.grant_job(workspace.id, record.id)
    return record


def test_company_override_updates_detail_archive_and_match_card_headers(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace = _confirmed_workspace(container)
        record = _manual_job(container, workspace, "unknown-company", company="Unknown")
        started = client.post(f"/jobs/{record.id}/match", follow_redirects=False)
        assert started.status_code == 303
        task_id = UUID(started.headers["location"].removeprefix("/tasks/"))
        assert client.app.state.background_worker.run_once()
        finished = container.background_tasks.get(task_id)
        assert finished is not None and finished.status.value == "succeeded"

        saved = client.post(
            f"/jobs/{record.id}/evidence/bulk",
            data={
                "evidence_kind": "context",
                "evidence_key": CONTEXT_COMPANY_NAME,
                "evidence_initial": "",
                "evidence_value": "Corrected Employer AG",
            },
            follow_redirects=False,
        )

        assert saved.status_code == 303
        detail = BeautifulSoup(client.get(f"/jobs/{record.id}").text, "html.parser")
        archive = BeautifulSoup(client.get("/jobs").text, "html.parser")
        matches = BeautifulSoup(client.get("/matches").text, "html.parser")
        apply_page = BeautifulSoup(client.get("/apply").text, "html.parser")

    assert detail.select_one(".detail-hero .company").get_text(strip=True) == (
        "Corrected Employer AG"
    )
    identity = detail.select_one(".employer-facts-workbench .evidence-comparison")
    assert identity is not None
    assert "has-user-override" in identity.get("class", [])
    assert identity.select_one(".evidence-auto strong").get_text(strip=True) == ("Unknown")
    assert identity.select_one(".evidence-user input[name='evidence_value']")["value"] == (
        "Corrected Employer AG"
    )
    for page in (archive, matches):
        card = page.select_one(f'[data-opportunity-record-id="{record.id}"]')
        assert card is not None
        assert card.select_one(".company").get_text(strip=True) == "Corrected Employer AG"
        assert "Corrected Employer AG" in card.select_one(".card-body-link")["aria-label"]
    candidate = apply_page.select_one(f'input[value="{record.id}"]')
    assert candidate is not None
    assert "Corrected Employer AG" in candidate.parent.get_text(" ", strip=True)

    css = (Path("src/betteroption/web/static/app.css")).read_text(encoding="utf-8")
    assert ".evidence-comparison.has-user-override > .evidence-auto" in css
    assert "text-decoration: line-through" in css


def test_manual_job_detail_can_create_the_first_single_job_match(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace = _confirmed_workspace(container)
        target = _manual_job(container, workspace, "selected", with_source_url=False)
        untouched = _manual_job(container, workspace, "untouched", with_source_url=False)

        before = client.get(f"/jobs/{target.id}")
        assert before.status_code == 200
        assert "Match this job only" in before.text
        assert "Only this job is evaluated" in before.text

        started = client.post(f"/jobs/{target.id}/match", follow_redirects=False)

        assert started.status_code == 303
        assert started.headers["location"].startswith("/tasks/")
        task_id = UUID(started.headers["location"].removeprefix("/tasks/"))
        payload = container.background_single_job_matches.get(task_id)
        assert payload is not None
        assert payload.job_record_id == target.id
        assert client.app.state.background_worker.run_once()

        finished = container.background_tasks.get(task_id)
        assert finished is not None
        assert finished.status.value == "succeeded", (finished.error_message, finished.message)
        assert "without+running+the+full+corpus" in (finished.result_url or "")
        run = container.results.latest_run(workspace.id)
        assert run is not None
        assert {item.job_record_id for item in run.results} == {target.id}
        assert run.metrics is not None and run.metrics.jobs_evaluated == 1
        assert container.results.get_interaction(workspace.id, untouched.id) is None

        matched_detail = client.get(f"/jobs/{target.id}")
        untouched_detail = client.get(f"/jobs/{untouched.id}")
        assert matched_detail.status_code == 200
        assert "Traceable compatibility" in matched_detail.text
        assert "Match this job only" not in matched_detail.text
        assert "Match this job only" in untouched_detail.text


def test_new_manual_job_match_merges_into_current_results_without_rematching_them(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, existing = _seed_workspace_and_job(container)
        workspace.session.profile.facts.append(
            ProfileFact(
                key="role.family",
                value="product engineering",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.DIRECTION,
                    text="I want a product engineering role.",
                ),
            )
        )
        container.workspaces.save(workspace)
        before = container.results.latest_run(workspace.id)
        assert before is not None
        existing_before = next(item for item in before.results if item.job_record_id == existing.id)
        manual = _manual_job(container, workspace, "new-after-match")

        started = client.post(f"/jobs/{manual.id}/match", follow_redirects=False)
        assert started.status_code == 303
        task_id = UUID(started.headers["location"].removeprefix("/tasks/"))
        assert client.app.state.background_worker.run_once()

    finished = container.background_tasks.get(task_id)
    assert finished is not None and finished.status.value == "succeeded"
    after = container.results.latest_run(workspace.id)
    assert after is not None
    assert after.id != before.id
    assert {item.job_record_id for item in after.results} == {existing.id, manual.id}
    assert after.metrics is not None and after.metrics.jobs_evaluated == 1
    existing_after = next(item for item in after.results if item.job_record_id == existing.id)
    assert existing_after.result.model_dump_json() == existing_before.result.model_dump_json()


def test_match_this_manual_job_only_cannot_cross_persona_grants(tmp_path: Path) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, _persona, owner_workspace = _confirmed_workspace(container)
        record = _manual_job(container, owner_workspace, "private")
        other_persona = container.personas.create(
            account.id,
            "Other search",
            maximum_personas=5,
        )
        other_session = new_session()
        other_session.profile.facts = list(owner_workspace.session.profile.facts)
        container.workspaces.create(
            other_session,
            account_id=account.id,
            persona_id=other_persona.id,
        )
        switched = client.post(
            f"/personas/{other_persona.id}/switch",
            follow_redirects=False,
        )
        assert switched.status_code == 303

        refused = client.post(f"/jobs/{record.id}/match", follow_redirects=False)

    assert refused.status_code == 404
    assert container.results.latest_run(owner_workspace.id) is None


def test_all_job_detail_overrides_keep_automatic_values_visible_and_struck(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace = _confirmed_workspace(container)
        record = _manual_job_with_override_sources(container, workspace)
        started = client.post(f"/jobs/{record.id}/match", follow_redirects=False)
        assert started.status_code == 303
        assert client.app.state.background_worker.run_once()

        container.job_overrides.upsert_many(
            [
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record.id,
                    kind=JobEvidenceOverrideKind.CONTEXT,
                    target_key=CONTEXT_EMPLOYER_TYPES,
                    target_label="Employer types",
                    text_value="consultancy,non_profit",
                ),
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record.id,
                    kind=JobEvidenceOverrideKind.CONTEXT,
                    target_key=CONTEXT_REPUTATION_SUMMARY,
                    target_label="Employer reputation context",
                    text_value="My private current review summary.",
                ),
            ]
        )
        guidance_saved = client.post(
            f"/jobs/{record.id}/application-guidance",
            data={
                "contact_name": "Samira Recruiter",
                "contact_role": "Hiring lead",
                "contact_email": "",
                "contact_phone": "+49 30 123456",
                "postal_address": "Example Street 1, 10115 Berlin",
                "application_channel": "employer_portal",
                "application_url": "https://manual.example/apply/override-evidence",
                "requested_documents": "CV\nPortfolio",
                "max_file_size": "10 MB",
                "max_pages": "2",
                "application_deadline": "15 September 2026",
                "instructions": "Use the employer portal only.",
            },
            follow_redirects=False,
        )
        assert guidance_saved.status_code == 303
        override = container.application_guidance.get(workspace.id, record.id)
        assert override is not None
        assert override.edited_fields == frozenset(ApplicationGuidanceField)

        detail = BeautifulSoup(client.get(f"/jobs/{record.id}").text, "html.parser")

    employer_types = detail.select_one(".employer-type-comparison.has-user-override")
    assert employer_types is not None
    automatic_types = {
        value.get_text(" ", strip=True)
        for value in employer_types.select(".evidence-auto .evidence-original-value")
    }
    assert {"Producer / manufacturer", "Product company"} <= automatic_types
    selected_types = {
        checkbox["value"]
        for checkbox in employer_types.select(
            ".evidence-user input[data-employer-type-checkbox][checked]"
        )
    }
    assert selected_types == {"consultancy", "non_profit"}
    assert employer_types.select_one(".evidence-column-label.evidence-original-value") is None
    assert employer_types.select_one(".evidence-auto small.evidence-original-value") is None

    reputation = detail.select_one(".reputation-context-comparison.has-user-override")
    assert reputation is not None
    original_reputation = reputation.select_one(".evidence-auto p.evidence-original-value")
    assert original_reputation is not None
    assert "No attributed employer certification" in original_reputation.get_text()
    private_reputation = reputation.select_one(".evidence-user input[name='evidence_value']")
    assert private_reputation is not None
    assert private_reputation["value"] == "My private current review summary."
    reputation_sources = detail.select_one("#employer-reputation .evidence-details")
    assert reputation_sources is not None
    assert reputation_sources.select_one(".evidence-original-value") is None
    assert reputation_sources.select_one("a.source-url") is not None

    guidance = detail.select_one(".application-guidance-comparison.has-user-override")
    assert guidance is not None
    original_contact = guidance.select_one(
        ".evidence-auto [data-guidance-field='contact_name'] dd.evidence-original-value"
    )
    assert original_contact is not None
    assert original_contact.get_text(strip=True) == "Dr. Anna Muster"
    corrected_contact = guidance.select_one(
        ".evidence-user [data-guidance-field='contact_name'] dd"
    )
    assert corrected_contact is not None
    assert corrected_contact.get_text(strip=True) == "Samira Recruiter"
    assert "evidence-original-value" not in corrected_contact.get("class", [])
    assert guidance.select_one("dt.evidence-original-value") is None
    provenance = detail.select_one(".application-guidance-source-item")
    assert provenance is not None
    assert "Dr. Anna Muster" in provenance.get_text(" ", strip=True)
    assert provenance.select_one(".evidence-original-value") is None


def test_original_value_css_does_not_strike_labels_or_provenance() -> None:
    css = Path("src/betteroption/web/static/app.css").read_text(encoding="utf-8")
    template = Path("src/betteroption/web/templates/job_detail.html").read_text(encoding="utf-8")

    assert ".evidence-comparison.has-user-override .evidence-original-value" in css
    assert "text-decoration: line-through" in css
    assert "> .evidence-auto > :is(" not in css
    assert 'class="evidence-original-value"' in template
    assert "route-duration{% if saved %} evidence-original-value{% endif %}" in template
    assert "{{ automatic_outcome.value }}{% if saved %} evidence-original-value" in template
    assert "automatic_matched else 'unknown' }}{% if saved %} evidence-original-value" in template
