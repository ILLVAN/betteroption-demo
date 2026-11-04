from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import UUID

from betteroption.accounts import AccountRepository, RegistrationMode
from betteroption.database import Database
from betteroption.job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    JobEvidenceOverrideRepository,
)
from betteroption.job_repository import JobObservationKind, JobRepository
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import MatchResult, match_job
from betteroption.personas import PersonaRepository
from betteroption.posting_date import (
    PostingDateConfidence,
    PostingDateSource,
    PostingFreshness,
    classify_posting_date,
    extract_posting_date,
)
from betteroption.profile import CandidateProfile
from betteroption.profile_repository import ProfileWorkspaceRepository
from betteroption.url_ingestion import FetchedDocument


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
JOB_URL = "https://careers.example.com/jobs/posting-date"


def _job(source_text: str) -> JobPosting:
    return JobPosting(
        title="Product Designer",
        company="Example Products",
        location="Berlin",
        summary="Design accessible products.",
        source_type=JobSourceType.URL_TEXT,
        source_name=JOB_URL,
        source_url=JOB_URL,
        requested_url=JOB_URL,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source_text,
        observed_at=NOW,
    )


def _store_job(repository: JobRepository, job: JobPosting) -> UUID:
    document = FetchedDocument(
        requested_url=JOB_URL,
        final_url=JOB_URL,
        status_code=200,
        content_type="text/html",
        text=job.source_text,
        fetched_at=NOW,
    )
    return repository.store_revision(document, job, JobObservationKind.NEW).id


def test_job_posting_extracts_and_serializes_attributable_structured_date() -> None:
    job = _job(
        "Product Designer\nDate posted: 2026-07-20T10:00:00Z\nApplication deadline: 31.08.2026"
    )

    assert job.posting_date == date(2026, 7, 20)
    assert job.posting_date_source == PostingDateSource.STRUCTURED
    assert job.posting_date_evidence_quote == "Date posted: 2026-07-20T10:00:00Z"
    restored = JobPosting.model_validate_json(job.model_dump_json())
    assert restored.posting_date == job.posting_date
    assert restored.posting_date_evidence_quote == job.posting_date_evidence_quote


def test_unattributed_provider_date_is_discarded_instead_of_trusted() -> None:
    job = _job("Product Designer with no publication date in the advertisement.").model_copy(
        update={
            "posting_date": date(2026, 7, 31),
            "posting_date_source": PostingDateSource.STRUCTURED,
            "posting_date_confidence": PostingDateConfidence.HIGH,
            "posting_date_evidence_quote": "Date posted: 2026-07-31",
        }
    )

    revalidated = JobPosting.model_validate(job.model_dump())

    assert revalidated.posting_date is None
    assert revalidated.posting_date_source is None
    assert revalidated.posting_date_confidence is None
    assert revalidated.posting_date_evidence_quote is None


def test_extractor_accepts_common_european_dates_but_not_unlabelled_or_deadline_dates() -> None:
    observed_at = NOW
    cases = {
        "Veröffentlicht am: 20.07.2026": date(2026, 7, 20),
        "Posted 12 May 2026": date(2026, 5, 12),
        "Publication date — May 12, 2026": date(2026, 5, 12),
        "Eingestellt am 12/05/2026": date(2026, 5, 12),
        "Publiziert am: 12-05-2026": date(2026, 5, 12),
    }
    for source_text, expected in cases.items():
        extracted = extract_posting_date(source_text, observed_at=observed_at)
        assert extracted is not None
        assert extracted.value == expected

    structured_json = extract_posting_date(
        '{"@type":"JobPosting","datePosted":"2026-07-21T09:00:00+02:00"}',
        observed_at=observed_at,
    )
    assert structured_json is not None
    assert structured_json.value == date(2026, 7, 21)
    assert structured_json.source == PostingDateSource.STRUCTURED

    assert extract_posting_date("Application deadline: 20.07.2026", observed_at=observed_at) is None
    assert (
        extract_posting_date("Our company was founded on 20.07.2026", observed_at=observed_at)
        is None
    )
    assert extract_posting_date("Posted 2 days ago", observed_at=observed_at).value == date(
        2026, 7, 30
    )
    assert extract_posting_date("Eingestellt vor 2 Wochen", observed_at=observed_at).value == date(
        2026, 7, 18
    )


def test_extractor_accepts_labeled_french_dutch_spanish_and_italian_dates() -> None:
    explicit_cases = {
        "Date de publication : 12 juillet 2026": date(2026, 7, 12),
        "Publié le 3 févr. 2026": date(2026, 2, 3),
        "Publicatiedatum: 11 augustus 2026": date(2026, 8, 11),
        "Fecha de publicación: 10 septiembre 2026": date(2026, 9, 10),
        "Pubblicato il 9 ottobre 2026": date(2026, 10, 9),
    }
    relative_cases = {
        "Publié il y a 2 jours": date(2026, 7, 30),
        "Geplaatst 2 weken geleden": date(2026, 7, 18),
        "Publicado hace 3 días": date(2026, 7, 29),
        "Pubblicato una settimana fa": date(2026, 7, 25),
    }

    for source_text, expected in {**explicit_cases, **relative_cases}.items():
        extracted = extract_posting_date(source_text, observed_at=NOW)
        assert extracted is not None
        assert extracted.value == expected

    for badge, expected in {
        "il y a 2 jours": date(2026, 7, 30),
        "2 weken geleden": date(2026, 7, 18),
        "hace 3 días": date(2026, 7, 29),
        "una settimana fa": date(2026, 7, 25),
    }.items():
        extracted = extract_posting_date(f"\n{badge}\n", observed_at=NOW)
        assert extracted is not None
        assert extracted.value == expected

    assert extract_posting_date("Fecha límite: 10 septiembre 2026", observed_at=NOW) is None
    assert extract_posting_date("Date limite : 12 juillet 2026", observed_at=NOW) is None
    assert (
        extract_posting_date(
            "Notre produit a été lancé il y a 2 jours.",
            observed_at=NOW,
        )
        is None
    )


def test_typed_extracted_fact_must_agree_with_its_verbatim_date_quote() -> None:
    job = JobPosting(
        title="Product Designer",
        company="Example Products",
        location="Berlin",
        summary="Design accessible products.",
        source_type=JobSourceType.SAMPLE,
        source_name="posting-date-fact-test",
        source_text="Published on 5 June 2026.",
        observed_at=NOW,
        facts=[
            JobFact(
                key="posting.date",
                value="5 June 2026",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Published on 5 June 2026",
            )
        ],
    )
    assert job.posting_date == date(2026, 6, 5)
    assert job.posting_date_source == PostingDateSource.EXTRACTED_FACT

    contradictory = JobPosting(
        title=job.title,
        company=job.company,
        location=job.location,
        summary=job.summary,
        source_type=JobSourceType.SAMPLE,
        source_name=job.source_name,
        source_text="Published on 5 June 2026. Date posted: 2026-07-01.",
        observed_at=NOW,
        facts=[job.facts[0].model_copy(update={"value": "1 June 2026"})],
    )
    assert contradictory.posting_date == date(2026, 7, 1)
    assert contradictory.posting_date_source == PostingDateSource.STRUCTURED


def test_freshness_uses_inclusive_calendar_month_boundaries() -> None:
    evaluated_on = date(2026, 8, 1)
    assert classify_posting_date(date(2026, 7, 2), evaluated_on=evaluated_on) == "fresh"
    assert classify_posting_date(date(2026, 7, 1), evaluated_on=evaluated_on) == "medium"
    assert classify_posting_date(date(2026, 4, 1), evaluated_on=evaluated_on) == "medium"
    assert classify_posting_date(date(2026, 3, 31), evaluated_on=evaluated_on) == "old"
    assert classify_posting_date(date(2026, 8, 2), evaluated_on=evaluated_on) == "unknown"
    assert classify_posting_date(None, evaluated_on=evaluated_on) == "unknown"


def test_posting_age_is_bounded_context_and_persisted_in_match_result() -> None:
    profile = CandidateProfile()
    fresh = match_job(profile, _job("Date posted: 2026-07-20"), evaluated_at=NOW)
    unknown = match_job(profile, _job("No publication date supplied."), evaluated_at=NOW)
    old = match_job(profile, _job("Date posted: 2025-12-15"), evaluated_at=NOW)

    assert fresh.score == unknown.score + 2
    assert old.score == unknown.score - 4
    assert fresh.hard_violations == old.hard_violations == 0
    assert fresh.posting_date is not None
    assert fresh.posting_date.freshness == PostingFreshness.FRESH
    assert fresh.posting_date.evaluated_on == NOW.date()
    assert fresh.posting_date.score_adjustment == 2
    restored = MatchResult.model_validate_json(fresh.model_dump_json())
    assert restored.posting_date == fresh.posting_date


def test_persona_posting_date_override_persists_across_workspaces_and_restores(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'posting-date.db').as_posix()}")
    accounts = AccountRepository(database)
    personas = PersonaRepository(database)
    workspaces = ProfileWorkspaceRepository(database)
    jobs = JobRepository(database)
    overrides = JobEvidenceOverrideRepository(database)
    account = accounts.create(
        "posting-date@example.com",
        "Date Owner",
        "correct horse battery staple",
        registration_mode=RegistrationMode.OPEN,
    )
    persona = personas.create(account.id, "Main", maximum_personas=5)
    first_workspace = workspaces.create(account_id=account.id, persona_id=persona.id)
    job = _job("Date posted: 2026-07-20")
    record_id = _store_job(jobs, job)

    overrides.upsert(
        JobEvidenceOverride(
            workspace_id=first_workspace.id,
            job_record_id=record_id,
            kind=JobEvidenceOverrideKind.POSTING_DATE,
            target_key="posting_date",
            target_label="Posting date",
            posting_date=date(2026, 2, 1),
        )
    )
    replacement_workspace = workspaces.create(account_id=account.id, persona_id=persona.id)
    inherited = overrides.list_for_job(replacement_workspace.id, record_id)

    assert len(inherited) == 1
    assert inherited[0].posting_date == date(2026, 2, 1)
    exported = json.loads(accounts.export_json(account.id))
    assert exported["job_evidence_overrides"][0]["posting_date"] == "2026-02-01"
    corrected = match_job(CandidateProfile(), job, job_overrides=inherited, evaluated_at=NOW)
    assert corrected.posting_date is not None
    assert corrected.posting_date.automatic_date == date(2026, 7, 20)
    assert corrected.posting_date.effective_date == date(2026, 2, 1)
    assert corrected.posting_date.automatic_freshness == PostingFreshness.FRESH
    assert corrected.posting_date.freshness == PostingFreshness.OLD
    assert corrected.posting_date.user_overridden

    assert overrides.delete(
        replacement_workspace.id,
        record_id,
        JobEvidenceOverrideKind.POSTING_DATE,
        "posting_date",
    )
    restored = match_job(
        CandidateProfile(),
        job,
        job_overrides=overrides.list_for_job(first_workspace.id, record_id),
        evaluated_at=NOW,
    )
    assert restored.posting_date is not None
    assert restored.posting_date.effective_date == date(2026, 7, 20)
    assert restored.posting_date.freshness == PostingFreshness.FRESH
    assert not restored.posting_date.user_overridden
