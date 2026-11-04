from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.application_guidance import ApplicationChannel, extract_application_guidance
from betteroption.container import ApplicationContainer
from betteroption.job_corpus import JobCorpusService
from betteroption.job_repository import JobObservationKind, JobRepository
from betteroption.jobs import JobPosting, JobSourceType
from betteroption.matching import MatchDisposition, MatchResult, MatchRun
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.url_ingestion import UrlFailureKind, UrlIngestionError
from betteroption.web import create_app


URL = "https://careers.example.eu/jobs/42"


class FailingFetcher:
    def __init__(self, error: UrlIngestionError) -> None:
        self.error = error

    def fetch(self, url: str):
        raise self.error


def test_flattened_german_ats_text_keeps_application_package_useful() -> None:
    source = (
        "Quality Engineer in Frankfurt. So kannst Du uns erreichen! Klingt nach dir? "
        "Dann freuen wir uns auf deine Bewerbung! Schick uns deinen Lebenslauf "
        "(ein Motivationsschreiben brauchst du nicht zwingend) und erzähl uns in ein "
        "paar Zeilen, warum du Lust auf diese Rolle hast. Ansprechpartner: Jonas Müller, "
        "Talent Acquisition Manager. Telefon: +49 69 123 45 67. "
        "Bewerbungsschluss: 30.09.2026."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.contact_name is not None
    assert guidance.contact_name.value == "Jonas Müller"
    assert guidance.contact_role is not None
    assert guidance.contact_role.value == "Talent Acquisition Manager"
    assert guidance.contact_phone is not None
    assert guidance.contact_phone.value == "+49 69 123 45 67"
    assert {item.value for item in guidance.requested_documents} == {
        "CV",
        "Cover letter (optional)",
    }
    assert guidance.application_deadline is not None
    assert guidance.instructions
    assert all(item.evidence_quote in source for item in guidance.entries())


def test_german_email_package_and_constraints_are_extracted_without_a_model() -> None:
    source = (
        "Wir haben Ihr Interesse geweckt? Dann senden Sie uns Ihre Bewerbung - bitte per "
        "E-Mail an bewerbung@hema-group.com. Wir freuen uns auf Sie! Bitte senden Sie "
        "Lebenslauf und Zeugnisse. Die Unterlagen dürfen höchstens 8 MB groß sein."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.contact_email is not None
    assert guidance.contact_email.value == "bewerbung@hema-group.com"
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMAIL.value
    assert {item.value for item in guidance.requested_documents} == {"CV", "Certificates"}
    assert guidance.max_file_size is not None
    assert guidance.max_file_size.value == "8 MB"


def test_schema_workplace_is_available_as_published_address_without_postal_channel() -> None:
    source = (
        "Test Automation Engineer. PostalAddress Deutschland Frankfurt am Main Hessen "
        "60322 Nicht vorhanden. Bewerben Sie sich über unser Karriereportal."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.postal_address is not None
    assert guidance.postal_address.value == "60322 Frankfurt am Main Hessen, Deutschland"
    assert guidance.postal_address.evidence_quote in source
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMPLOYER_PORTAL.value


def test_flattened_multiple_schema_workplaces_keep_verbatim_evidence() -> None:
    source = (
        "Test Automation Engineer. PostalAddress Deutschland Frankfurt am Main Hessen "
        "60322 Nicht vorhanden PostalAddress Deutschland Frankfurt am Main Hessen "
        "60311 Nicht vorhanden. Bewerben Sie sich über unser Karriereportal."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.postal_address is not None
    assert "60322 Frankfurt am Main Hessen, Deutschland" in guidance.postal_address.value
    assert "60311 Frankfurt am Main Hessen, Deutschland" in guidance.postal_address.value
    assert guidance.postal_address.evidence_quote in source
    assert all(item.evidence_quote in source for item in guidance.entries())


def test_published_street_address_does_not_invent_postal_application_channel() -> None:
    source = (
        "Data Analyst at Example GmbH. Office: Musterstraße 12, 10115 Berlin. "
        "Use the Apply button to submit your application."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.postal_address is not None
    assert "Musterstraße 12" in guidance.postal_address.value
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMPLOYER_PORTAL.value


def test_spanish_contact_process_and_postal_package_remain_source_grounded() -> None:
    source = (
        "Proceso de selección. Persona de contacto: María García — Responsable de selección. "
        "Envía tu CV y portfolio por correo electrónico a empleo@example.es. "
        "Dirección de solicitud: Calle Mayor 12, 28013 Madrid. "
        "Los documentos pueden tener como máximo 5 MB. Fecha límite: 15 octubre 2026."
    )

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.contact_name is not None
    assert guidance.contact_name.value == "María García"
    assert guidance.contact_role is not None
    assert guidance.contact_role.value == "Responsable de selección"
    assert guidance.contact_email is not None
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMAIL.value
    assert guidance.postal_address is not None
    assert guidance.postal_address.value == "Calle Mayor 12, 28013 Madrid"
    assert {item.value for item in guidance.requested_documents} == {"CV", "Portfolio"}
    assert guidance.max_file_size is not None
    assert guidance.application_deadline is not None
    assert any("Proceso de selección" in item.value for item in guidance.instructions)
    assert all(item.evidence_quote in source for item in guidance.entries())


def test_interactive_url_failure_recommends_manual_paste_without_archive_record(
    tmp_path: Path,
) -> None:
    repository = JobRepository(f"sqlite:///{(tmp_path / 'manual-fallback.db').as_posix()}")
    service = JobCorpusService(
        repository,
        fetcher=FailingFetcher(
            UrlIngestionError(
                "robots.txt does not permit fetching this URL",
                kind=UrlFailureKind.BLOCKED,
            )
        ),
        source_snapshot_directory=tmp_path / "snapshots",
        canonical_job_directory=tmp_path / "jobs",
    )

    result = service.import_url(URL, persist_failure=False)

    assert result.kind == JobObservationKind.UNREACHABLE
    assert result.record is None
    assert result.requested_url == URL
    assert result.manual_input_recommended is True
    assert repository.list_records() == []


def test_expired_url_is_not_presented_as_a_manual_paste_candidate(tmp_path: Path) -> None:
    repository = JobRepository(f"sqlite:///{(tmp_path / 'expired.db').as_posix()}")
    service = JobCorpusService(
        repository,
        fetcher=FailingFetcher(
            UrlIngestionError(
                "job page returned HTTP 404",
                kind=UrlFailureKind.EXPIRED,
                http_status=404,
            )
        ),
        source_snapshot_directory=tmp_path / "snapshots",
        canonical_job_directory=tmp_path / "jobs",
    )

    result = service.import_url(URL, persist_failure=False)

    assert result.kind == JobObservationKind.EXPIRED
    assert result.manual_input_recommended is False
    assert result.record is None


def test_saved_legacy_revision_gets_new_deterministic_guidance_without_llm(
    tmp_path: Path,
) -> None:
    repository = JobRepository(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    source = (
        "Example GmbH sucht eine Qualitätsingenieurin. Bitte senden Sie Lebenslauf und "
        "Zeugnisse per E-Mail an bewerbung@example.de. Die Unterlagen dürfen maximal "
        "6 MB groß sein."
    )
    job = JobPosting(
        title="Quality Engineer",
        company="Example GmbH",
        location="Berlin",
        summary="Quality engineering role.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="Manual input",
        source_text=source,
    )
    record = repository.store_manual_revision(
        "https://manual.betteroption.local/legacy-guidance",
        job,
        JobObservationKind.NEW,
    )

    restored = repository.get_current_job(record.id)

    assert restored is not None
    assert restored.application_guidance.contact_email is not None
    assert restored.application_guidance.contact_email.value == "bewerbung@example.de"
    assert {item.value for item in restored.application_guidance.requested_documents} == {
        "CV",
        "Certificates",
    }
    assert restored.application_guidance.max_file_size is not None
    assert restored.application_guidance.max_file_size.value == "6 MB"


def test_legacy_multi_address_guidance_keeps_job_detail_and_apply_available(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'legacy-web.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )
    workspace = container.workspaces.create(new_session())
    source = (
        "Test Automation Engineer. PostalAddress Deutschland Frankfurt am Main Hessen "
        "60322 Nicht vorhanden PostalAddress Deutschland Frankfurt am Main Hessen "
        "60311 Nicht vorhanden. Bewerben Sie sich über unser Karriereportal."
    )
    job = JobPosting(
        title="Test Automation Engineer",
        company="Example GmbH",
        location="Frankfurt am Main",
        summary="Automated testing role.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="Manual input",
        source_text=source,
    )
    record = container.repository.store_manual_revision(
        "https://manual.betteroption.local/legacy-multi-address",
        job,
        JobObservationKind.NEW,
    )
    run = MatchRun(
        profile_id=workspace.session.profile.id,
        results=[
            MatchResult(
                job_id=job.id,
                source_is_manual=True,
                score=80,
                hard_evidence_coverage=70,
                disposition=MatchDisposition.TOP,
                hard_violations=0,
            )
        ],
    )
    container.results.save_run(
        workspace.id,
        run,
        workspace.session.profile,
        {job.id: job},
        {job.id: record.id},
    )
    container.results.grant_initial_results(workspace.id, run.id, limit=25)
    container.application_drafts.save(
        workspace.id,
        record.id,
        "Dear Hiring Team,\n\nI am interested in this testing role.",
        generator_model=None,
        generated_action=None,
        manually_edited=True,
    )

    restored = container.repository.get_current_job(record.id)
    assert restored is not None
    assert JobPosting.model_validate(restored.model_dump(mode="python")) == restored

    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    detail = client.get(f"/jobs/{record.id}")
    apply_page = client.get("/apply")

    assert detail.status_code == 200
    assert "60322 Frankfurt am Main Hessen, Deutschland" in detail.text
    assert apply_page.status_code == 200
    assert "Test Automation Engineer" in apply_page.text
    assert "I am interested in this testing role." in apply_page.text
