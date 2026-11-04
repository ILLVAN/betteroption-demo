"""Read-only application service and view models for the local dashboard."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field

from .job_repository import (
    JobAvailability,
    JobObservation,
    JobRecord,
    JobRepository,
    JobRevision,
)
from .jobs import JobPosting, JobSourceType
from .matching import MatchDisposition, MatchResult, MatchRun
from .posting_date import PostingFreshness
from .presentation import format_job_location, job_is_remote_only
from .profile import EvidenceStatus, RequirementLevel, StrictModel
from .profile_repository import ProfileWorkspaceRepository
from .result_repository import ApplicationState, JobInteraction, ResultRepository
from .session import ProfileSession


DISPOSITION_LABELS = {
    MatchDisposition.TOP: "Strong fit",
    MatchDisposition.STRETCH: "Worth a look",
    MatchDisposition.BLOCKED: "Outside your boundaries",
}

AVAILABILITY_LABELS = {
    JobAvailability.LIVE: "Open now",
    JobAvailability.EXPIRED: "Closed",
    JobAvailability.UNREACHABLE: "Needs a recheck",
    JobAvailability.NEEDS_ATTENTION: "Needs extraction",
}


class ProfileSnapshot(StrictModel):
    available: bool = False
    completed_sections: int = 0
    total_sections: int = 9
    confirmed_facts: int = 0
    pending_facts: int = 0
    must_haves: int = 0
    preferences: int = 0
    exclusions: int = 0


class OpportunityCard(StrictModel):
    record_id: UUID
    title: str
    company: str
    location: str
    summary: str
    source_url: str
    availability: JobAvailability
    availability_label: str
    last_checked_label: str
    revision_count: int
    is_extracted: bool
    source_is_verified: bool
    source_is_manual: bool = False
    score: int | None = Field(default=None, ge=0, le=100)
    disposition: MatchDisposition | None = None
    disposition_label: str | None = None
    hard_evidence_coverage: int | None = Field(default=None, ge=0, le=100)
    application_state: ApplicationState | None = None
    posting_freshness: PostingFreshness = PostingFreshness.UNKNOWN
    remote_only: bool = False


class DashboardSnapshot(StrictModel):
    profile: ProfileSnapshot
    live_count: int
    closed_count: int
    recheck_count: int
    opportunities: list[OpportunityCard]
    latest_match_available: bool


class OpportunityDetail(StrictModel):
    record: JobRecord
    job: JobPosting | None = None
    card: OpportunityCard
    match: MatchResult | None = None
    revisions: list[JobRevision]
    observations: list[JobObservation]


class DashboardService:
    def __init__(
        self,
        repository: JobRepository,
        *,
        workspaces: ProfileWorkspaceRepository,
        results: ResultRepository | None = None,
        data_directory: Path = Path("local-data"),
        workspace_id: UUID | None = None,
        restrict_to_workspace: bool = False,
    ) -> None:
        self.repository = repository
        self.workspaces = workspaces
        self.results = results
        self.data_directory = data_directory
        self.workspace_id = workspace_id
        self.restrict_to_workspace = restrict_to_workspace

    def overview(self) -> DashboardSnapshot:
        records = self.repository.list_records()
        accessible = self._accessible_record_ids()
        if accessible is not None:
            records = [record for record in records if record.id in accessible]
        match_run = self._latest_match_run()
        matches = self._matches_by_job(match_run)
        visible_result_records = self._visible_result_record_ids()
        interactions = self._interactions()
        cards = [
            self._card(record, matches, visible_result_records, interactions) for record in records
        ]
        cards.sort(
            key=lambda item: (
                item.availability != JobAvailability.LIVE,
                -(item.score if item.score is not None else -1),
                item.company.casefold(),
            )
        )
        return DashboardSnapshot(
            profile=self._profile_snapshot(),
            live_count=sum(item.availability == JobAvailability.LIVE for item in records),
            closed_count=sum(item.availability == JobAvailability.EXPIRED for item in records),
            recheck_count=sum(
                item.availability in {JobAvailability.UNREACHABLE, JobAvailability.NEEDS_ATTENTION}
                for item in records
            ),
            opportunities=cards,
            latest_match_available=match_run is not None,
        )

    def list_opportunities(
        self,
        availability: JobAvailability | None = None,
    ) -> list[OpportunityCard]:
        snapshot = self.overview()
        if availability is None:
            return snapshot.opportunities
        return [item for item in snapshot.opportunities if item.availability == availability]

    def opportunity_detail(self, record_id: UUID) -> OpportunityDetail | None:
        accessible = self._accessible_record_ids()
        if accessible is not None and record_id not in accessible:
            return None
        record = next(
            (item for item in self.repository.list_records() if item.id == record_id),
            None,
        )
        if record is None:
            return None
        job = self.repository.get_current_job(record_id)
        match_run = self._latest_match_run()
        match = self._matches_by_job(match_run).get(job.id) if job else None
        visible_result_records = self._visible_result_record_ids()
        if visible_result_records is not None and record.id not in visible_result_records:
            match = None
        card = self._card(
            record,
            {job.id: match} if job and match else {},
            visible_result_records,
            self._interactions(),
        )
        return OpportunityDetail(
            record=record,
            job=job,
            card=card,
            match=match,
            revisions=self.repository.list_revisions(record_id),
            observations=self.repository.list_observations(record_id),
        )

    def _card(
        self,
        record: JobRecord,
        matches: dict[UUID, MatchResult],
        visible_result_records: set[UUID] | None = None,
        interactions: dict[UUID, JobInteraction] | None = None,
    ) -> OpportunityCard:
        job = self.repository.get_current_job(record.id)
        match = matches.get(job.id) if job else None
        if visible_result_records is not None and record.id not in visible_result_records:
            match = None
        host = urlsplit(record.canonical_url).hostname or "External source"
        if job is None:
            title = {
                JobAvailability.EXPIRED: "Closed job link",
                JobAvailability.NEEDS_ATTENTION: "Job needs extraction",
            }.get(record.availability, "Job link needs a recheck")
            company = host
            location = "Details not extracted yet"
            summary = record.unavailable_reason or "The source could not be read yet."
            source_url = record.canonical_url
        else:
            title = job.title
            company = job.company
            location = format_job_location(job)
            summary = job.summary
            source_url = str(job.source_url or record.canonical_url)
        source_is_manual = job is not None and job.source_type == JobSourceType.MANUAL_TEXT
        return OpportunityCard(
            record_id=record.id,
            title=title,
            company=company,
            location=location,
            summary=summary,
            source_url=source_url,
            availability=record.availability,
            availability_label=(
                "Manual input" if source_is_manual else AVAILABILITY_LABELS[record.availability]
            ),
            last_checked_label=record.last_checked_at.astimezone().strftime("%d %b %Y, %H:%M"),
            revision_count=record.revision_count,
            is_extracted=job is not None,
            source_is_verified=(
                record.availability == JobAvailability.LIVE and not source_is_manual
            ),
            source_is_manual=source_is_manual,
            score=match.score if match else None,
            disposition=match.disposition if match else None,
            disposition_label=DISPOSITION_LABELS[match.disposition] if match else None,
            hard_evidence_coverage=match.hard_evidence_coverage if match else None,
            application_state=(
                interactions.get(record.id).application_state
                if interactions is not None and record.id in interactions
                else ApplicationState.DISCOVERED
                if interactions is not None
                else None
            ),
            posting_freshness=(
                match.posting_date.freshness
                if match is not None and match.posting_date is not None
                else PostingFreshness.UNKNOWN
            ),
            remote_only=job_is_remote_only(job) if job is not None else False,
        )

    def _interactions(self) -> dict[UUID, JobInteraction] | None:
        workspace = self._workspace()
        if self.results is None or workspace is None:
            return None
        return self.results.interactions(workspace.id)

    def _profile_snapshot(self) -> ProfileSnapshot:
        session = self._latest_profile_session()
        if session is None:
            return ProfileSnapshot()
        confirmed = [
            fact
            for fact in session.profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
        ]
        return ProfileSnapshot(
            available=True,
            completed_sections=session.completed_count,
            total_sections=len(session.sections),
            confirmed_facts=len(confirmed),
            pending_facts=len(session.profile.pending_facts),
            must_haves=sum(fact.level == RequirementLevel.MUST_HAVE for fact in confirmed),
            preferences=sum(fact.level == RequirementLevel.PREFERENCE for fact in confirmed),
            exclusions=sum(fact.level == RequirementLevel.EXCLUSION for fact in confirmed),
        )

    def _latest_profile_session(self) -> ProfileSession | None:
        workspace = self._workspace()
        return workspace.session if workspace else None

    def _latest_match_run(self) -> MatchRun | None:
        workspace = self._workspace()
        if self.results is not None and workspace is not None:
            stored = self.results.latest_run(workspace.id)
            if stored is not None:
                return stored.as_match_run()
        path = self._latest_file(self.data_directory / "matches", "match-run-*.json")
        if path is None:
            return None
        try:
            return MatchRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _visible_result_record_ids(self) -> set[UUID] | None:
        workspace = self._workspace()
        if self.results is None or workspace is None:
            return None
        stored = self.results.latest_run(workspace.id)
        if stored is None:
            return None
        visible = {grant.job_record_id for grant in self.results.access_grants(workspace.id)}
        visible.update(
            item.job_record_id
            for item in stored.results
            if item.result.disposition == MatchDisposition.BLOCKED
        )
        return visible

    def _workspace(self):
        if self.workspace_id is not None:
            return self.workspaces.get(self.workspace_id)
        if self.restrict_to_workspace:
            return None
        return self.workspaces.latest()

    def _accessible_record_ids(self) -> set[UUID] | None:
        if self.results is None:
            return None
        if self.workspace_id is None:
            return set() if self.restrict_to_workspace else None
        return {grant.job_record_id for grant in self.results.access_grants(self.workspace_id)}

    @staticmethod
    def _latest_file(directory: Path, pattern: str) -> Path | None:
        paths = list(directory.glob(pattern)) if directory.exists() else []
        return max(paths, key=lambda item: item.stat().st_mtime) if paths else None

    @staticmethod
    def _matches_by_job(run: MatchRun | None) -> dict[UUID, MatchResult]:
        return {item.job_id: item for item in run.results} if run else {}
