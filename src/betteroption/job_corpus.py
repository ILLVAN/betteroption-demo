"""Application service for cached, revisioned URL job ingestion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from .background import BackgroundTaskCommitRejected
from .concurrency import CooperativeControlFlow
from .job_repository import (
    JobAvailability,
    JobObservationKind,
    JobRecord,
    JobRepository,
    normalize_job_url,
)
from .jobs import JobPosting, JobSourceType, normalize_placeholder_employer, save_job
from .llm import JobExtractorPort
from .profile import StrictModel
from .url_ingestion import (
    FetchedDocument,
    PublicUrlFetcher,
    UrlFailureKind,
    UrlIngestionError,
    save_fetched_document,
)


class JobCorpusError(RuntimeError):
    """Raised when corpus processing cannot safely complete."""


class JobImportResult(StrictModel):
    kind: JobObservationKind
    record: JobRecord | None = None
    job: JobPosting | None = None
    used_cached_extraction: bool = False
    source_snapshot_path: Path | None = None
    message: str | None = None
    requested_url: str | None = None
    manual_input_recommended: bool = False


class JobCorpusService:
    def __init__(
        self,
        repository: JobRepository,
        *,
        fetcher: PublicUrlFetcher | None = None,
        extractor: JobExtractorPort | None = None,
        extractor_factory: Callable[[], JobExtractorPort] | None = None,
        source_snapshot_directory: Path = Path("local-data") / "source-snapshots",
        canonical_job_directory: Path = Path("local-data") / "jobs",
    ) -> None:
        self.repository = repository
        self.fetcher = fetcher
        self.extractor = extractor
        self.extractor_factory = extractor_factory
        self.source_snapshot_directory = source_snapshot_directory
        self.canonical_job_directory = canonical_job_directory

    def _extract(self, document: FetchedDocument) -> JobPosting:
        if self.extractor is None and self.extractor_factory is not None:
            try:
                self.extractor = self.extractor_factory()
            except Exception as exc:
                raise JobCorpusError(
                    "Job extraction could not start. Check the configured provider and API key."
                ) from exc
        if self.extractor is None:
            raise JobCorpusError(
                "The URL changed and requires extraction, but no LLM extractor is configured."
            )
        return self.extractor.extract(
            document.text,
            source_name=document.final_url,
            source_url=document.final_url,
            requested_url=document.requested_url,
            url_http_status=document.status_code,
            url_checked_at=document.fetched_at,
        )

    def _fetch(self, url: str) -> FetchedDocument:
        if self.fetcher is None:
            self.fetcher = PublicUrlFetcher()
        return self.fetcher.fetch(url)

    def import_url(
        self,
        url: str,
        *,
        replace_manual: bool = False,
        persist_failure: bool = True,
        check_control: Callable[[], None] | None = None,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> JobImportResult:
        """Fetch and import one URL.

        ``persist_failure=False`` is intended for the interactive Add flow: a
        blocked, unsupported or unextractable page can then hand the original
        URL and all still-local form settings back to a manual-paste step
        without creating a misleading Needs-Recheck archive record. Scheduled
        corpus refreshes retain the default failure history.
        """

        supplied_fence = (
            commit_task_id is not None,
            expected_task_attempt is not None,
            task_claim_token is not None,
        )
        if any(supplied_fence) and not all(supplied_fence):
            raise ValueError("task id, attempt, and claim token must be supplied together")

        def checkpoint() -> None:
            if check_control is not None:
                check_control()

        checkpoint()
        requested_url = url.strip()
        known_record = self.repository.find_by_urls(url)
        if known_record is not None and not replace_manual:
            known_job = self.repository.get_current_job(known_record.id)
            if known_job is not None and known_job.source_type == JobSourceType.MANUAL_TEXT:
                return JobImportResult(
                    kind=JobObservationKind.UNCHANGED,
                    record=known_record,
                    job=known_job,
                    used_cached_extraction=True,
                    message="Manual input was kept unchanged; no URL was requested.",
                    requested_url=requested_url,
                )
        try:
            document = self._fetch(url)
        except UrlIngestionError as exc:
            checkpoint()
            record = None
            if persist_failure:
                try:
                    record = self.repository.record_failure(
                        url,
                        exc.kind,
                        str(exc),
                        http_status=exc.http_status,
                        commit_task_id=commit_task_id,
                        expected_task_attempt=expected_task_attempt,
                        task_claim_token=task_claim_token,
                    )
                except ValueError:
                    record = None
            kind = (
                JobObservationKind.EXPIRED
                if exc.kind == UrlFailureKind.EXPIRED
                else JobObservationKind.UNREACHABLE
            )
            return JobImportResult(
                kind=kind,
                record=record,
                message=str(exc),
                requested_url=requested_url,
                manual_input_recommended=exc.kind
                in {
                    UrlFailureKind.BLOCKED,
                    UrlFailureKind.UNREACHABLE,
                    UrlFailureKind.UNSUPPORTED,
                },
            )

        checkpoint()
        snapshot_identity = sha256(
            f"{document.final_url}\0{document.text}".encode("utf-8")
        ).hexdigest()[:20]
        expected_snapshot_path = (
            self.source_snapshot_directory / f"source-snapshot-{snapshot_identity}.json"
        )
        snapshot_existed = expected_snapshot_path.exists()
        snapshot_path = save_fetched_document(
            document,
            self.source_snapshot_directory,
        )

        def discard_new_snapshot() -> None:
            if not snapshot_existed:
                snapshot_path.unlink(missing_ok=True)

        def checkpoint_after_snapshot() -> None:
            try:
                checkpoint()
            except CooperativeControlFlow:
                discard_new_snapshot()
                raise

        def commit(operation: Callable[[], JobRecord]) -> JobRecord:
            try:
                return operation()
            except BackgroundTaskCommitRejected:
                discard_new_snapshot()
                raise

        checkpoint_after_snapshot()
        source_hash = sha256(document.text.encode("utf-8")).hexdigest()
        existing = self.repository.find_by_urls(document.requested_url, document.final_url)
        if (
            existing is not None
            and existing.current_revision_id is not None
            and existing.current_content_hash == source_hash
        ):
            record = commit(
                lambda: self.repository.record_unchanged(
                    document,
                    commit_task_id=commit_task_id,
                    expected_task_attempt=expected_task_attempt,
                    task_claim_token=task_claim_token,
                )
            )
            job = self.repository.get_current_job(record.id)
            if job is None:
                raise JobCorpusError("cached corpus record has no current job revision")
            return JobImportResult(
                kind=JobObservationKind.UNCHANGED,
                record=record,
                job=job,
                used_cached_extraction=True,
                source_snapshot_path=snapshot_path,
                message="Content is unchanged; reused the existing canonical extraction.",
                requested_url=requested_url,
            )

        try:
            job = self._extract(document)
        except (RuntimeError, ValueError) as exc:
            checkpoint_after_snapshot()
            failure_message = str(exc)
            record = (
                commit(
                    lambda: self.repository.record_extraction_failure(
                        document,
                        failure_message,
                        commit_task_id=commit_task_id,
                        expected_task_attempt=expected_task_attempt,
                        task_claim_token=task_claim_token,
                    )
                )
                if persist_failure
                else None
            )
            return JobImportResult(
                kind=JobObservationKind.EXTRACTION_FAILED,
                record=record,
                source_snapshot_path=snapshot_path,
                message=failure_message,
                requested_url=requested_url,
                manual_input_recommended=True,
            )
        checkpoint_after_snapshot()
        job = normalize_placeholder_employer(job)
        kind = (
            JobObservationKind.NEW
            if existing is None or existing.current_revision_id is None
            else JobObservationKind.CHANGED
        )
        record = commit(
            lambda: self.repository.store_revision(
                document,
                job,
                kind,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
        )
        save_job(job, self.canonical_job_directory)
        return JobImportResult(
            kind=kind,
            record=record,
            job=job,
            source_snapshot_path=snapshot_path,
            requested_url=requested_url,
            message=(
                "Created the first canonical job revision."
                if kind == JobObservationKind.NEW
                else "Advertisement content changed; created a new revision."
            ),
        )

    def import_manual(self, source_text: str, *, source_url: str | None = None) -> JobImportResult:
        """Extract a user-pasted advertisement without fetching or verifying a URL."""

        text = source_text.strip()
        if len(text) < 80:
            raise JobCorpusError(
                "Paste at least 80 characters of the advertisement so the role can be extracted."
            )
        if len(text) > 150_000:
            raise JobCorpusError("Manual job text must not exceed 150,000 characters.")

        normalized_source_url = normalize_job_url(source_url) if source_url else None
        content_hash = sha256(text.encode("utf-8")).hexdigest()
        identity_url = normalized_source_url or (
            f"https://manual.betteroption.local/{content_hash}"
        )
        observed_at = datetime.now(timezone.utc)
        existing = self.repository.find_by_urls(identity_url)
        if (
            existing is not None
            and existing.current_revision_id is not None
            and existing.current_content_hash == content_hash
        ):
            job = self.repository.get_current_job(existing.id)
            if job is None:
                raise JobCorpusError("cached manual corpus record has no current job revision")
            return JobImportResult(
                kind=JobObservationKind.UNCHANGED,
                record=existing,
                job=job,
                used_cached_extraction=True,
                requested_url=normalized_source_url,
                message="Manual text is unchanged; reused the existing extraction.",
            )

        document = FetchedDocument(
            requested_url=identity_url,
            final_url=identity_url,
            status_code=200,
            content_type="text/plain; charset=utf-8",
            text=text,
            fetched_at=observed_at,
        )
        try:
            extracted = self._extract(document)
        except (RuntimeError, ValueError) as exc:
            raise JobCorpusError(str(exc)) from exc

        payload = extracted.model_dump(mode="python")
        guidance = payload.get("application_guidance", {})
        for value in guidance.values():
            if isinstance(value, dict):
                value["source_url"] = normalized_source_url
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, dict):
                        item["source_url"] = normalized_source_url
        payload.update(
            {
                "source_type": JobSourceType.MANUAL_TEXT,
                "source_name": normalized_source_url or "Manual input",
                "source_url": normalized_source_url,
                "requested_url": normalized_source_url,
                "url_status": None,
                "url_http_status": None,
                "url_checked_at": None,
                "application_guidance": guidance,
            }
        )
        job = normalize_placeholder_employer(JobPosting.model_validate(payload))
        kind = (
            JobObservationKind.NEW
            if existing is None or existing.current_revision_id is None
            else JobObservationKind.CHANGED
        )
        record = self.repository.store_manual_revision(identity_url, job, kind)
        save_job(job, self.canonical_job_directory)
        return JobImportResult(
            kind=kind,
            record=record,
            job=job,
            requested_url=normalized_source_url,
            message=(
                "Manual job text saved locally without checking the source link."
                if kind == JobObservationKind.NEW
                else "Manual job text changed; a new local revision was saved."
            ),
        )

    def jobs_ready_for_presentation(
        self,
        *,
        maximum_age: timedelta = timedelta(hours=24),
    ) -> list[JobPosting]:
        """Return live jobs, refreshing stale live links before presentation."""

        cutoff = datetime.now(timezone.utc) - maximum_age
        jobs: list[JobPosting] = []
        for record in self.repository.list_records():
            if record.availability != JobAvailability.LIVE:
                continue
            job = self.repository.get_current_job(record.id)
            if job is not None and job.source_type == JobSourceType.MANUAL_TEXT:
                jobs.append(job)
                continue
            if record.last_checked_at < cutoff:
                result = self.import_url(record.canonical_url)
                if result.job is not None and result.record is not None:
                    if result.record.availability == JobAvailability.LIVE:
                        jobs.append(result.job)
                continue
            if job is not None:
                jobs.append(job)
        return _deduplicate_jobs(jobs)

    def refresh_all(self) -> list[JobImportResult]:
        """Recheck every known URL, including previously unavailable records."""

        results: list[JobImportResult] = []
        for record in self.repository.list_records():
            job = self.repository.get_current_job(record.id)
            if job is not None and job.source_type == JobSourceType.MANUAL_TEXT:
                results.append(
                    JobImportResult(
                        kind=JobObservationKind.UNCHANGED,
                        record=record,
                        job=job,
                        used_cached_extraction=True,
                        message="Manual input was kept unchanged; no URL was requested.",
                    )
                )
                continue
            results.append(self.import_url(record.canonical_url))
        return results

    def delete_record(
        self,
        record_id: UUID,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> bool:
        """Delete one corpus record and its reproducibility files after database success."""

        record = next(
            (item for item in self.repository.list_records() if item.id == record_id),
            None,
        )
        if record is None:
            return False
        revisions = self.repository.list_revisions(record_id)
        known_urls = {normalize_job_url(record.canonical_url)}
        current_job = self.repository.get_current_job(record_id)
        if current_job is not None:
            known_urls.update(
                normalize_job_url(str(url))
                for url in (current_job.requested_url, current_job.source_url)
                if url is not None
            )
        deleted = self.repository.delete_record(
            record_id,
            commit_task_id=commit_task_id,
            expected_task_attempt=expected_task_attempt,
            task_claim_token=task_claim_token,
        )
        if not deleted:
            return False
        for revision in revisions:
            (self.canonical_job_directory / f"job-{revision.posting_id}.json").unlink(
                missing_ok=True
            )
        self._delete_source_snapshots(known_urls)
        return True

    def _delete_source_snapshots(self, known_urls: set[str]) -> None:
        if not self.source_snapshot_directory.exists():
            return
        for path in self.source_snapshot_directory.glob("source-snapshot-*.json"):
            try:
                document = FetchedDocument.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            document_urls = {
                normalize_job_url(document.requested_url),
                normalize_job_url(document.final_url),
            }
            if document_urls.intersection(known_urls):
                path.unlink(missing_ok=True)


def _deduplicate_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    unique: dict[str, JobPosting] = {}
    for job in jobs:
        job = normalize_placeholder_employer(job)
        unique.setdefault(job.content_hash, job)
    return list(unique.values())
