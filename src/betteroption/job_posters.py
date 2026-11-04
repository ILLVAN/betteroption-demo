"""Verified employer access and first-party public job postings.

The candidate and employer boundaries deliberately stay separate: a verified
poster may publish public vacancy data, but this repository never exposes a
candidate account, persona, Compass, match, rating, or application draft.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .discovery import DiscoveredJob, DiscoveryQuery, SourceReadiness
from .profile import StrictModel


class JobPosterAccessStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EmployerPostingStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class JobPosterAccessRow(Base):
    __tablename__ = "job_poster_access"

    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    company_website: Mapped[str] = mapped_column(String(2_000), nullable=False)
    work_email: Mapped[str] = mapped_column(String(320), nullable=False)
    requester_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reviewer_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )


class EmployerJobPostingRow(Base):
    __tablename__ = "employer_job_postings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    employer_name: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    work_model: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    application_url: Mapped[str] = mapped_column(String(2_000), nullable=False, default="")
    application_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class JobPosterAccess(StrictModel):
    account_id: UUID
    company_name: str
    company_website: str
    work_email: str
    requester_note: str = ""
    status: JobPosterAccessStatus
    reviewer_note: str = ""
    requested_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by_account_id: UUID | None = None


class EmployerJobPosting(StrictModel):
    id: UUID
    owner_account_id: UUID
    title: str
    employer_name: str
    location: str
    work_model: str
    summary: str
    description: str
    application_url: str = ""
    application_email: str = ""
    status: EmployerPostingStatus
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None

    @property
    def remote(self) -> bool:
        return self.work_model.casefold() in {"remote", "remote only"}


class JobPosterError(ValueError):
    """Raised when poster access or publication fails closed."""


_FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "gmx.de",
        "gmx.net",
        "hotmail.com",
        "icloud.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "web.de",
        "yahoo.com",
    }
)
_GENERIC_EMPLOYER_NAMES = frozenset(
    {"company", "employer", "unknown", "not stated", "traceable company"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean(value: str, *, label: str, maximum: int, required: bool = True) -> str:
    result = " ".join(value.split())
    if required and not result:
        raise JobPosterError(f"Enter {label}.")
    if len(result) > maximum:
        raise JobPosterError(f"{label.capitalize()} is too long.")
    return result


def _clean_multiline(value: str, *, label: str, maximum: int, required: bool = True) -> str:
    result = "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()
    if required and not result:
        raise JobPosterError(f"Enter {label}.")
    if len(result) > maximum:
        raise JobPosterError(f"{label.capitalize()} is too long.")
    return result


def _https_url(value: str, *, label: str, required: bool = True) -> str:
    result = value.strip()
    if not result and not required:
        return ""
    try:
        parsed = urlsplit(result)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError as exc:
        raise JobPosterError(f"{label.capitalize()} must be a public HTTPS URL.") from exc
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise JobPosterError(f"{label.capitalize()} must be a public HTTPS URL.")
    try:
        address = ip_address(host)
    except ValueError:
        if (
            "." not in host
            or host == "localhost"
            or host.endswith((".internal", ".local", ".localhost"))
        ):
            raise JobPosterError(f"{label.capitalize()} must be a public HTTPS URL.")
    else:
        if not address.is_global:
            raise JobPosterError(f"{label.capitalize()} must be a public HTTPS URL.")
    return result


def _email(value: str, *, label: str, required: bool = True) -> str:
    result = value.strip().casefold()
    if not result and not required:
        return ""
    if not result or len(result) > 320 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", result):
        raise JobPosterError(f"Enter a valid {label}.")
    return result


def _email_domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].casefold()


def _host_belongs_to_email(website: str, email: str) -> bool:
    host = (urlsplit(website).hostname or "").casefold().removeprefix("www.")
    domain = _email_domain(email)
    return bool(host and domain and (host == domain or host.endswith(f".{domain}")))


class JobPosterRepository:
    """Persist approval requests and public vacancy records."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _access(row: JobPosterAccessRow) -> JobPosterAccess:
        return JobPosterAccess(
            account_id=UUID(row.account_id),
            company_name=row.company_name,
            company_website=row.company_website,
            work_email=row.work_email,
            requester_note=row.requester_note,
            status=JobPosterAccessStatus(row.status),
            reviewer_note=row.reviewer_note,
            requested_at=_utc(row.requested_at),
            reviewed_at=_utc(row.reviewed_at),
            reviewed_by_account_id=(
                UUID(row.reviewed_by_account_id) if row.reviewed_by_account_id else None
            ),
        )

    @staticmethod
    def _posting(row: EmployerJobPostingRow) -> EmployerJobPosting:
        return EmployerJobPosting(
            id=UUID(row.id),
            owner_account_id=UUID(row.owner_account_id),
            title=row.title,
            employer_name=row.employer_name,
            location=row.location,
            work_model=row.work_model,
            summary=row.summary,
            description=row.description,
            application_url=row.application_url,
            application_email=row.application_email,
            status=EmployerPostingStatus(row.status),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            published_at=_utc(row.published_at),
        )

    def access_for(self, account_id: UUID) -> JobPosterAccess | None:
        with self.session_factory() as session:
            row = session.get(JobPosterAccessRow, str(account_id))
            return self._access(row) if row else None

    def request_access(
        self,
        account_id: UUID,
        *,
        company_name: str,
        company_website: str,
        work_email: str,
        requester_note: str = "",
    ) -> JobPosterAccess:
        company = _clean(company_name, label="the company name", maximum=300)
        website = _https_url(company_website, label="company website")
        email = _email(work_email, label="work email address")
        note = _clean_multiline(
            requester_note,
            label="the verification note",
            maximum=2_000,
            required=False,
        )
        if _email_domain(email) in _FREE_EMAIL_DOMAINS:
            raise JobPosterError("Use a company email address for poster verification.")
        if not _host_belongs_to_email(website, email) and not note:
            raise JobPosterError(
                "The website and work-email domains differ. Explain the relationship for review."
            )
        now = _now()
        with self.session_factory.begin() as session:
            row = session.get(JobPosterAccessRow, str(account_id))
            if row is not None and row.status == JobPosterAccessStatus.APPROVED.value:
                return self._access(row)
            if row is None:
                row = JobPosterAccessRow(
                    account_id=str(account_id),
                    company_name=company,
                    company_website=website,
                    work_email=email,
                    requester_note=note,
                    status=JobPosterAccessStatus.PENDING.value,
                    reviewer_note="",
                    requested_at=now,
                    reviewed_at=None,
                    reviewed_by_account_id=None,
                )
                session.add(row)
            else:
                row.company_name = company
                row.company_website = website
                row.work_email = email
                row.requester_note = note
                row.status = JobPosterAccessStatus.PENDING.value
                row.reviewer_note = ""
                row.requested_at = now
                row.reviewed_at = None
                row.reviewed_by_account_id = None
            session.flush()
            return self._access(row)

    def list_access_requests(self) -> list[JobPosterAccess]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(JobPosterAccessRow).order_by(JobPosterAccessRow.requested_at.desc())
            ).all()
            return [self._access(row) for row in rows]

    def review_access(
        self,
        account_id: UUID,
        *,
        approved: bool,
        reviewer_account_id: UUID,
        reviewer_note: str = "",
    ) -> JobPosterAccess:
        note = _clean_multiline(
            reviewer_note,
            label="the review note",
            maximum=2_000,
            required=False,
        )
        if not approved and not note:
            raise JobPosterError("Add a reason when declining poster access.")
        with self.session_factory.begin() as session:
            row = session.get(JobPosterAccessRow, str(account_id))
            if row is None:
                raise JobPosterError("Poster access request not found.")
            row.status = (
                JobPosterAccessStatus.APPROVED.value
                if approved
                else JobPosterAccessStatus.REJECTED.value
            )
            row.reviewer_note = note
            row.reviewed_at = _now()
            row.reviewed_by_account_id = str(reviewer_account_id)
            if not approved:
                published = session.scalars(
                    select(EmployerJobPostingRow).where(
                        EmployerJobPostingRow.owner_account_id == str(account_id),
                        EmployerJobPostingRow.status == EmployerPostingStatus.PUBLISHED.value,
                    )
                ).all()
                for posting in published:
                    posting.status = EmployerPostingStatus.WITHDRAWN.value
                    posting.updated_at = row.reviewed_at
            session.flush()
            return self._access(row)

    def require_approved(self, account_id: UUID) -> JobPosterAccess:
        access = self.access_for(account_id)
        if access is None or access.status != JobPosterAccessStatus.APPROVED:
            raise JobPosterError("Verified job-poster access is required.")
        return access

    def create_posting(
        self,
        account_id: UUID,
        *,
        title: str,
        employer_name: str,
        location: str,
        work_model: str,
        summary: str,
        description: str,
        application_url: str = "",
        application_email: str = "",
        publish: bool = False,
    ) -> EmployerJobPosting:
        access = self.require_approved(account_id)
        values = self._validate_posting(
            title=title,
            employer_name=employer_name,
            location=location,
            work_model=work_model,
            summary=summary,
            description=description,
            application_url=application_url,
            application_email=application_email,
            expected_employer=access.company_name,
            publish=publish,
        )
        now = _now()
        row = EmployerJobPostingRow(
            id=str(uuid4()),
            owner_account_id=str(account_id),
            **values,
            status=(
                EmployerPostingStatus.PUBLISHED.value
                if publish
                else EmployerPostingStatus.DRAFT.value
            ),
            created_at=now,
            updated_at=now,
            published_at=now if publish else None,
        )
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            return self._posting(row)

    def update_posting(
        self,
        account_id: UUID,
        posting_id: UUID,
        *,
        title: str,
        employer_name: str,
        location: str,
        work_model: str,
        summary: str,
        description: str,
        application_url: str = "",
        application_email: str = "",
    ) -> EmployerJobPosting:
        access = self.require_approved(account_id)
        with self.session_factory.begin() as session:
            row = session.get(EmployerJobPostingRow, str(posting_id))
            if row is None or row.owner_account_id != str(account_id):
                raise JobPosterError("Job posting not found.")
            values = self._validate_posting(
                title=title,
                employer_name=employer_name,
                location=location,
                work_model=work_model,
                summary=summary,
                description=description,
                application_url=application_url,
                application_email=application_email,
                expected_employer=access.company_name,
                publish=row.status == EmployerPostingStatus.PUBLISHED.value,
            )
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = _now()
            session.flush()
            return self._posting(row)

    def publish(self, account_id: UUID, posting_id: UUID) -> EmployerJobPosting:
        access = self.require_approved(account_id)
        with self.session_factory.begin() as session:
            row = session.get(EmployerJobPostingRow, str(posting_id))
            if row is None or row.owner_account_id != str(account_id):
                raise JobPosterError("Job posting not found.")
            self._validate_posting(
                title=row.title,
                employer_name=row.employer_name,
                location=row.location,
                work_model=row.work_model,
                summary=row.summary,
                description=row.description,
                application_url=row.application_url,
                application_email=row.application_email,
                expected_employer=access.company_name,
                publish=True,
            )
            now = _now()
            row.status = EmployerPostingStatus.PUBLISHED.value
            row.updated_at = now
            row.published_at = row.published_at or now
            session.flush()
            return self._posting(row)

    def withdraw(self, account_id: UUID, posting_id: UUID) -> EmployerJobPosting:
        self.require_approved(account_id)
        with self.session_factory.begin() as session:
            row = session.get(EmployerJobPostingRow, str(posting_id))
            if row is None or row.owner_account_id != str(account_id):
                raise JobPosterError("Job posting not found.")
            row.status = EmployerPostingStatus.WITHDRAWN.value
            row.updated_at = _now()
            session.flush()
            return self._posting(row)

    def get_owned(self, account_id: UUID, posting_id: UUID) -> EmployerJobPosting | None:
        with self.session_factory() as session:
            row = session.get(EmployerJobPostingRow, str(posting_id))
            if row is None or row.owner_account_id != str(account_id):
                return None
            return self._posting(row)

    def get_published(self, posting_id: UUID) -> EmployerJobPosting | None:
        with self.session_factory() as session:
            row = session.get(EmployerJobPostingRow, str(posting_id))
            if row is None or row.status != EmployerPostingStatus.PUBLISHED.value:
                return None
            return self._posting(row)

    def list_owned(self, account_id: UUID) -> list[EmployerJobPosting]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EmployerJobPostingRow)
                .where(EmployerJobPostingRow.owner_account_id == str(account_id))
                .order_by(EmployerJobPostingRow.updated_at.desc())
            ).all()
            return [self._posting(row) for row in rows]

    def list_published(self) -> list[EmployerJobPosting]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(EmployerJobPostingRow)
                .where(EmployerJobPostingRow.status == EmployerPostingStatus.PUBLISHED.value)
                .order_by(EmployerJobPostingRow.published_at.desc())
            ).all()
            return [self._posting(row) for row in rows]

    @staticmethod
    def _validate_posting(
        *,
        title: str,
        employer_name: str,
        location: str,
        work_model: str,
        summary: str,
        description: str,
        application_url: str,
        application_email: str,
        expected_employer: str,
        publish: bool,
    ) -> dict[str, str]:
        clean_employer = _clean(employer_name, label="the employer name", maximum=500)
        if clean_employer.casefold() in _GENERIC_EMPLOYER_NAMES:
            raise JobPosterError("Use the employer's identifiable public name.")
        if clean_employer.casefold() != expected_employer.casefold():
            raise JobPosterError(
                "The employer name must match the company approved for this poster account."
            )
        values = {
            "title": _clean(title, label="the job title", maximum=500),
            "employer_name": clean_employer,
            "location": _clean(location, label="a location or Remote", maximum=500),
            "work_model": _clean(work_model, label="the work model", maximum=80),
            "summary": _clean_multiline(summary, label="a concise summary", maximum=1_500),
            "description": _clean_multiline(
                description,
                label="the public job description",
                maximum=30_000,
            ),
            "application_url": _https_url(
                application_url,
                label="application URL",
                required=False,
            ),
            "application_email": _email(
                application_email,
                label="application email address",
                required=False,
            ),
        }
        if publish and len(values["description"]) < 120:
            raise JobPosterError(
                "Add at least 120 characters of public job detail before publishing."
            )
        if publish and not (values["application_url"] or values["application_email"]):
            raise JobPosterError("Add an application URL or application email before publishing.")
        return values


class BetterOptionPostedJobProvider:
    """Expose approved, published listings as a first-party Explore source."""

    name = "betteroption-posted"
    attribution = "Employer-published jobs verified by the WorkLifeBalance operator"
    attribution_url = "https://github.com/ILLVAN/betteroption"

    def __init__(self, repository: JobPosterRepository, *, public_base_url: str = "") -> None:
        self.repository = repository
        self.public_base_url = public_base_url.rstrip("/") or "http://127.0.0.1:8000"

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        wanted = _search_tokens(" ".join([query.text, *query.desired_terms]))
        excluded = _search_tokens(" ".join(query.excluded_terms))
        jobs: list[DiscoveredJob] = []
        for posting in self.repository.list_published():
            if query.remote_only and not posting.remote:
                continue
            if query.onsite_only and posting.remote:
                continue
            material = " ".join(
                (
                    posting.title,
                    posting.employer_name,
                    posting.location,
                    posting.work_model,
                    posting.summary,
                    posting.description,
                )
            )
            material_tokens = _search_tokens(material)
            if excluded.intersection(material_tokens):
                continue
            overlap = wanted.intersection(material_tokens)
            if wanted and not overlap:
                continue
            score = min(100, 45 + round(55 * len(overlap) / max(1, len(wanted))))
            jobs.append(
                DiscoveredJob(
                    provider=self.name,
                    source_readiness=SourceReadiness.READY,
                    external_id=str(posting.id),
                    title=posting.title,
                    company=posting.employer_name,
                    location=posting.location,
                    remote=posting.remote,
                    tags=["Employer published", posting.work_model],
                    summary=posting.summary,
                    source_url=f"{self.public_base_url}/published-jobs/{posting.id}",
                    published_at=posting.published_at,
                    keyword_relevance=score,
                    search_score=score,
                )
            )
        jobs.sort(key=lambda job: (job.search_score or 0, job.keyword_relevance or 0), reverse=True)
        return jobs[: query.limit]


def _search_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w+#.-]{2,}", value.casefold())
        if token not in {"and", "der", "die", "for", "für", "the", "und"}
    }
