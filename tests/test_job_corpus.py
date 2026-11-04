from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from betteroption.job_corpus import JobCorpusService
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.job_repository import (
    JobAvailability,
    JobObservationKind,
    JobRepository,
    normalize_job_url,
)
from betteroption.jobs import JobSourceType
from betteroption.url_ingestion import (
    FetchedDocument,
    UrlFailureKind,
    UrlIngestionError,
)


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
URL = "https://jobs.example.com/embedded/123"


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


class CountingExtractor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(self, source_text: str, **metadata):
        self.calls.append(source_text)
        version = "v2" if "version two" in source_text else "v1"
        extraction = JobExtraction(
            title=f"Embedded Engineer {version}",
            company="Acme",
            location="Frankfurt",
            summary="Embedded engineering role.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="Python",
                    kind="requirement",
                    evidence_quote="Python",
                )
            ],
        )
        return extraction.to_job_posting(source_text=source_text, **metadata)


def document(
    text: str = "Acme needs Python for an embedded engineering role version one.",
    *,
    requested_url: str = URL,
    final_url: str = URL,
    checked_at: datetime = NOW,
) -> FetchedDocument:
    return FetchedDocument(
        requested_url=requested_url,
        final_url=final_url,
        status_code=200,
        content_type="text/html",
        text=text,
        fetched_at=checked_at,
    )


@pytest.fixture
def repository(tmp_path: Path) -> JobRepository:
    database_path = (tmp_path / "corpus.db").as_posix()
    return JobRepository(f"sqlite:///{database_path}")


def service_for(
    tmp_path: Path,
    repository: JobRepository,
    fetcher: SequenceFetcher,
    extractor: CountingExtractor | None,
) -> JobCorpusService:
    return JobCorpusService(
        repository,
        fetcher=fetcher,
        extractor=extractor,
        source_snapshot_directory=tmp_path / "snapshots",
        canonical_job_directory=tmp_path / "jobs",
    )


def test_url_identity_removes_tracking_but_preserves_job_parameters() -> None:
    normalized = normalize_job_url(
        "HTTPS://Jobs.Example.com/role/123/?utm_source=newsletter&gh_jid=123&ref=mail"
    )

    assert normalized == "https://jobs.example.com/role/123?gh_jid=123"


def test_new_then_unchanged_reuses_extraction(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    extractor = CountingExtractor()
    fetcher = SequenceFetcher(document(), document(checked_at=NOW + timedelta(hours=1)))
    service = service_for(tmp_path, repository, fetcher, extractor)

    first = service.import_url(URL)
    second = service.import_url(URL)

    assert first.kind == JobObservationKind.NEW
    assert second.kind == JobObservationKind.UNCHANGED
    assert second.used_cached_extraction is True
    assert len(extractor.calls) == 1
    assert first.record is not None
    assert second.record is not None
    assert first.record.id == second.record.id
    assert second.record.revision_count == 1
    assert second.source_snapshot_path is not None
    assert second.source_snapshot_path.exists()
    assert second.job is not None
    assert second.job.url_checked_at == NOW + timedelta(hours=1)
    assert first.record is not None
    assert [item.kind for item in repository.list_observations(first.record.id)] == [
        JobObservationKind.NEW,
        JobObservationKind.UNCHANGED,
    ]
    assert len(repository.list_revisions(first.record.id)) == 1


def test_manual_text_is_saved_without_fetch_or_url_verification(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    extractor = CountingExtractor()
    fetcher = SequenceFetcher()
    service = service_for(tmp_path, repository, fetcher, extractor)
    source_text = (
        "Acme needs Python for an embedded engineering role version one. "
        "Applicants will design, test, and document reliable product software."
    )

    result = service.import_manual(source_text, source_url=URL)

    assert result.kind == JobObservationKind.NEW
    assert result.record is not None
    assert result.job is not None
    assert result.job.source_type == JobSourceType.MANUAL_TEXT
    assert str(result.job.source_url) == URL
    assert result.job.url_status is None
    assert result.job.url_http_status is None
    assert result.job.url_checked_at is None
    assert result.record.last_http_status is None
    assert fetcher.calls == []
    observations = repository.list_observations(result.record.id)
    assert observations[0].http_status is None
    assert "no network verification" in (observations[0].message or "").casefold()

    refreshed = service.refresh_all()
    guarded = service.import_url(URL)

    assert refreshed[0].used_cached_extraction is True
    assert guarded.used_cached_extraction is True
    assert guarded.job is not None
    assert guarded.job.source_type == JobSourceType.MANUAL_TEXT
    assert fetcher.calls == []


def test_changed_content_creates_a_revision_and_calls_extractor(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    extractor = CountingExtractor()
    changed_text = "Acme needs Python for an embedded engineering role version two."
    fetcher = SequenceFetcher(document(), document(changed_text))
    service = service_for(tmp_path, repository, fetcher, extractor)

    first = service.import_url(URL)
    changed = service.import_url(URL)

    assert first.kind == JobObservationKind.NEW
    assert changed.kind == JobObservationKind.CHANGED
    assert changed.job is not None
    assert changed.job.title.endswith("v2")
    assert changed.record is not None
    assert changed.record.revision_count == 2
    assert len(extractor.calls) == 2


def test_unchanged_cache_survives_repository_restart_without_an_api_key(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"
    extractor = CountingExtractor()
    first_service = service_for(
        tmp_path,
        JobRepository(database_url),
        SequenceFetcher(document()),
        extractor,
    )
    first_service.import_url(URL)

    restarted_service = service_for(
        tmp_path,
        JobRepository(database_url),
        SequenceFetcher(document(checked_at=NOW + timedelta(hours=2))),
        None,
    )
    result = restarted_service.import_url(URL)

    assert result.kind == JobObservationKind.UNCHANGED
    assert result.used_cached_extraction is True
    assert result.job is not None
    assert result.job.title == "Embedded Engineer v1"
    assert len(extractor.calls) == 1


def test_expired_job_is_retained_but_excluded_from_live_results(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    extractor = CountingExtractor()
    expired = UrlIngestionError(
        "job page returned HTTP 410",
        kind=UrlFailureKind.EXPIRED,
        http_status=410,
    )
    service = service_for(
        tmp_path,
        repository,
        SequenceFetcher(document(), expired),
        extractor,
    )

    first = service.import_url(URL)
    result = service.import_url(URL)

    assert first.job is not None
    assert result.kind == JobObservationKind.EXPIRED
    assert result.record is not None
    assert result.record.availability == JobAvailability.EXPIRED
    assert result.record.revision_count == 1
    assert repository.list_live_jobs() == []
    assert repository.get_current_job(result.record.id) is not None


def test_previously_unreachable_url_can_recover_to_a_live_first_revision(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    unavailable = UrlIngestionError(
        "temporary network failure",
        kind=UrlFailureKind.UNREACHABLE,
    )
    extractor = CountingExtractor()
    service = service_for(
        tmp_path,
        repository,
        SequenceFetcher(unavailable, document()),
        extractor,
    )

    failed = service.import_url(URL)
    recovered = service.import_url(URL)

    assert failed.record is not None
    assert failed.record.availability == JobAvailability.UNREACHABLE
    assert recovered.record is not None
    assert recovered.record.id == failed.record.id
    assert recovered.kind == JobObservationKind.NEW
    assert recovered.record.availability == JobAvailability.LIVE
    assert recovered.record.revision_count == 1


def test_redirect_and_tracking_aliases_resolve_to_one_record(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    requested = f"{URL}?utm_source=mail"
    final = "https://careers.example.com/jobs/123"
    extractor = CountingExtractor()
    service = service_for(
        tmp_path,
        repository,
        SequenceFetcher(
            document(requested_url=requested, final_url=final),
            document(requested_url=final, final_url=final),
        ),
        extractor,
    )

    first = service.import_url(requested)
    second = service.import_url(final)

    assert first.record is not None
    assert second.record is not None
    assert first.record.id == second.record.id
    assert second.kind == JobObservationKind.UNCHANGED
    assert len(repository.list_records()) == 1
    assert len(extractor.calls) == 1


def test_stale_live_job_is_revalidated_before_presentation(
    tmp_path: Path,
    repository: JobRepository,
) -> None:
    extractor = CountingExtractor()
    service = service_for(
        tmp_path,
        repository,
        SequenceFetcher(document(), document(checked_at=NOW + timedelta(days=2))),
        extractor,
    )
    service.import_url(URL)

    jobs = service.jobs_ready_for_presentation(maximum_age=timedelta(0))

    assert len(jobs) == 1
    assert len(extractor.calls) == 1
    assert repository.list_records()[0].last_observation_kind == JobObservationKind.UNCHANGED


def test_generic_experience_is_not_counted_as_a_skill() -> None:
    source = "Software development experience, for example in a Linux environment, is required."
    extraction = JobExtraction(
        title="Software Engineer",
        company="Acme",
        location="Frankfurt",
        summary="Software engineering role.",
        facts=[
            JobFactDraft(
                key="skill.name",
                value="Software development experience, for example in a Linux environment",
                kind="requirement",
                evidence_quote=source.removesuffix(" is required."),
            )
        ],
    )

    job = extraction.to_job_posting(
        source_text=source,
        source_name=URL,
        source_url=URL,
        requested_url=URL,
        url_http_status=200,
        url_checked_at=NOW,
    )

    assert job.facts[0].key == "candidate.experience"
