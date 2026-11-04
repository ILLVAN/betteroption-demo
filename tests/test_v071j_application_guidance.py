from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select

from betteroption.accounts import RegistrationMode
from betteroption.application_guidance import (
    ApplicationChannel,
    ApplicationGuidance,
    ApplicationGuidanceEntry,
    ApplicationGuidanceField,
    ApplicationGuidanceOverrideRepository,
    ApplicationGuidanceOverrideRow,
    GuidanceProvenance,
    extract_application_guidance,
)
from betteroption.applications import ApplicationDraftService, DraftAction
from betteroption.container import ApplicationContainer
from betteroption.job_extraction import (
    ApplicationGuidanceDraft,
    ApplicationGuidanceEntryDraft,
    JobExtraction,
    UnverifiedEvidenceError,
)
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
from betteroption.providers.openai_application import CoverLetterOutput, OpenAIApplicationDrafter
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
URL = "https://careers.example.com/jobs/123"
SOURCE = """Example GmbH seeks a Quality Engineer in Berlin.
Ansprechpartnerin: Dr. Anna Muster, Talent Acquisition
Bitte senden Sie Ihren Lebenslauf und Ihr Anschreiben per E-Mail an jobs@example.com.
Attachments may be a maximum 5 MB.
Bewerbungsschluss: 31. August 2026.
"""


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'guidance.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )


def _job(guidance: ApplicationGuidance | None = None) -> JobPosting:
    return JobPosting(
        title="Quality Engineer",
        company="Example GmbH",
        location="Berlin",
        summary="Assure product quality.",
        source_type=JobSourceType.URL_TEXT,
        source_name=URL,
        source_url=URL,
        requested_url=URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=SOURCE,
        application_guidance=guidance or extract_application_guidance(SOURCE, source_url=URL),
        facts=[
            JobFact(
                key="skill.name",
                value="Quality assurance",
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="Quality Engineer",
            )
        ],
        observed_at=NOW,
    )


def _seed(container: ApplicationContainer, job: JobPosting):
    document = FetchedDocument(
        requested_url=URL,
        final_url=URL,
        status_code=200,
        content_type="text/html",
        text=SOURCE,
        fetched_at=NOW,
    )
    return container.repository.store_revision(document, job, JobObservationKind.NEW)


def _workspace(container: ApplicationContainer):
    session = new_session()
    session.profile.facts = [
        ProfileFact(
            key="skill.demonstrated",
            value="Quality assurance",
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.EXPERIENCE,
                text="Quality assurance",
            ),
        )
    ]
    return container.workspaces.create(session)


def test_deterministic_guidance_is_explicit_and_source_grounded() -> None:
    guidance = extract_application_guidance(SOURCE, source_url=URL)

    assert guidance.contact_name is not None
    assert guidance.contact_name.value == "Dr. Anna Muster"
    assert guidance.contact_name.evidence_quote in SOURCE
    assert guidance.contact_role is not None
    assert guidance.contact_role.value == "Talent Acquisition"
    assert guidance.contact_email is not None
    assert guidance.contact_email.value == "jobs@example.com"
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMAIL.value
    assert {item.value for item in guidance.requested_documents} == {"CV", "Cover letter"}
    assert guidance.max_file_size is not None
    assert guidance.max_file_size.value == "5 MB"
    assert guidance.application_deadline is not None
    _job(guidance)


def test_model_guidance_must_have_verbatim_evidence_and_can_fail_closed() -> None:
    extraction = JobExtraction(
        title="Quality Engineer",
        company="Example GmbH",
        location="Berlin",
        summary="Assure product quality.",
        facts=[],
        application_guidance=ApplicationGuidanceDraft(
            contact_name=ApplicationGuidanceEntryDraft(
                value="Invented Person",
                evidence_quote="This name is not in the advertisement",
            )
        ),
    )
    arguments = dict(
        source_text=SOURCE,
        source_name=URL,
        source_url=URL,
        requested_url=URL,
        url_http_status=200,
        url_checked_at=NOW,
    )

    with pytest.raises(UnverifiedEvidenceError):
        extraction.to_job_posting(**arguments)
    disabled = extraction.to_job_posting(**arguments, include_application_guidance=False)
    assert disabled.application_guidance.is_empty


def test_persona_override_can_correct_or_explicitly_clear_source_values(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)
    repository = ApplicationGuidanceOverrideRepository(container.database)

    saved = repository.save(
        workspace.id,
        record.id,
        edited_fields={
            ApplicationGuidanceField.CONTACT_NAME,
            ApplicationGuidanceField.CONTACT_EMAIL,
            ApplicationGuidanceField.MAX_PAGES,
        },
        contact_name="Samira Recruiter",
        contact_email=None,
        max_pages=2,
    )
    effective = repository.effective(workspace.id, record.id, job.application_guidance)

    assert saved.contact_name == "Samira Recruiter"
    assert effective.contact_name is not None
    assert effective.contact_name.value == "Samira Recruiter"
    assert effective.contact_name.provenance == GuidanceProvenance.USER_OVERRIDE
    assert effective.contact_email is None
    assert effective.max_pages is not None
    assert effective.max_pages.value == "2"
    assert effective.contact_role == job.application_guidance.contact_role


def test_postal_address_override_collapses_repeated_schema_representation_on_save(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)
    repository = container.application_guidance

    saved = repository.save(
        workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.POSTAL_ADDRESS},
        postal_address=(
            "PostalAddress Siemensstraße 30, 63755 DE "
            "PostalAddress Siemensstraße 30 Alzenau 63755 DE"
        ),
    )
    effective = repository.effective(workspace.id, record.id, job.application_guidance)

    assert saved.postal_address == "Siemensstraße 30 Alzenau 63755 DE"
    assert effective.postal_address is not None
    assert effective.postal_address.value == "Siemensstraße 30 Alzenau 63755 DE"
    assert effective.postal_address.provenance == GuidanceProvenance.USER_OVERRIDE


def test_legacy_postal_address_override_is_normalized_when_made_effective(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)
    now = datetime.now(timezone.utc)
    with container.database.session_factory.begin() as database_session:
        database_session.add(
            ApplicationGuidanceOverrideRow(
                id=str(uuid4()),
                workspace_id=str(workspace.id),
                job_record_id=str(record.id),
                payload_json=json.dumps(
                    {
                        "postal_address": (
                            "PostalAddress Friedrichstraße 41, 01067 Dresden Sachsen DE "
                            "PostalAddress Friedrichstraße 41 01067 Dresden Sachsen DE"
                        )
                    }
                ),
                edited_fields_json=json.dumps([ApplicationGuidanceField.POSTAL_ADDRESS.value]),
                created_at=now,
                updated_at=now,
            )
        )

    effective = container.application_guidance.effective(
        workspace.id,
        record.id,
        job.application_guidance,
    )

    assert effective.postal_address is not None
    assert effective.postal_address.value == "Friedrichstraße 41, 01067 Dresden Sachsen DE"


def test_postal_address_override_preserves_genuinely_distinct_addresses(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)

    saved = container.application_guidance.save(
        workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.POSTAL_ADDRESS},
        postal_address=(
            "PostalAddress Main Street 1, 10115 Berlin PostalAddress Branch Road 2, 20095 Hamburg"
        ),
    )
    effective = container.application_guidance.effective(
        workspace.id,
        record.id,
        job.application_guidance,
    )

    expected = "Main Street 1, 10115 Berlin / Branch Road 2, 20095 Hamburg"
    assert saved.postal_address == expected
    assert effective.postal_address is not None
    assert effective.postal_address.value == expected


def test_guidance_override_follows_persona_replacement_and_stays_isolated(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    other_persona = container.personas.create(account.id, "Other", maximum_personas=5)
    other_account = container.accounts.create(
        "other@example.com",
        "Other Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    other_account_persona = container.personas.create(
        other_account.id,
        "Main",
        maximum_personas=5,
    )
    first_workspace = container.workspaces.create(
        account_id=account.id,
        persona_id=persona.id,
    )
    sibling_workspace = container.workspaces.create(
        account_id=account.id,
        persona_id=other_persona.id,
    )
    other_account_workspace = container.workspaces.create(
        account_id=other_account.id,
        persona_id=other_account_persona.id,
    )
    job = _job()
    record = _seed(container, job)
    repository = container.application_guidance
    repository.save(
        first_workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="First Recruiter",
    )

    replacement_workspace = container.workspaces.create(
        account_id=account.id,
        persona_id=persona.id,
    )

    inherited = repository.get(replacement_workspace.id, record.id)
    assert inherited is not None
    assert inherited.workspace_id == first_workspace.id
    assert inherited.contact_name == "First Recruiter"
    effective = repository.effective(
        replacement_workspace.id,
        record.id,
        job.application_guidance,
    )
    assert effective.contact_name is not None
    assert effective.contact_name.value == "First Recruiter"
    assert repository.get(sibling_workspace.id, record.id) is None
    assert repository.get(other_account_workspace.id, record.id) is None

    updated = repository.save(
        replacement_workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="Replacement Recruiter",
    )
    assert updated.workspace_id == first_workspace.id
    with container.database.session_factory() as database_session:
        scoped_rows = database_session.scalars(
            select(ApplicationGuidanceOverrideRow).where(
                ApplicationGuidanceOverrideRow.workspace_id.in_(
                    [str(first_workspace.id), str(replacement_workspace.id)]
                ),
                ApplicationGuidanceOverrideRow.job_record_id == str(record.id),
            )
        ).all()
    assert len(scoped_rows) == 1

    repository.save(
        sibling_workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="Sibling Recruiter",
    )
    assert repository.delete(replacement_workspace.id, record.id)
    assert repository.get(first_workspace.id, record.id) is None
    sibling = repository.get(sibling_workspace.id, record.id)
    assert sibling is not None
    assert sibling.contact_name == "Sibling Recruiter"


def test_guidance_override_prefers_latest_legacy_duplicate_and_deletes_scope(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    account = container.accounts.create(
        "duplicates@example.com",
        "Duplicate Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.create(account.id, "Main", maximum_personas=5)
    first_workspace = container.workspaces.create(
        account_id=account.id,
        persona_id=persona.id,
    )
    replacement_workspace = container.workspaces.create(
        account_id=account.id,
        persona_id=persona.id,
    )
    record = _seed(container, _job())
    repository = container.application_guidance
    original = repository.save(
        first_workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="Older Recruiter",
    )
    later = original.updated_at + timedelta(hours=1)
    with container.database.session_factory.begin() as database_session:
        database_session.add(
            ApplicationGuidanceOverrideRow(
                id=str(uuid4()),
                workspace_id=str(replacement_workspace.id),
                job_record_id=str(record.id),
                payload_json=json.dumps({"contact_name": "Latest Recruiter"}),
                edited_fields_json=json.dumps([ApplicationGuidanceField.CONTACT_NAME.value]),
                created_at=later,
                updated_at=later,
            )
        )

    latest = repository.get(first_workspace.id, record.id)
    assert latest is not None
    assert latest.workspace_id == replacement_workspace.id
    assert latest.contact_name == "Latest Recruiter"

    reused = repository.save(
        first_workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="Reused Latest Row",
    )
    assert reused.workspace_id == replacement_workspace.id
    assert reused.contact_name == "Reused Latest Row"
    assert repository.delete(first_workspace.id, record.id)
    assert repository.get(replacement_workspace.id, record.id) is None


def test_effective_verified_contact_reaches_cover_letter_provider(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)
    container.application_guidance.save(
        workspace.id,
        record.id,
        edited_fields={ApplicationGuidanceField.CONTACT_NAME},
        contact_name="Samira Recruiter",
    )

    class Drafter:
        model = "fake"

        def __init__(self) -> None:
            self.job = None

        def draft(self, *, job, confirmed_facts, action, existing_text=None):
            del confirmed_facts, action, existing_text
            self.job = job
            return "Dear Samira Recruiter,\n\nYour quality role aligns with my verified experience.\n\nKind regards"

    drafter = Drafter()
    service = ApplicationDraftService(
        container.application_drafts,
        drafter,
        container.application_guidance,
    )
    service.generate(workspace, record.id, job, DraftAction.CREATE)

    assert drafter.job.application_guidance.contact_name.value == "Samira Recruiter"
    assert (
        drafter.job.application_guidance.contact_name.provenance == GuidanceProvenance.USER_OVERRIDE
    )


def test_openai_cover_letter_prompt_keeps_contact_identity_local(
    tmp_path: Path,
) -> None:
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_parsed=CoverLetterOutput(
                letter=(
                    "Sehr geehrte Frau Dr. Anna Muster,\n\nMy confirmed quality-assurance work "
                    "is relevant to this role and I would welcome a conversation.\n\n"
                    "Kind regards"
                )
            ),
            usage=None,
        )

    provider = OpenAIApplicationDrafter(
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    fact = _workspace(_container(tmp_path)).session.profile.facts[0]
    letter = provider.draft(job=_job(), confirmed_facts=[fact], action="create")
    prompt = captured["input"][1]["content"]

    assert "Dr. Anna Muster" not in prompt
    assert "Talent Acquisition" not in prompt
    assert "Contact name:" not in prompt
    assert "Contact role:" not in prompt
    assert "Application channel: email (advertisement)" in prompt
    assert "jobs@example.com" not in prompt
    assert "Application email:" not in prompt
    assert "Application phone:" not in prompt
    assert "Application URL:" not in prompt
    assert SOURCE not in prompt
    assert letter.startswith("[LOCAL SALUTATION]\n")
    assert "Dr. Anna Muster" not in letter
    assert "Frau" not in letter


def test_openai_cover_letter_prompt_scrubs_contact_coordinates_from_every_surface(
    tmp_path: Path,
) -> None:
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_parsed=CoverLetterOutput(
                letter=(
                    "Dear Dr. Anna Muster,\n\nMy confirmed quality-assurance work is relevant "
                    "to this role and I would welcome a conversation.\n\nKind regards"
                )
            ),
            usage=None,
        )

    def private_entry(value: str) -> ApplicationGuidanceEntry:
        return ApplicationGuidanceEntry(
            value=value,
            provenance=GuidanceProvenance.USER_OVERRIDE,
        )

    guidance = ApplicationGuidance(
        contact_name=private_entry("Dr. Anna Muster"),
        contact_role=private_entry("Talent Acquisition"),
        instructions=(
            private_entry(
                "Questions: guidance@example.org, www.apply.example/jobs/9, +33 1 42 68 53 00."
            ),
        ),
    )
    job = JobPosting(
        title="Quality Engineer — questions for Dr. Anna Muster at +49 30 1234567",
        company="Example GmbH",
        location="Berlin",
        summary=(
            "Talent Acquisition contact: Dr. Anna Muster. "
            "For further details, speak with Jane Doe, Senior Recruiter. "
            "Apply at www.summary.example/apply. Posted 01.08.2026. "
            "Salary €55,000–€65,000 gross/year."
        ),
        source_type=JobSourceType.URL_TEXT,
        source_name=URL,
        source_url=URL,
        requested_url=URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text="For evidence call (030) 765 43 21 about quality assurance.",
        application_guidance=guidance,
        facts=[
            JobFact(
                key="skill.name",
                value=(
                    "Quality assurance via qa-fact@example.net or "
                    "http://fact.example/contact; ask Dr. Anna Muster"
                ),
                kind=JobFactKind.REQUIREMENT,
                evidence_quote="call (030) 765 43 21",
            )
        ],
        observed_at=NOW,
    )
    compass_fact = (
        _workspace(_container(tmp_path))
        .session.profile.facts[0]
        .model_copy(
            update={
                "value": (
                    "Portfolio www.compass.example; phone 020 7946 0958; "
                    "local note for Dr. Anna Muster"
                ),
            }
        )
    )
    provider = OpenAIApplicationDrafter(
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )

    letter = provider.draft(
        job=job,
        confirmed_facts=[compass_fact],
        action="longer",
        existing_text=(
            "Dear Dr. Anna Muster,\n\nReach me on +1 (202) 555-0187, at "
            "draft@example.com, or through https://draft.example/me."
        ),
    )
    prompt = captured["input"][1]["content"]

    for private_value in (
        "+49 30 1234567",
        "www.summary.example/apply",
        "qa-fact@example.net",
        "http://fact.example/contact",
        "(030) 765 43 21",
        "www.compass.example",
        "020 7946 0958",
        "guidance@example.org",
        "www.apply.example/jobs/9",
        "+33 1 42 68 53 00",
        "+1 (202) 555-0187",
        "draft@example.com",
        "https://draft.example/me",
        "Dr. Anna Muster",
        "Jane Doe",
        "Senior Recruiter",
        "Talent Acquisition",
    ):
        assert private_value not in prompt
    assert "[application email kept local]" in prompt
    assert "[application URL kept local]" in prompt
    assert "[application phone kept local]" in prompt
    assert "Dr. Anna Muster" not in prompt
    assert "Talent Acquisition" not in prompt
    assert "Contact name:" not in prompt
    assert "Contact role:" not in prompt
    assert "01.08.2026" in prompt
    assert "€55,000–€65,000 gross/year" in prompt
    assert letter.startswith("[LOCAL SALUTATION]\n")
    assert "Dr. Anna Muster" not in letter


def test_openai_cover_letter_prompt_keeps_free_form_contact_instruction_local(
    tmp_path: Path,
) -> None:
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_parsed=CoverLetterOutput(
                letter=(
                    "Dear Hiring Team,\n\nMy confirmed quality-assurance experience is "
                    "relevant to this role and I welcome a conversation.\n\nKind regards"
                )
            ),
            usage=None,
        )

    guidance = ApplicationGuidance(
        instructions=(
            ApplicationGuidanceEntry(
                value="Please send your application to Jane Recruiter, Talent Acquisition Lead.",
                provenance=GuidanceProvenance.USER_OVERRIDE,
            ),
        )
    )
    job = _job().model_copy(update={"application_guidance": guidance})
    fact = _workspace(_container(tmp_path)).session.profile.facts[0]
    provider = OpenAIApplicationDrafter(
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )

    provider.draft(job=job, confirmed_facts=[fact], action="create")
    prompt = captured["input"][1]["content"]

    assert "Jane Recruiter" not in prompt
    assert "Talent Acquisition Lead" not in prompt


def test_hosted_guidance_gate_requires_legal_and_processor_review() -> None:
    assert Settings(app_environment="local").application_guidance_available
    assert not Settings(
        app_environment="staging",
        legal_review_completed=True,
        processor_review_completed=False,
    ).application_guidance_available
    assert Settings(
        app_environment="staging",
        legal_review_completed=True,
        processor_review_completed=True,
    ).application_guidance_available


def test_application_guidance_migration_follows_employer_scoring() -> None:
    config = Config()
    config.set_main_option("script_location", "src/betteroption/migrations")
    revision = ScriptDirectory.from_config(config).get_revision("0026_application_guidance")

    assert revision is not None
    assert revision.down_revision == "0025_employer_reputation_scoring"


def test_job_detail_guidance_tile_saves_clears_and_restores_private_copy(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = _workspace(container)
    job = _job()
    record = _seed(container, job)
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    initial = client.get(f"/jobs/{record.id}")
    assert initial.status_code == 200
    assert "Application contact and process" in initial.text
    assert "Dr. Anna Muster" in initial.text
    assert "Source-published evidence and provenance" in initial.text

    saved = client.post(
        f"/jobs/{record.id}/application-guidance",
        data={
            "contact_name": "Samira Recruiter",
            "contact_role": "Hiring lead",
            "contact_email": "",
            "contact_phone": "",
            "application_channel": "employer_portal",
            "application_url": "https://careers.example.com/apply/123",
            "requested_documents": "CV\nPortfolio",
            "max_file_size": "10 MB",
            "max_pages": "2",
            "application_deadline": "15 September 2026",
            "instructions": "Use the employer portal only.",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    override = container.application_guidance.get(workspace.id, record.id)
    assert override is not None
    assert override.contact_name == "Samira Recruiter"
    assert override.contact_email is None
    assert override.edited_fields == frozenset(ApplicationGuidanceField)

    corrected = client.get(f"/jobs/{record.id}")
    assert "Samira Recruiter" in corrected.text
    assert "Restore all source-published values" in corrected.text
    assert "Dr. Anna Muster" in corrected.text  # retained only in collapsed provenance

    restored = client.post(
        f"/jobs/{record.id}/application-guidance/restore",
        follow_redirects=False,
    )
    assert restored.status_code == 303
    assert container.application_guidance.get(workspace.id, record.id) is None
    source_again = client.get(f"/jobs/{record.id}")
    assert "Dr. Anna Muster" in source_again.text
    assert "Restore all source-published values" not in source_again.text
