"""Durable Explore requests and public discovery result snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .background import fence_background_task_commit
from .database import Base, Database
from .discovery import (
    DiscoveredJob,
    DiscoveryQuery,
    SourceReadiness,
    WEB_DISCOVERY_PROVIDER_NAMES,
    discovery_result_is_plausible_individual_job,
    web_discovery_source_is_excluded,
    web_discovery_title_is_error_landing,
    web_discovery_url_is_error_landing,
)
from .profile import StrictModel


DEFAULT_EXPLORE_PREVIEW_LIMIT = 9


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ExploreSearchSnapshot(StrictModel):
    """Workspace-owned query and the public jobs returned for it."""

    task_id: UUID
    workspace_id: UUID
    query: DiscoveryQuery
    query_text: str
    location: str
    work_arrangement: str
    compass_used: bool
    hide_remote_only: bool
    results: list[DiscoveredJob]
    regional_result_count: int
    created_at: datetime
    completed_at: datetime | None = None


class ExploreSearchRow(Base):
    __tablename__ = "explore_searches"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("background_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_json: Mapped[str] = mapped_column(Text, nullable=False)
    query_text: Mapped[str] = mapped_column(String(400), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    work_arrangement: Mapped[str] = mapped_column(String(160), nullable=False)
    compass_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hide_remote_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    results_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    regional_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExploreSearchRepository:
    """Persist enough state to resume discovery without holding a browser request."""

    def __init__(
        self,
        database: Database,
        *,
        preview_limit: int = DEFAULT_EXPLORE_PREVIEW_LIMIT,
    ) -> None:
        self.database = database
        self.preview_limit = max(3, min(12, preview_limit))

    def create(
        self,
        *,
        task_id: UUID,
        workspace_id: UUID,
        query: DiscoveryQuery,
        query_text: str,
        location: str,
        compass_used: bool,
        hide_remote_only: bool,
    ) -> ExploreSearchSnapshot:
        row = ExploreSearchRow(
            task_id=str(task_id),
            workspace_id=str(workspace_id),
            query_json=query.model_dump_json(),
            query_text=query_text,
            location=location,
            work_arrangement=query.work_arrangement_label,
            compass_used=compass_used,
            hide_remote_only=hide_remote_only,
            results_json="[]",
            regional_result_count=0,
            created_at=utc_now(),
        )
        with self.database.session_factory.begin() as session:
            session.add(row)
        return self._from_row(row)

    def get(self, task_id: UUID) -> ExploreSearchSnapshot | None:
        with self.database.session_factory() as session:
            row = session.get(ExploreSearchRow, str(task_id))
            return self._from_row(row) if row else None

    def latest_completed(self, workspace_id: UUID) -> ExploreSearchSnapshot | None:
        with self.database.session_factory() as session:
            row = session.scalar(
                select(ExploreSearchRow)
                .where(
                    ExploreSearchRow.workspace_id == str(workspace_id),
                    ExploreSearchRow.completed_at.is_not(None),
                )
                .order_by(ExploreSearchRow.completed_at.desc())
                .limit(1)
            )
            return self._from_row(row) if row else None

    def update_preview(
        self,
        task_id: UUID,
        *,
        results: list[DiscoveredJob],
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> ExploreSearchSnapshot:
        """Persist a bounded, replaceable ranking while discovery is running."""

        payload = json.dumps(
            [job.model_dump(mode="json") for job in results[: self.preview_limit]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.database.session_factory.begin() as session:
            if (expected_task_attempt is None) != (task_claim_token is None):
                raise ValueError("task attempt and claim token must be supplied together")
            if expected_task_attempt is not None and task_claim_token is not None:
                fence_background_task_commit(
                    session,
                    task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            row = session.get(ExploreSearchRow, str(task_id))
            if row is None:
                raise KeyError(f"unknown Explore search: {task_id}")
            # A delayed callback must never replace the completed full result
            # set with the bounded live preview.
            if row.completed_at is None and row.results_json != payload:
                row.results_json = payload
                session.flush()
            return self._from_row(row)

    def complete(
        self,
        task_id: UUID,
        *,
        results: list[DiscoveredJob],
        regional_result_count: int,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> ExploreSearchSnapshot:
        with self.database.session_factory.begin() as session:
            if (expected_task_attempt is None) != (task_claim_token is None):
                raise ValueError("task attempt and claim token must be supplied together")
            if expected_task_attempt is not None and task_claim_token is not None:
                fence_background_task_commit(
                    session,
                    task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            row = session.get(ExploreSearchRow, str(task_id))
            if row is None:
                raise KeyError(f"unknown Explore search: {task_id}")
            row.results_json = json.dumps(
                [job.model_dump(mode="json") for job in results],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            row.regional_result_count = max(0, regional_result_count)
            row.completed_at = utc_now()
            session.flush()
            return self._from_row(row)

    def remove_result_urls(
        self,
        task_id: UUID,
        normalized_urls: set[str],
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> None:
        if not normalized_urls:
            return
        from .job_repository import normalize_job_url

        with self.database.session_factory.begin() as session:
            if (commit_task_id is None) != (expected_task_attempt is None) or (
                commit_task_id is None
            ) != (task_claim_token is None):
                raise ValueError("task id, attempt, and claim token must be supplied together")
            if (
                commit_task_id is not None
                and expected_task_attempt is not None
                and task_claim_token is not None
            ):
                fence_background_task_commit(
                    session,
                    commit_task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            row = session.get(ExploreSearchRow, str(task_id))
            if row is None or row.completed_at is None:
                return
            results = [
                job
                for job in self._results(row.results_json)
                if normalize_job_url(str(job.source_url)) not in normalized_urls
            ]
            row.results_json = json.dumps(
                [job.model_dump(mode="json") for job in results],
                ensure_ascii=False,
                separators=(",", ":"),
            )

    def update_result_readiness(
        self,
        task_id: UUID,
        normalized_urls: set[str],
        readiness: SourceReadiness | str = SourceReadiness.MANUAL_REQUIRED,
        *,
        commit_task_id: UUID | None = None,
        expected_task_attempt: int | None = None,
        task_claim_token: UUID | None = None,
    ) -> int:
        """Mark matching snapshot rows without deleting recoverable discoveries."""

        if not normalized_urls:
            return 0
        from .job_repository import normalize_job_url

        target_readiness = SourceReadiness(readiness)
        updated = 0
        with self.database.session_factory.begin() as session:
            if (commit_task_id is None) != (expected_task_attempt is None) or (
                commit_task_id is None
            ) != (task_claim_token is None):
                raise ValueError("task id, attempt, and claim token must be supplied together")
            if (
                commit_task_id is not None
                and expected_task_attempt is not None
                and task_claim_token is not None
            ):
                fence_background_task_commit(
                    session,
                    commit_task_id,
                    expected_attempt=expected_task_attempt,
                    claim_token=task_claim_token,
                )
            row = session.get(ExploreSearchRow, str(task_id))
            if row is None or row.completed_at is None:
                return 0
            results: list[DiscoveredJob] = []
            for job in self._results(row.results_json):
                if normalize_job_url(str(job.source_url)) in normalized_urls:
                    if job.source_readiness != target_readiness:
                        job = job.model_copy(update={"source_readiness": target_readiness})
                        updated += 1
                results.append(job)
            row.results_json = json.dumps(
                [job.model_dump(mode="json") for job in results],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return updated

    @classmethod
    def _from_row(cls, row: ExploreSearchRow) -> ExploreSearchSnapshot:
        results = cls._results(row.results_json)
        query = DiscoveryQuery.model_validate_json(row.query_json)
        regional_result_count = (
            sum(
                1
                for job in results
                if not job.remote
                and job.distance_km is not None
                and job.distance_km <= query.regional_radius_km
            )
            if query.location.strip()
            else 0
        )
        return ExploreSearchSnapshot(
            task_id=UUID(row.task_id),
            workspace_id=UUID(row.workspace_id),
            query=query,
            query_text=row.query_text,
            location=row.location,
            work_arrangement=row.work_arrangement,
            compass_used=row.compass_used,
            hide_remote_only=row.hide_remote_only,
            results=results,
            regional_result_count=regional_result_count,
            created_at=ensure_utc(row.created_at),
            completed_at=ensure_utc(row.completed_at),
        )

    @staticmethod
    def _results(value: str) -> list[DiscoveredJob]:
        restored: list[DiscoveredJob] = []
        for item in json.loads(value):
            if not isinstance(item, dict):
                continue
            try:
                job = DiscoveredJob.model_validate(item)
            except ValueError:
                continue
            if not discovery_result_is_plausible_individual_job(
                str(job.source_url),
                job.title,
                job.summary,
            ):
                continue
            if all(
                provider in WEB_DISCOVERY_PROVIDER_NAMES
                for provider in job.effective_source_providers
            ) and web_discovery_source_is_excluded(str(job.source_url)):
                continue
            if web_discovery_url_is_error_landing(str(job.source_url)):
                continue
            if web_discovery_title_is_error_landing(job.title):
                continue
            restored.append(job)
        return restored
