"""Persistent job corpus with URL identity, revisions, and observations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func, select

from .application_guidance import extract_application_guidance, merge_application_guidance
from .background import fence_background_task_commit
from .database import Base, Database
from .jobs import JobPosting, normalize_placeholder_employer
from .profile import StrictModel
from .url_ingestion import FetchedDocument, UrlFailureKind


TRACKING_QUERY_PARAMETERS = {
    "campaign",
    "ref",
    "referrer",
    "source",
    "trackingid",
    "trk",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_job_url(url: str) -> str:
    """Normalize URL identity without removing job-specific query parameters."""

    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("job URL must use http or https and contain a host")
    if parsed.username or parsed.password:
        raise ValueError("job URL must not contain credentials")

    host = parsed.hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (scheme == "http" and parsed.port == 80) or (
        scheme == "https" and parsed.port == 443
    )
    netloc = host if parsed.port is None or default_port else f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_PARAMETERS
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


class JobAvailability(StrEnum):
    LIVE = "live"
    EXPIRED = "expired"
    UNREACHABLE = "unreachable"
    NEEDS_ATTENTION = "needs_attention"


class JobObservationKind(StrEnum):
    NEW = "new"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    EXPIRED = "expired"
    UNREACHABLE = "unreachable"
    EXTRACTION_FAILED = "extraction_failed"


class JobRecordRow(Base):
    __tablename__ = "job_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    last_observation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobUrlAliasRow(Base):
    __tablename__ = "job_url_aliases"

    normalized_url: Mapped[str] = mapped_column(Text, primary_key=True)
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class JobRevisionRow(Base):
    __tablename__ = "job_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    posting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    posting_json: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobObservationRow(Base):
    __tablename__ = "job_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobRecord(StrictModel):
    id: UUID
    canonical_url: str
    availability: JobAvailability
    last_observation_kind: JobObservationKind
    current_revision_id: UUID | None = None
    current_content_hash: str | None = None
    revision_count: int
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_checked_at: datetime
    last_http_status: int | None = None
    unavailable_reason: str | None = None


class JobRevision(StrictModel):
    id: UUID
    job_record_id: UUID
    posting_id: UUID
    content_hash: str
    observed_at: datetime
    created_at: datetime


class JobObservation(StrictModel):
    id: UUID
    job_record_id: UUID
    kind: JobObservationKind
    requested_url: str
    resolved_url: str | None = None
    checked_at: datetime
    http_status: int | None = None
    content_hash: str | None = None
    message: str | None = None


class JobRepository:
    """SQLAlchemy repository; SQLite locally and PostgreSQL-compatible by design."""

    def __init__(
        self,
        database_url: str | Database | None = None,
        *,
        database: Database | None = None,
    ) -> None:
        if isinstance(database_url, Database):
            if database is not None:
                raise ValueError("Pass a Database either positionally or by keyword, not both.")
            database = database_url
            database_url = None
        self.database = database or Database(database_url)
        self.database_url = self.database.url
        self.engine = self.database.engine
        self.session_factory = self.database.session_factory

    def _find_row(self, session: Session, *urls: str) -> JobRecordRow | None:
        normalized_urls = {normalize_job_url(url) for url in urls if url}
        if not normalized_urls:
            return None
        alias = session.scalar(
            select(JobUrlAliasRow).where(JobUrlAliasRow.normalized_url.in_(normalized_urls))
        )
        if alias is not None:
            return session.get(JobRecordRow, alias.job_record_id)
        return session.scalar(
            select(JobRecordRow).where(JobRecordRow.canonical_url.in_(normalized_urls))
        )

    @staticmethod
    def _fence_background_commit(
        session: Session,
        *,
        commit_task_id: UUID | None,
        expected_task_attempt: int | None,
        task_claim_token: UUID | None,
    ) -> None:
        supplied = (
            commit_task_id is not None,
            expected_task_attempt is not None,
            task_claim_token is not None,
        )
        if any(supplied) and not all(supplied):
            raise ValueError("task id, attempt, and claim token must be supplied together")
        if all(supplied):
            fence_background_task_commit(
                session,
                commit_task_id,
                expected_attempt=expected_task_attempt,
                claim_token=task_claim_token,
            )

    def _ensure_alias(self, session: Session, row: JobRecordRow, url: str) -> None:
        normalized = normalize_job_url(url)
        alias = session.get(JobUrlAliasRow, normalized)
        if alias is None:
            session.add(JobUrlAliasRow(normalized_url=normalized, job_record_id=row.id))
        elif alias.job_record_id != row.id:
            raise ValueError("job URL alias already belongs to another corpus record")

    def _to_record(self, session: Session, row: JobRecordRow) -> JobRecord:
        revision_count = session.scalar(
            select(func.count(JobRevisionRow.id)).where(JobRevisionRow.job_record_id == row.id)
        )
        return JobRecord(
            id=UUID(row.id),
            canonical_url=row.canonical_url,
            availability=JobAvailability(row.availability),
            last_observation_kind=JobObservationKind(row.last_observation_kind),
            current_revision_id=(
                UUID(row.current_revision_id) if row.current_revision_id else None
            ),
            current_content_hash=row.current_content_hash,
            revision_count=int(revision_count or 0),
            first_seen_at=ensure_utc(row.first_seen_at),
            last_seen_at=ensure_utc(row.last_seen_at),
            last_checked_at=ensure_utc(row.last_checked_at),
            last_http_status=row.last_http_status,
            unavailable_reason=row.unavailable_reason,
        )

    def find_by_urls(self, *urls: str) -> JobRecord | None:
        with self.session_factory() as session:
            row = self._find_row(session, *urls)
            return self._to_record(session, row) if row is not None else None

    def find_current_by_posting_id(self, posting_id: UUID) -> JobRecord | None:
        """Resolve a posting only when it is the record's current revision.

        Manual pasted jobs may intentionally have no public source URL.  Their
        stable posting UUID therefore provides the authoritative association,
        without rescanning and reloading the entire corpus for every Match run.
        """

        with self.session_factory() as session:
            row = session.scalar(
                select(JobRecordRow)
                .join(
                    JobRevisionRow,
                    JobRevisionRow.id == JobRecordRow.current_revision_id,
                )
                .where(JobRevisionRow.posting_id == str(posting_id))
            )
            return self._to_record(session, row) if row is not None else None

    def list_records(self) -> list[JobRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(JobRecordRow).order_by(JobRecordRow.updated_at.desc())
            ).all()
            return [self._to_record(session, row) for row in rows]

    def count_records(self) -> int:
        with self.session_factory() as session:
            return int(session.scalar(select(func.count(JobRecordRow.id))) or 0)

    def delete_record(
        self,
        record_id: UUID,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> bool:
        """Delete one explicitly selected job and its database-backed history."""

        with self.session_factory.begin() as session:
            self._fence_background_commit(
                session,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
            row = session.get(JobRecordRow, str(record_id))
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

    def list_revisions(self, record_id: UUID) -> list[JobRevision]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(JobRevisionRow)
                .where(JobRevisionRow.job_record_id == str(record_id))
                .order_by(JobRevisionRow.created_at.asc())
            ).all()
            return [
                JobRevision(
                    id=UUID(row.id),
                    job_record_id=UUID(row.job_record_id),
                    posting_id=UUID(row.posting_id),
                    content_hash=row.content_hash,
                    observed_at=ensure_utc(row.observed_at),
                    created_at=ensure_utc(row.created_at),
                )
                for row in rows
            ]

    def list_observations(self, record_id: UUID) -> list[JobObservation]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(JobObservationRow)
                .where(JobObservationRow.job_record_id == str(record_id))
                .order_by(JobObservationRow.checked_at.asc())
            ).all()
            return [
                JobObservation(
                    id=UUID(row.id),
                    job_record_id=UUID(row.job_record_id),
                    kind=JobObservationKind(row.kind),
                    requested_url=row.requested_url,
                    resolved_url=row.resolved_url,
                    checked_at=ensure_utc(row.checked_at),
                    http_status=row.http_status,
                    content_hash=row.content_hash,
                    message=row.message,
                )
                for row in rows
            ]

    def get_current_job(self, record_id: UUID) -> JobPosting | None:
        with self.session_factory() as session:
            row = session.get(JobRecordRow, str(record_id))
            if row is None or row.current_revision_id is None:
                return None
            revision = session.get(JobRevisionRow, row.current_revision_id)
            if revision is None:
                raise RuntimeError("corpus record points to a missing job revision")
            job = normalize_placeholder_employer(
                JobPosting.model_validate_json(revision.posting_json)
            )
            # Deterministic guidance improves over time independently of the
            # expensive canonical job extraction. Rehydrate missing public
            # application logistics when an older revision is read, so an
            # unchanged URL or manual paste benefits immediately without an
            # LLM call or a fabricated source revision.
            deterministic = extract_application_guidance(
                job.source_text,
                source_url=str(job.source_url) if job.source_url is not None else None,
            )
            current_guidance = merge_application_guidance(
                deterministic,
                job.application_guidance,
            )
            # model_copy(update=...) deliberately skips validation.  That is
            # unsafe at this persistence boundary because newly derived
            # guidance could otherwise travel through the application until a
            # containing dashboard model happens to revalidate JobPosting.
            # Rebuild the complete model here so every returned job preserves
            # the source-grounded evidence contract.
            payload = job.model_dump(mode="python")
            payload["application_guidance"] = current_guidance
            return JobPosting.model_validate(payload)

    def list_live_jobs(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for record in self.list_records():
            if record.availability != JobAvailability.LIVE:
                continue
            job = self.get_current_job(record.id)
            if job is not None:
                jobs.append(job)
        return jobs

    def store_revision(
        self,
        document: FetchedDocument,
        posting: JobPosting,
        kind: JobObservationKind,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> JobRecord:
        if kind not in {JobObservationKind.NEW, JobObservationKind.CHANGED}:
            raise ValueError("a stored revision must be new or changed")
        now = utc_now()
        with self.session_factory.begin() as session:
            self._fence_background_commit(
                session,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
            row = self._find_row(session, document.requested_url, document.final_url)
            if row is None:
                if kind != JobObservationKind.NEW:
                    raise ValueError("a missing corpus record must be stored as new")
                row = JobRecordRow(
                    id=str(uuid4()),
                    canonical_url=normalize_job_url(document.final_url),
                    availability=JobAvailability.LIVE,
                    last_observation_kind=kind,
                    current_revision_id=None,
                    current_content_hash=None,
                    first_seen_at=document.fetched_at,
                    last_seen_at=document.fetched_at,
                    last_checked_at=document.fetched_at,
                    last_http_status=document.status_code,
                    unavailable_reason=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            elif kind == JobObservationKind.NEW and row.current_revision_id is not None:
                raise ValueError("an existing corpus record cannot be stored as new")

            self._ensure_alias(session, row, document.requested_url)
            self._ensure_alias(session, row, document.final_url)
            revision_id = str(uuid4())
            session.add(
                JobRevisionRow(
                    id=revision_id,
                    job_record_id=row.id,
                    posting_id=str(posting.id),
                    content_hash=posting.content_hash,
                    posting_json=posting.model_dump_json(),
                    observed_at=posting.observed_at,
                    created_at=now,
                )
            )
            row.current_revision_id = revision_id
            row.current_content_hash = posting.content_hash
            row.availability = JobAvailability.LIVE
            row.last_observation_kind = kind
            if row.first_seen_at is None:
                row.first_seen_at = document.fetched_at
            row.last_seen_at = document.fetched_at
            row.last_checked_at = document.fetched_at
            row.last_http_status = document.status_code
            row.unavailable_reason = None
            row.updated_at = now
            session.add(
                JobObservationRow(
                    id=str(uuid4()),
                    job_record_id=row.id,
                    kind=kind,
                    requested_url=document.requested_url,
                    resolved_url=document.final_url,
                    checked_at=document.fetched_at,
                    http_status=document.status_code,
                    content_hash=posting.content_hash,
                    message=None,
                )
            )
            session.flush()
            return self._to_record(session, row)

    def store_manual_revision(
        self,
        identity_url: str,
        posting: JobPosting,
        kind: JobObservationKind,
    ) -> JobRecord:
        """Store user-pasted source text without claiming a network verification.

        ``identity_url`` is either the optional source link supplied by the user or
        a private synthetic HTTPS identity.  It exists solely because the corpus
        uses URL-shaped stable identities; this method never fetches it.
        """

        if kind not in {JobObservationKind.NEW, JobObservationKind.CHANGED}:
            raise ValueError("a stored manual revision must be new or changed")
        normalized_identity = normalize_job_url(identity_url)
        observed_at = posting.observed_at
        now = utc_now()
        with self.session_factory.begin() as session:
            row = self._find_row(session, normalized_identity)
            if row is None:
                if kind != JobObservationKind.NEW:
                    raise ValueError("a missing manual corpus record must be stored as new")
                row = JobRecordRow(
                    id=str(uuid4()),
                    canonical_url=normalized_identity,
                    availability=JobAvailability.LIVE,
                    last_observation_kind=kind,
                    current_revision_id=None,
                    current_content_hash=None,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    last_checked_at=observed_at,
                    last_http_status=None,
                    unavailable_reason=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            elif kind == JobObservationKind.NEW and row.current_revision_id is not None:
                raise ValueError("an existing manual corpus record cannot be stored as new")

            self._ensure_alias(session, row, normalized_identity)
            revision_id = str(uuid4())
            session.add(
                JobRevisionRow(
                    id=revision_id,
                    job_record_id=row.id,
                    posting_id=str(posting.id),
                    content_hash=posting.content_hash,
                    posting_json=posting.model_dump_json(),
                    observed_at=observed_at,
                    created_at=now,
                )
            )
            row.current_revision_id = revision_id
            row.current_content_hash = posting.content_hash
            row.availability = JobAvailability.LIVE
            row.last_observation_kind = kind
            if row.first_seen_at is None:
                row.first_seen_at = observed_at
            row.last_seen_at = observed_at
            row.last_checked_at = observed_at
            row.last_http_status = None
            row.unavailable_reason = None
            row.updated_at = now
            session.add(
                JobObservationRow(
                    id=str(uuid4()),
                    job_record_id=row.id,
                    kind=kind,
                    requested_url=normalized_identity,
                    resolved_url=(str(posting.source_url) if posting.source_url else None),
                    checked_at=observed_at,
                    http_status=None,
                    content_hash=posting.content_hash,
                    message="Manual input saved locally; no network verification was attempted.",
                )
            )
            session.flush()
            return self._to_record(session, row)

    def record_unchanged(
        self,
        document: FetchedDocument,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> JobRecord:
        now = utc_now()
        with self.session_factory.begin() as session:
            self._fence_background_commit(
                session,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
            row = self._find_row(session, document.requested_url, document.final_url)
            if row is None or row.current_content_hash is None:
                raise ValueError("cannot record unchanged content without an existing revision")
            revision = session.get(JobRevisionRow, row.current_revision_id)
            if revision is None:
                raise RuntimeError("corpus record points to a missing job revision")
            cached_job = JobPosting.model_validate_json(revision.posting_json)
            refreshed_payload = cached_job.model_dump(mode="python")
            refreshed_payload.update(
                {
                    "source_name": document.final_url,
                    "source_url": document.final_url,
                    "requested_url": document.requested_url,
                    "url_http_status": document.status_code,
                    "url_checked_at": document.fetched_at,
                }
            )
            refreshed_job = JobPosting.model_validate(refreshed_payload)
            revision.posting_json = refreshed_job.model_dump_json()
            self._ensure_alias(session, row, document.requested_url)
            self._ensure_alias(session, row, document.final_url)
            row.availability = JobAvailability.LIVE
            row.last_observation_kind = JobObservationKind.UNCHANGED
            row.last_seen_at = document.fetched_at
            row.last_checked_at = document.fetched_at
            row.last_http_status = document.status_code
            row.unavailable_reason = None
            row.updated_at = now
            session.add(
                JobObservationRow(
                    id=str(uuid4()),
                    job_record_id=row.id,
                    kind=JobObservationKind.UNCHANGED,
                    requested_url=document.requested_url,
                    resolved_url=document.final_url,
                    checked_at=document.fetched_at,
                    http_status=document.status_code,
                    content_hash=row.current_content_hash,
                    message="Reused the current canonical extraction.",
                )
            )
            session.flush()
            return self._to_record(session, row)

    def record_failure(
        self,
        requested_url: str,
        failure_kind: UrlFailureKind,
        message: str,
        *,
        http_status: int | None = None,
        checked_at: datetime | None = None,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> JobRecord:
        checked_at = checked_at or utc_now()
        observation_kind = (
            JobObservationKind.EXPIRED
            if failure_kind == UrlFailureKind.EXPIRED
            else JobObservationKind.UNREACHABLE
        )
        availability = (
            JobAvailability.EXPIRED
            if observation_kind == JobObservationKind.EXPIRED
            else JobAvailability.UNREACHABLE
        )
        now = utc_now()
        with self.session_factory.begin() as session:
            self._fence_background_commit(
                session,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
            row = self._find_row(session, requested_url)
            if row is None:
                row = JobRecordRow(
                    id=str(uuid4()),
                    canonical_url=normalize_job_url(requested_url),
                    availability=availability,
                    last_observation_kind=observation_kind,
                    current_revision_id=None,
                    current_content_hash=None,
                    first_seen_at=None,
                    last_seen_at=None,
                    last_checked_at=checked_at,
                    last_http_status=http_status,
                    unavailable_reason=message,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            self._ensure_alias(session, row, requested_url)
            row.availability = availability
            row.last_observation_kind = observation_kind
            row.last_checked_at = checked_at
            row.last_http_status = http_status
            row.unavailable_reason = message
            row.updated_at = now
            session.add(
                JobObservationRow(
                    id=str(uuid4()),
                    job_record_id=row.id,
                    kind=observation_kind,
                    requested_url=requested_url,
                    resolved_url=None,
                    checked_at=checked_at,
                    http_status=http_status,
                    content_hash=row.current_content_hash,
                    message=message,
                )
            )
            session.flush()
            return self._to_record(session, row)

    def record_extraction_failure(
        self,
        document: FetchedDocument,
        message: str,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> JobRecord:
        """Keep a reachable source visible when canonical extraction fails."""

        now = utc_now()
        with self.session_factory.begin() as session:
            self._fence_background_commit(
                session,
                commit_task_id=commit_task_id,
                expected_task_attempt=expected_task_attempt,
                task_claim_token=task_claim_token,
            )
            row = self._find_row(session, document.requested_url, document.final_url)
            if row is None:
                row = JobRecordRow(
                    id=str(uuid4()),
                    canonical_url=normalize_job_url(document.final_url),
                    availability=JobAvailability.NEEDS_ATTENTION,
                    last_observation_kind=JobObservationKind.EXTRACTION_FAILED,
                    current_revision_id=None,
                    current_content_hash=None,
                    first_seen_at=document.fetched_at,
                    last_seen_at=document.fetched_at,
                    last_checked_at=document.fetched_at,
                    last_http_status=document.status_code,
                    unavailable_reason=message,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
            self._ensure_alias(session, row, document.requested_url)
            self._ensure_alias(session, row, document.final_url)
            row.availability = JobAvailability.NEEDS_ATTENTION
            row.last_observation_kind = JobObservationKind.EXTRACTION_FAILED
            if row.first_seen_at is None:
                row.first_seen_at = document.fetched_at
            row.last_seen_at = document.fetched_at
            row.last_checked_at = document.fetched_at
            row.last_http_status = document.status_code
            row.unavailable_reason = message
            row.updated_at = now
            session.add(
                JobObservationRow(
                    id=str(uuid4()),
                    job_record_id=row.id,
                    kind=JobObservationKind.EXTRACTION_FAILED,
                    requested_url=document.requested_url,
                    resolved_url=document.final_url,
                    checked_at=document.fetched_at,
                    http_status=document.status_code,
                    content_hash=row.current_content_hash,
                    message=message,
                )
            )
            session.flush()
            return self._to_record(session, row)
