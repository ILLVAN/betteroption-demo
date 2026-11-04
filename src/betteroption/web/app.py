"""FastAPI delivery adapter for account-owned personas and application workflows."""

from __future__ import annotations

import csv
import ipaddress
import logging
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from .. import __version__
from ..accounts import (
    USERNAME_MAX_LENGTH,
    Account,
    AccountAccessTier,
    AccountError,
    AccountRole,
    RegistrationMode,
    normalize_email,
)
from ..application_guidance import (
    ApplicationChannel,
    ApplicationGuidance,
    ApplicationGuidanceField,
    extract_application_guidance,
    merge_application_guidance,
)
from ..applications import (
    MAX_APPLICATION_DRAFT_LENGTH,
    MAX_APPLICATION_DRAFT_NAME_LENGTH,
    MAX_APPLICATION_DRAFTS_PER_JOB,
    ApplicationDraftError,
    ApplicationDraftService,
    DraftAction,
)
from ..background import (
    BackgroundTaskKind,
    BackgroundTaskPermanentError,
    BackgroundTaskStatus,
    BackgroundWorker,
    JobImportDestination,
)
from ..brave_search import brave_search_failure_guidance
from ..candidate_languages import (
    PROGRAMMING_LANGUAGES,
    SPOKEN_LANGUAGES,
    PracticalProficiency,
    is_language_editor_fact,
    profile_language_mentions,
    profile_language_selections,
)
from ..concurrency import cooperative_control
from ..container import ApplicationContainer
from ..cv import (
    MAX_CV_BYTES,
    MAX_CV_TEXT,
    canonical_cv_preview_text,
    extract_cv_text,
    sanitize_cv_text,
)
from ..cost_calibration import ProviderBillingPeriod
from ..dashboard import DashboardService
from ..discovery import (
    MAX_PORTAL_SEARCH_SCOPES,
    DiscoveryError,
    DiscoveryQuery,
    JobDiscoveryProvider,
    SourceReadiness,
    discovery_query_from_profile,
    provider_attributions,
    web_discovery_matches_portal,
)
from ..discovery_sources import DiscoverySourceMesh
from ..geography import OfflineGermanPostalCodeIndex, OfflinePlaceIndex
from ..feedback import (
    MAX_FEEDBACK_MESSAGE_LENGTH,
    FeedbackCategory,
    FeedbackStatus,
    FeedbackSurface,
    ProductFeedbackError,
)
from ..job_corpus import JobCorpusError, JobCorpusService, JobImportResult
from ..job_context import EmployerContextService, EmployerKind, source_guidance
from ..employer_reputation import (
    EmployerReputationError,
    normalize_employer_name,
    resolved_employer_name,
)
from ..job_ratings import PersonaJobRatingError
from ..job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    ReasonOverrideValue,
    SkillOverrideValue,
)
from ..job_posters import EmployerPostingStatus, JobPosterAccessStatus, JobPosterError
from ..job_repository import JobAvailability, JobObservationKind, normalize_job_url
from ..jobs import JobSourceType
from ..llm import ApplicationDrafterPort, JobExtractorPort, ProfileExtractorPort
from ..matching import (
    CONTEXT_COMPANY_CATEGORIES,
    CONTEXT_COMPANY_NAME,
    CONTEXT_COMPANY_REVENUE_MODEL,
    CONTEXT_COMPANY_SUMMARY,
    CONTEXT_EMPLOYER_TYPES,
    CONTEXT_EMPLOYER_RELATIONSHIP,
    CONTEXT_REPUTATION_SUMMARY,
    CONTEXT_SALARY_RANGE,
    CONTEXT_WORK_MODE_PREFIX,
    MatchDisposition,
    skill_is_evidenced_by_profile,
)
from ..mobility import NominatimPlaceResolver, TravelTimeProvider
from ..operations import provider_operation_scope
from ..personas import PERSONA_NAME_MAX_LENGTH, AccountPersona, PersonaError
from ..portal_sources import PortalSourceError
from ..profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    ReviewAction,
    SUPPORTED_COMPENSATION_CURRENCIES,
    SourceExcerpt,
)
from ..profile_integrity import CompassAction, inspect_compass_integrity
from ..profile_mobility import (
    mobility_widget_preferences,
    origin_precision_from_label,
)
from ..profile_workflow import (
    ProfileWorkflowError,
    ProfileWorkflowService,
    pending_reference_learning_ids,
    workspace_stage,
)
from ..presentation import (
    commute_visual_state,
    format_duration_minutes,
    format_job_location,
    job_is_remote_only,
)
from ..result_repository import ApplicationState, FeedbackState
from ..results import RatingProjection, ResultAccessError, ResultService, ResultServiceError
from ..provider_permissions import (
    ProviderPermissionError,
    account_provider_permission_scope,
)
from ..session import (
    CORE_SECTION_DEFINITIONS,
    SessionState,
    definition_for,
    next_clarification_section,
    next_pending_section,
    next_review_section,
    progress_for,
)
from ..url_ingestion import PublicUrlFetcher


logger = logging.getLogger(__name__)


EMPLOYER_TYPE_OPTIONS = (
    ("producer_manufacturer", "Producer / manufacturer"),
    ("product_company", "Product company"),
    ("consultancy", "Consultancy"),
    ("professional_services", "Professional services"),
    ("staffing_recruiting", "Staffing / recruiting"),
    ("platform_marketplace", "Platform / marketplace"),
    ("healthcare_provider", "Healthcare provider"),
    ("education_research", "Education / research"),
    ("public_sector", "Public sector"),
    ("non_profit", "Non-profit"),
    ("association", "Association"),
    ("startup_scaleup", "Start-up / scale-up"),
    ("retail_hospitality", "Retail / hospitality"),
    ("logistics_transport", "Logistics / transport"),
    ("financial_services", "Financial services"),
    ("other", "Other"),
)

EXPLORE_PROVIDER_LABELS = {
    "betteroption-posted": "Own",
    "arbeitnow": "Arbeitnow",
    "brave-web": "Brave Search",
    "you-web": "You.com Search",
    "exa-fallback": "Exa",
    "openwebninja-jsearch": "OpenWebNinja JSearch",
    "apify-eures": "EURES via Apify",
    "apify-jobspipe": "JobsPipe via Apify",
    "apify-all-jobs": "All Jobs via Apify",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
}

# Discovery adapters retain these tags as source metadata. Explore presents the
# provider once, in a quiet badge, instead of repeating transport details as if
# they described the vacancy itself.
EXPLORE_HIDDEN_SOURCE_TAGS = frozenset(
    {
        "Web discovery",
        "Semantic web fallback",
        "Source verification required",
        "All Jobs Scraper",
        "JobsPipe",
        "EURES",
        "JSearch",
    }
)


PACKAGE_DIRECTORY = Path(__file__).resolve().parent

FEEDBACK_LABELS = {
    FeedbackState.INTERESTED: "Interesting",
    FeedbackState.NOT_RELEVANT: "Not relevant",
    FeedbackState.TOO_MUCH_CONSULTING: "Responsibilities do not fit",
    FeedbackState.TOO_LITTLE_DEVELOPMENT: "Day-to-day work does not fit",
    FeedbackState.TOO_SENIOR: "Level or scope does not fit",
    FeedbackState.CONTEXT_MISMATCH: "Company or work context does not fit",
}

APPLICATION_LABELS = {
    ApplicationState.DISCOVERED: "Discovered",
    ApplicationState.MATCHED: "Matched",
    ApplicationState.SAVED: "Shortlisted",
    ApplicationState.PREPARING: "Preparing",
    ApplicationState.APPLIED: "Applied",
    ApplicationState.INTERVIEW: "Interview",
    ApplicationState.REJECTED: "Rejected",
    ApplicationState.OFFER: "Offer",
    ApplicationState.WITHDRAWN: "Withdrawn",
}

REFERENCE_LEARNING_SCOPES = {"role", "skills", "culture", "location", "work_model", "pay"}
MANUAL_ADD_RECOVERY_COPY = (
    "Automatic import needs the public advertisement text for this source. "
    "Paste the complete job advertisement below; the source link stays attached."
)
AUTH_COOKIE = "betteroption_session"
_CURRENT_ACCOUNT: ContextVar[Account | None] = ContextVar(
    "betteroption_current_account",
    default=None,
)
_CURRENT_PERSONA_ID: ContextVar[UUID | None] = ContextVar(
    "betteroption_current_persona_id",
    default=None,
)


def _redirect(
    path: str,
    *,
    notice: str | None = None,
    error: str | None = None,
    fragment: str | None = None,
):
    parameters = {key: value for key, value in {"notice": notice, "error": error}.items() if value}
    separator = "&" if "?" in path else "?"
    destination = f"{path}{separator}{urlencode(parameters)}" if parameters else path
    if fragment:
        destination = f"{destination}#{quote(fragment, safe='-')}"
    return RedirectResponse(destination, status_code=303)


def create_app(
    container: ApplicationContainer | None = None,
    *,
    data_directory: Path = Path("local-data"),
    profile_extractor: ProfileExtractorPort | None = None,
    reference_fetcher: PublicUrlFetcher | None = None,
    job_extractor: JobExtractorPort | None = None,
    job_fetcher: PublicUrlFetcher | None = None,
    travel_time_provider: TravelTimeProvider | None = None,
    discovery_provider: JobDiscoveryProvider | None = None,
    application_drafter: ApplicationDrafterPort | None = None,
) -> FastAPI:
    container = container or ApplicationContainer()
    container.workspaces.adopt_latest_file(data_directory / "sessions")
    dashboard = DashboardService(
        container.repository,
        workspaces=container.workspaces,
        results=container.results,
        data_directory=data_directory,
    )
    templates = Jinja2Templates(directory=str(PACKAGE_DIRECTORY / "templates"))
    templates.env.globals["app_version"] = __version__
    templates.env.filters["duration"] = format_duration_minutes
    templates.env.filters["commute_state"] = commute_visual_state
    templates.env.filters["job_location"] = format_job_location
    templates.env.filters["remote_only"] = job_is_remote_only
    discovery = discovery_provider or container.job_discovery_provider()
    mobility = container.mobility_service(travel_time_provider)
    employer_context = EmployerContextService(
        fetcher=job_fetcher,
        research_homepages=container.settings.employer_homepage_research,
        company_research_provider=container.company_research_provider(),
    )
    salary_benchmark = container.salary_benchmark_provider()
    compass_place_index = OfflinePlaceIndex()
    compass_postal_index = OfflineGermanPostalCodeIndex()
    compass_place_resolver = (
        NominatimPlaceResolver(
            base_url=container.settings.osm_geocoder_base_url,
            user_agent=container.settings.osm_geocoder_user_agent,
            timeout_seconds=4.0,
        )
        if container.settings.osm_geocoder_enabled
        else None
    )

    # This remains as a compatibility fallback for tests and installations that
    # deliberately disable the worker. Normal private-alpha Explore searches
    # use the durable repository below.
    explore_snapshot: dict[str, object] | None = None

    def current_account() -> Account | None:
        return _CURRENT_ACCOUNT.get()

    def account_id() -> UUID | None:
        account = current_account()
        return account.id if account else None

    def active_persona_id() -> UUID | None:
        return _CURRENT_PERSONA_ID.get()

    def current_persona() -> AccountPersona | None:
        account = current_account()
        selected_persona_id = active_persona_id()
        if account is None or selected_persona_id is None:
            return None
        return container.personas.get(selected_persona_id, account_id=account.id)

    def current_job_ratings():
        """Return the active persona's private job judgements keyed by job id."""

        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            return {}
        try:
            return {
                rating.job_record_id: rating
                for rating in container.job_ratings.list_for_persona(
                    persona.id,
                    account_id=account.id,
                )
            }
        except PersonaJobRatingError:
            return {}

    def effective_employer_name(record_id: UUID, source_name: str) -> str | None:
        workspace = latest_workspace()
        if workspace is None:
            return resolved_employer_name(source_name)
        overrides = container.job_overrides.list_for_job(workspace.id, record_id)
        corrected = next(
            (
                override.text_value
                for override in overrides
                if override.kind == JobEvidenceOverrideKind.CONTEXT
                and override.target_key == CONTEXT_COMPANY_NAME
                and override.text_value
            ),
            source_name,
        )
        return resolved_employer_name(corrected)

    def current_employer_ratings_by_record(opportunities) -> tuple[dict, dict]:
        """Resolve private company ratings without ever combining placeholder employers."""

        account = current_account()
        persona = current_persona()
        ratings_by_record = {}
        available_by_record = {}
        if account is None or persona is None:
            return ratings_by_record, available_by_record
        ratings = {
            rating.employer_key: rating
            for rating in container.employer_reputation.list_for_persona(
                persona.id,
                account_id=account.id,
            )
        }
        for opportunity in opportunities:
            record_id = opportunity.record_id
            employer_name = effective_employer_name(record_id, opportunity.company)
            available_by_record[record_id] = employer_name is not None
            if employer_name is None:
                continue
            try:
                _, employer_key = normalize_employer_name(employer_name)
            except EmployerReputationError:
                continue
            if employer_key in ratings:
                ratings_by_record[record_id] = ratings[employer_key]
        return ratings_by_record, available_by_record

    def current_employer_names_by_record(opportunities) -> dict[UUID, str]:
        return {
            opportunity.record_id: name
            for opportunity in opportunities
            if (name := effective_employer_name(opportunity.record_id, opportunity.company))
            is not None
        }

    def current_employer_keys_by_record(opportunities) -> dict[UUID, str]:
        keys: dict[UUID, str] = {}
        for opportunity in opportunities:
            employer_name = effective_employer_name(
                opportunity.record_id,
                opportunity.company,
            )
            if employer_name is None:
                continue
            try:
                _, employer_key = normalize_employer_name(employer_name)
            except EmployerReputationError:
                continue
            keys[opportunity.record_id] = employer_key
        return keys

    def persona_feature_enabled(request: Request) -> bool:
        if container.settings.auth_mode != "accounts":
            return False
        if container.settings.account_personas_enabled:
            return True
        if not container.settings.local_personas_enabled or request.client is None:
            return False
        try:
            return ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            return False

    def latest_workspace():
        if container.settings.auth_mode != "accounts":
            return container.workspaces.latest()
        selected_persona_id = active_persona_id()
        if selected_persona_id is None:
            return None
        return container.workspaces.latest(
            account_id=account_id(),
            persona_id=selected_persona_id,
        )

    def owned_workspace(workspace_id: UUID):
        if container.settings.auth_mode != "accounts":
            return container.workspaces.get(workspace_id)
        selected_persona_id = active_persona_id()
        if selected_persona_id is None:
            return None
        return container.workspaces.get(
            workspace_id,
            account_id=account_id(),
            persona_id=selected_persona_id,
        )

    def compass_action_error(workspace, action: CompassAction) -> str | None:
        report = inspect_compass_integrity(workspace.session if workspace is not None else None)
        reason = report.blocked_reason(action)
        if reason is None:
            return None
        return f"Review the Compass point shown on this page first. {reason}"

    def normalize_compass_origin(value: str) -> str:
        """Normalize a deliberately chosen public point without storing coordinates."""

        clean = " ".join(value.split())[:200]
        if not clean:
            return ""
        postal = compass_postal_index.resolve(clean)
        if postal is not None:
            return f"{postal.label}, {postal.country_code}"[:200]
        if origin_precision_from_label(clean) == "address" and compass_place_resolver is not None:
            resolved = compass_place_resolver.resolve(clean)
            if resolved is not None:
                return " ".join(resolved.label.split())[:200]
        city = compass_place_index.resolve(clean)
        if city is not None:
            country_suffix = f", {city.country_code}"
            if not clean.casefold().endswith(city.country_code.casefold()):
                return f"{clean}{country_suffix}"[:200]
        return clean

    def account_workspaces():
        if container.settings.auth_mode != "accounts":
            return container.workspaces.list_all()
        selected_persona_id = active_persona_id()
        if selected_persona_id is None:
            return []
        return container.workspaces.list_all(
            account_id=account_id(),
            persona_id=selected_persona_id,
        )

    def dashboard_for_current() -> DashboardService:
        workspace = latest_workspace()
        if container.settings.auth_mode == "local":
            return dashboard
        return DashboardService(
            container.repository,
            workspaces=container.workspaces,
            results=container.results,
            data_directory=data_directory,
            workspace_id=workspace.id if workspace else None,
            restrict_to_workspace=True,
        )

    def smart_home_action(snapshot, workspace):
        """Choose one useful next step without turning Home into a warning wall."""

        if workspace is None:
            return {
                "eyebrow": "Start with what matters",
                "title": "Build your first Compass.",
                "copy": "A short guided setup gives every later search and match its direction.",
                "progress_label": None,
                "primary_url": "/profile",
                "primary_label": "Start guided setup",
                "secondary_url": None,
                "secondary_label": None,
            }
        if snapshot.profile.confirmed_facts == 0:
            return {
                "eyebrow": "Your next useful step",
                "title": "Give your Compass a direction.",
                "copy": "Add the first confirmed signal before searching for roles.",
                "progress_label": (
                    f"{snapshot.profile.completed_sections}/{snapshot.profile.total_sections} "
                    "sections visited"
                ),
                "primary_url": f"/profile/{workspace.id}/guided",
                "primary_label": "Continue guided setup",
                "secondary_url": f"/profile/{workspace.id}",
                "secondary_label": "Edit Compass",
            }

        job_count = len(snapshot.opportunities)
        if job_count < 4:
            return {
                "eyebrow": "Widen the field",
                "title": "Bring a few roles into view.",
                "copy": "Add a role you already know or explore from your confirmed Compass.",
                "progress_label": f"{job_count}/4 roles ready for a useful comparison",
                "primary_url": "/explore",
                "primary_label": "Explore roles",
                "secondary_url": "/add",
                "secondary_label": "Add a role",
            }

        groups = result_service().latest(workspace)
        if groups is None or not groups.profile_is_current or not groups.algorithm_is_current:
            return {
                "eyebrow": "Ready to compare",
                "title": "Match these roles to your current Compass.",
                "copy": "Your saved roles are ready for a fresh, evidence-backed comparison.",
                "progress_label": f"{job_count} roles available",
                "primary_url": "/matches",
                "primary_label": "Run matching",
                "secondary_url": "/explore",
                "secondary_label": "Explore more",
            }

        draft_count = sum(container.application_drafts.counts_for_workspace(workspace.id).values())
        if draft_count == 0:
            return {
                "eyebrow": "Turn fit into action",
                "title": "Prepare your first application draft.",
                "copy": "Choose a strong match and create an editable cover letter—nothing is sent.",
                "progress_label": f"{len(groups.top)} strong · {len(groups.stretch)} worth a look",
                "primary_url": "/apply",
                "primary_label": "Prepare an application",
                "secondary_url": "/matches",
                "secondary_label": "Review matches",
            }
        return {
            "eyebrow": "Keep your search moving",
            "title": "Continue with your application workspace.",
            "copy": "Review saved drafts, then decide which opportunity deserves your attention.",
            "progress_label": f"{draft_count} draft{'s' if draft_count != 1 else ''} saved",
            "primary_url": "/apply",
            "primary_label": "Open Apply",
            "secondary_url": "/explore",
            "secondary_label": "Explore more",
        }

    def accessible_record_ids() -> set[UUID] | None:
        if container.settings.auth_mode == "local":
            return None
        workspace = latest_workspace()
        if workspace is None:
            return set()
        return {grant.job_record_id for grant in container.results.access_grants(workspace.id)}

    def accessible_records():
        allowed = accessible_record_ids()
        records = container.repository.list_records()
        return records if allowed is None else [row for row in records if row.id in allowed]

    def stored_count() -> int:
        return len(accessible_records())

    def grant_record(record_id: UUID) -> None:
        if container.settings.auth_mode == "local":
            return
        workspace = latest_workspace()
        if workspace is None:
            raise JobCorpusError("Create your Compass before saving a job.")
        container.results.grant_job(workspace.id, record_id)

    def workflow(*, require_extractor: bool = False) -> ProfileWorkflowService:
        extractor = profile_extractor
        extractor_setup_error: Exception | None = None
        if require_extractor and extractor is None:
            try:
                extractor = container.profile_extractor()
            except Exception as exc:
                # The workflow can still durably save ordinary Compass text.
                # The service converts this to a secret-safe actionable warning.
                extractor_setup_error = exc
        return ProfileWorkflowService(
            container.workspaces,
            extractor=extractor,
            extractor_setup_error=extractor_setup_error,
            fetcher=reference_fetcher,
            account_id=account_id(),
            persona_id=active_persona_id(),
        )

    def corpus() -> JobCorpusService:
        return JobCorpusService(
            container.repository,
            fetcher=job_fetcher,
            extractor=job_extractor,
            extractor_factory=None if job_extractor else container.job_extractor,
            source_snapshot_directory=data_directory / "source-snapshots",
            canonical_job_directory=data_directory / "jobs",
        )

    def delete_job_records(record_ids: list[UUID]) -> int:
        """Delete complete job aggregates and remove linked reference settings."""

        records = {record.id: record for record in accessible_records()}
        deleted = 0
        for record_id in dict.fromkeys(record_ids):
            record = records.get(record_id)
            if record is None:
                continue
            urls = [record.canonical_url]
            current_job = container.repository.get_current_job(record_id)
            if current_job is not None:
                urls.extend(
                    str(url)
                    for url in (current_job.requested_url, current_job.source_url)
                    if url is not None
                )
            for profile_workspace in account_workspaces():
                workflow().delete_references_for_urls(profile_workspace.id, urls)
            if container.settings.auth_mode == "accounts":
                revoked = False
                for profile_workspace in account_workspaces():
                    revoked = (
                        container.results.revoke_job(profile_workspace.id, record_id) or revoked
                    )
                if not revoked:
                    continue
            elif not corpus().delete_record(record_id):
                continue
            deleted += 1
        return deleted

    def stored_record_for_reference(reference) -> UUID | None:
        identities = {
            normalize_job_url(str(url))
            for url in (reference.url, reference.resolved_url)
            if url is not None
        }
        for record in accessible_records():
            record_urls = {normalize_job_url(record.canonical_url)}
            current_job = container.repository.get_current_job(record.id)
            if current_job is not None:
                record_urls.update(
                    normalize_job_url(str(url))
                    for url in (current_job.requested_url, current_job.source_url)
                    if url is not None
                )
            if identities.intersection(record_urls):
                return record.id
        return None

    def result_service() -> ResultService:
        match_evidence_resolver = None
        if container.settings.openai_api_key_value:
            try:
                match_evidence_resolver = container.match_evidence_resolver()
            except Exception:
                # Semantic evidence resolution is optional. Deterministic
                # Matching and stored-evidence quickscore must remain usable
                # when its provider or reviewed-processor setup is unavailable.
                match_evidence_resolver = None
        return ResultService(
            container.repository,
            corpus(),
            container.results,
            container.access_policy,
            mobility=mobility,
            employer_context=employer_context,
            operation_ledger=container.operations,
            salary_benchmark=salary_benchmark,
            salary_research_max_jobs=container.settings.salary_research_max_jobs,
            job_overrides=container.job_overrides,
            employer_reputation=container.employer_reputation,
            job_ratings=container.job_ratings,
            match_evidence_resolver=match_evidence_resolver,
            restrict_to_grants=container.settings.auth_mode == "accounts",
        )

    def application_service() -> ApplicationDraftService:
        drafter = application_drafter
        if drafter is None:
            try:
                drafter = container.application_drafter()
            except Exception as exc:
                raise ApplicationDraftError(
                    "Cover-letter generation is unavailable. Check OPENAI_API_KEY, the configured "
                    "model, and the processor-readiness setting."
                ) from exc
        return ApplicationDraftService(
            container.application_drafts,
            drafter,
            container.application_guidance,
        )

    def current_application_match(workspace, record_id: UUID):
        try:
            detail = result_service().latest_detail(workspace, record_id)
        except ResultAccessError as exc:
            raise ApplicationDraftError(str(exc)) from exc
        if detail is None:
            raise ApplicationDraftError(
                "That job is not part of the active persona’s latest Match run."
            )
        if detail.item.stored.result.disposition.value == "blocked":
            raise ApplicationDraftError(
                "Blocked jobs are excluded from cover-letter generation. Review the boundary first."
            )
        if not detail.item.accessible:
            raise ApplicationDraftError("That job is no longer accessible to the active persona.")
        if not detail.item.source_is_current:
            raise ApplicationDraftError(
                "The job source changed or closed. Refresh it and run Match again first."
            )
        return detail

    def run_match_background(task, report) -> str:
        workspace = container.workspaces.get(task.workspace_id)
        if workspace is None:
            raise BackgroundTaskPermanentError(
                "The Compass for this workflow no longer exists. Start Matching again."
            )
        if integrity_error := compass_action_error(workspace, CompassAction.MATCH):
            raise BackgroundTaskPermanentError(integrity_error)
        try:
            groups = result_service().run(
                workspace,
                workflow_id=task.id,
                progress=report,
                task_attempt=task.attempt,
                task_claim_token=task.claim_token,
            )
        except (KeyError, ResultServiceError, ValueError) as exc:
            raise BackgroundTaskPermanentError(str(exc)) from exc
        notice = (
            f"Your match run is ready: {len(groups.top)} Top, "
            f"{len(groups.stretch)} Stretch, and {len(groups.blocked)} Blocked."
        )
        return f"/matches?{urlencode({'notice': notice})}"

    def run_single_job_match_background(task, report) -> str:
        workspace = container.workspaces.get(task.workspace_id)
        request_payload = container.background_single_job_matches.get(task.id)
        if workspace is None or request_payload is None:
            raise BackgroundTaskPermanentError(
                "This saved single-job Match request is no longer available."
            )
        if integrity_error := compass_action_error(workspace, CompassAction.MATCH):
            raise BackgroundTaskPermanentError(integrity_error)
        previous_run = container.results.latest_run(workspace.id)
        was_previously_matched = bool(
            previous_run
            and any(
                item.job_record_id == request_payload.job_record_id for item in previous_run.results
            )
        )
        try:
            result_service().run(
                workspace,
                workflow_id=task.id,
                progress=report,
                record_ids={request_payload.job_record_id},
                task_attempt=task.attempt,
                task_claim_token=task.claim_token,
            )
        except (KeyError, ResultServiceError, ValueError) as exc:
            raise BackgroundTaskPermanentError(str(exc)) from exc
        notice = (
            "This job was rematched; your other saved match results were kept."
            if was_previously_matched
            else "This job was matched without running the full corpus."
        )
        return (
            f"/jobs/{request_payload.job_record_id}?{urlencode({'notice': notice})}"
            "#evidence-heading"
        )

    def run_explore_background(task, report) -> str:
        search = container.explore_searches.get(task.id)
        if search is None:
            raise RuntimeError("The stored Explore request is not ready yet.")
        if search.completed_at is not None:
            return "/explore"
        report(
            "searching_sources",
            0,
            2,
            "Searching public feeds and employer job boards.",
        )

        def save_preview(_stage: str, preview_results: list) -> None:
            try:
                container.explore_searches.update_preview(
                    task.id,
                    results=preview_results,
                    expected_task_attempt=task.attempt,
                    task_claim_token=task.claim_token,
                )
            except Exception:
                # Preview persistence is optional presentation. Worker control
                # exceptions from report() below must still propagate.
                pass
            report(
                "ranking_preview",
                0,
                2,
                (
                    f"Ranking {len(preview_results)} current leader"
                    f"{'s' if len(preview_results) != 1 else ''} as new source evidence arrives."
                ),
            )

        try:
            with provider_operation_scope(task.id, "explore-search"):
                if isinstance(discovery, DiscoverySourceMesh):
                    results = discovery.search(
                        search.query,
                        on_preview=save_preview,
                        check_control=getattr(report, "checkpoint", None),
                    )
                else:
                    results = discovery.search(search.query)
                    save_preview(
                        "sources_ranked",
                        results[: container.settings.explore_preview_limit],
                    )
        except (DiscoveryError, RuntimeError, ValueError) as exc:
            raise BackgroundTaskPermanentError(str(exc)) from exc
        report(
            "saving_results",
            1,
            2,
            f"Saving {len(results)} ranked public discoveries.",
        )
        container.explore_searches.complete(
            task.id,
            results=results,
            regional_result_count=getattr(discovery, "last_regional_count", 0),
            expected_task_attempt=task.attempt,
            task_claim_token=task.claim_token,
        )
        report(
            "complete",
            2,
            2,
            f"{len(results)} public discoveries are ready.",
        )
        return "/explore"

    def run_import_background(task, report) -> str:
        batch = container.background_job_imports.get(task.id)
        workspace = container.workspaces.get(task.workspace_id)
        if workspace is None or batch is None:
            raise BackgroundTaskPermanentError(
                "The stored Explore selection is no longer available. Select the jobs again."
            )

        destination = batch.destination
        origin_search = None
        if batch.source_explore_task_id is not None:
            candidate = container.explore_searches.get(batch.source_explore_task_id)
            if candidate is not None and candidate.workspace_id == workspace.id:
                origin_search = candidate
        imported = 0
        failures: list[str] = []
        discarded_urls: set[str] = set()
        manual_required_urls: set[str] = set()
        total = len(batch.source_urls)
        existing_grants = {
            grant.job_record_id for grant in container.results.access_grants(workspace.id)
        }
        checkpoint = getattr(report, "checkpoint", lambda: None)

        def workspace_stored_count() -> int:
            if container.settings.auth_mode == "accounts":
                return len(existing_grants)
            return container.repository.count_records()

        for position, url in enumerate(batch.source_urls, start=1):
            report(
                "verifying_sources",
                position - 1,
                total,
                f"Verifying and extracting job source {position} of {total}.",
            )
            try:
                existing = container.repository.find_by_urls(url, url)
                already_available = existing is not None and (
                    container.settings.auth_mode == "local" or existing.id in existing_grants
                )
                if (
                    not already_available
                    and workspace_stored_count() >= container.access_policy.max_stored_jobs
                ):
                    raise JobCorpusError("The selected jobs exceed the available Archive slots.")

                with provider_operation_scope(task.id, "job-import"):
                    result = corpus().import_url(
                        url,
                        check_control=checkpoint,
                        commit_task_id=task.id,
                        expected_task_attempt=task.attempt,
                        task_claim_token=task.claim_token,
                    )
                checkpoint()
                if result.job is not None and result.kind not in {
                    JobObservationKind.EXPIRED,
                    JobObservationKind.UNREACHABLE,
                    JobObservationKind.EXTRACTION_FAILED,
                }:
                    if result.record is not None:
                        if container.settings.auth_mode == "accounts":
                            container.results.grant_job(
                                workspace.id,
                                result.record.id,
                                commit_task_id=task.id,
                                expected_task_attempt=task.attempt,
                                task_claim_token=task.claim_token,
                            )
                            existing_grants.add(result.record.id)
                    imported += 1
                else:
                    failures.append(
                        result.message or "A selected URL was closed or not a usable live job."
                    )
                    normalized_url = normalize_job_url(url)
                    if result.kind == JobObservationKind.EXPIRED:
                        discarded_urls.add(normalized_url)
                        if result.record is not None and container.settings.auth_mode == "local":
                            corpus().delete_record(
                                result.record.id,
                                commit_task_id=task.id,
                                expected_task_attempt=task.attempt,
                                task_claim_token=task.claim_token,
                            )
                    elif (
                        result.kind
                        in {
                            JobObservationKind.UNREACHABLE,
                            JobObservationKind.EXTRACTION_FAILED,
                        }
                        or result.manual_input_recommended
                    ):
                        manual_required_urls.add(normalized_url)
                    # Keep recoverable discovery evidence in the Explore
                    # snapshot, but do not let a failed local import consume an
                    # Archive slot or poison a later retry of the same URL.
                    if (
                        result.record is not None
                        and container.settings.auth_mode == "local"
                        and result.kind != JobObservationKind.EXPIRED
                    ):
                        corpus().delete_record(
                            result.record.id,
                            commit_task_id=task.id,
                            expected_task_attempt=task.attempt,
                            task_claim_token=task.claim_token,
                        )
            except (JobCorpusError, RuntimeError, ValueError) as exc:
                failures.append(str(exc))
            report(
                "verifying_sources",
                position,
                total,
                f"Checked {position} of {total} selected job sources.",
            )

        if discarded_urls:
            if origin_search is not None:
                container.explore_searches.remove_result_urls(
                    origin_search.task_id,
                    discarded_urls,
                    commit_task_id=task.id,
                    expected_task_attempt=task.attempt,
                    task_claim_token=task.claim_token,
                )
        if manual_required_urls:
            if origin_search is not None:
                container.explore_searches.update_result_readiness(
                    origin_search.task_id,
                    manual_required_urls,
                    readiness=SourceReadiness.MANUAL_REQUIRED,
                    commit_task_id=task.id,
                    expected_task_attempt=task.attempt,
                    task_claim_token=task.claim_token,
                )
        if imported == 0:
            detail = failures[0] if failures else "No selected job could be imported."
            if len(batch.source_urls) == 1 and manual_required_urls:
                return (
                    "/add?"
                    + urlencode({"url": batch.source_urls[0], "manual": "true"})
                    + "#manual-job-input"
                )
            parameters = {
                "error": (
                    "Nothing was saved or matched because the selected source is not "
                    f"currently usable. {detail}"
                )
            }
            if origin_search is not None:
                parameters["source_explore_task_id"] = str(origin_search.task_id)
            return "/explore?" + urlencode(parameters)

        if destination == JobImportDestination.MATCHING:
            integrity_error = compass_action_error(workspace, CompassAction.MATCH)
            if integrity_error:
                return "/matches?" + urlencode(
                    {"error": (f"{imported} selected job(s) were saved. {integrity_error}")}
                )
            # A running match may already have taken its corpus snapshot. This
            # import therefore owns a fresh run, but its deterministic id makes
            # a retry after import/pre-success failure reuse the same child.
            match_task_id = uuid5(
                NAMESPACE_URL,
                f"betteroption:job-import:{task.id}:match",
            )
            match_task = container.background_tasks.get(match_task_id)
            if match_task is None:
                match_task = container.background_tasks.create(
                    workspace.id,
                    BackgroundTaskKind.MATCH_RUN,
                    max_attempts=container.settings.background_task_max_attempts,
                    task_id=match_task_id,
                    commit_task_id=task.id,
                    expected_task_attempt=task.attempt,
                    task_claim_token=task.claim_token,
                )
            elif (
                match_task.workspace_id != workspace.id
                or match_task.kind != BackgroundTaskKind.MATCH_RUN
            ):
                raise BackgroundTaskPermanentError(
                    "The stored follow-up workflow is inconsistent with this import."
                )
            background_worker.wake()
            return f"/tasks/{match_task.id}"

        notice = f"{imported} selected job(s) saved to Archive."
        if failures:
            notice += f" {len(failures)} selection(s) need another source or check."
        return f"/jobs?{urlencode({'notice': notice})}"

    def scoped_background(handler):
        """Restore the owning account's provider boundary inside worker threads."""

        def run_scoped(task, report):
            workspace = container.workspaces.get(task.workspace_id)
            owner_id = workspace.account_id if workspace is not None else None
            checkpoint = getattr(report, "checkpoint", None)
            with (
                account_provider_permission_scope(
                    container.provider_permissions,
                    owner_id,
                ),
                cooperative_control(checkpoint if callable(checkpoint) else None),
            ):
                return handler(task, report)

        return run_scoped

    background_worker = BackgroundWorker(
        container.background_tasks,
        {
            BackgroundTaskKind.MATCH_RUN: scoped_background(run_match_background),
            BackgroundTaskKind.SINGLE_JOB_MATCH: scoped_background(run_single_job_match_background),
            BackgroundTaskKind.EXPLORE_SEARCH: scoped_background(run_explore_background),
            BackgroundTaskKind.JOB_IMPORT: scoped_background(run_import_background),
        },
        # Keep private source URLs across retryable attempts, then sweep them
        # after success, final failure, or cancellation. The sweep also resumes
        # idempotently after a cleanup-time process or database failure.
        maintenance_handlers=(lambda: container.background_job_imports.delete_terminal(),),
        poll_interval_seconds=container.settings.background_worker_poll_seconds,
        retry_base_seconds=container.settings.background_task_retry_seconds,
        lease_ttl_seconds=container.settings.background_task_lease_ttl_seconds,
        heartbeat_interval_seconds=container.settings.background_task_heartbeat_seconds,
    )
    background_queue_enabled = bool(
        container.settings.background_worker_enabled
        or container.settings.background_worker_external
    )

    def task_lease_fresh(task) -> bool:
        return bool(
            task.status == BackgroundTaskStatus.RUNNING
            and task.lease_expires_at is not None
            and task.lease_expires_at > datetime.now(timezone.utc)
        )

    def background_worker_available(task=None) -> bool:
        # The web process cannot inspect the external process directly. In
        # external mode the durable queue and worker service are the contract;
        # do not present the intentionally disabled embedded thread as dead.
        if task is not None and task.status == BackgroundTaskStatus.RUNNING:
            return task_lease_fresh(task)
        return background_worker.is_running or container.settings.background_worker_external

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if container.settings.background_worker_enabled:
            background_worker.start()
        try:
            yield
        finally:
            # The embedded worker exists only for the local app.  A local
            # Ctrl+C means stop that in-process work, not leave a task and its
            # provider threads alive behind an already closed Uvicorn app.
            background_worker.stop(cancel_running=True)

    app = FastAPI(
        title="WorkLifeBalance",
        version=__version__,
        description="A calm, evidence-backed home for your job search.",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.container = container
    app.state.dashboard = dashboard
    app.state.background_worker = background_worker
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_DIRECTORY / "static")),
        name="static",
    )

    @app.middleware("http")
    async def account_boundary(request: Request, call_next):
        if container.settings.auth_mode != "accounts":
            return await call_next(request)
        public_paths = {
            "/invite",
            "/login",
            "/recover",
            "/register",
            "/health",
            "/health/live",
            "/health/ready",
            "/legal/privacy",
            "/legal/terms",
            "/legal/imprint",
            "/legal/ai",
            "/legal/storage",
        }
        is_public = (
            request.url.path in public_paths
            or request.url.path.startswith("/static/")
            or request.url.path.startswith("/published-jobs/")
        )
        token = request.cookies.get(AUTH_COOKIE)
        account = container.accounts.resolve_session(token)
        if account is None and not is_public:
            if request.url.path.startswith("/api/") or "application/json" in request.headers.get(
                "accept", ""
            ):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            next_path = request.url.path
            if request.url.query:
                next_path += f"?{request.url.query}"
            return RedirectResponse(
                f"/login?{urlencode({'next': next_path})}",
                status_code=303,
            )
        expected_origin = container.settings.public_base_url.rstrip("/") or str(
            request.base_url
        ).rstrip("/")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied_origin = request.headers.get("origin")
            if not supplied_origin:
                referer = request.headers.get("referer")
                if referer:
                    parsed_referer = urlsplit(referer)
                    if parsed_referer.scheme and parsed_referer.netloc:
                        supplied_origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            supplied_origin = supplied_origin.rstrip("/") if supplied_origin else None
            if supplied_origin != expected_origin and (
                supplied_origin is not None or container.settings.app_environment != "local"
            ):
                return PlainTextResponse("Cross-site request rejected.", status_code=403)
        active_persona_id = (
            container.accounts.session_persona_id(token, account_id=account.id)
            if account is not None
            else None
        )
        if account is not None and active_persona_id is None:
            fallback_persona = container.personas.ensure_main(
                account.id,
                maximum_personas=container.settings.persona_limit,
            )
            container.accounts.set_session_persona(
                token,
                account_id=account.id,
                persona_id=fallback_persona.id,
            )
            active_persona_id = fallback_persona.id
        token_context = _CURRENT_ACCOUNT.set(account)
        persona_context_token = _CURRENT_PERSONA_ID.set(active_persona_id)
        try:
            with account_provider_permission_scope(
                container.provider_permissions,
                account.id if account is not None else None,
            ):
                return await call_next(request)
        finally:
            _CURRENT_PERSONA_ID.reset(persona_context_token)
            _CURRENT_ACCOUNT.reset(token_context)

    def safe_next_path(value: str | None, fallback: str = "/") -> str:
        if not value or not value.startswith("/") or value.startswith("//"):
            return fallback
        return value

    def auth_context(
        request: Request,
        *,
        error: str | None = None,
        next_path: str | None = None,
    ) -> dict:
        mode = RegistrationMode(container.settings.registration_mode)
        registration_available = mode == RegistrationMode.OPEN or (
            mode == RegistrationMode.FIRST_USER and container.accounts.count() == 0
        )
        return {
            "registration_available": registration_available,
            "invitation_only": mode == RegistrationMode.INVITE_ONLY,
            "next_path": safe_next_path(next_path or request.query_params.get("next")),
            "error": error,
            "notice": request.query_params.get("notice"),
            "auth_mode": container.settings.auth_mode,
            "personas_enabled": persona_feature_enabled(request),
            "local_personas_enabled": persona_feature_enabled(request),
            "current_account": current_account(),
            "active_page": None,
            "terms_version": container.settings.legal_terms_version,
            "privacy_version": container.settings.legal_privacy_version,
        }

    def auth_attempt_allowed(request: Request, action: str, subject: str) -> bool:
        """Apply a privacy-preserving auth limit to an address and client pair."""

        secret = container.settings.auth_rate_limit_secret.strip()
        if not secret:
            return container.settings.app_environment == "local"
        direct_client = request.client.host if request.client else "unknown-client"
        client = f"direct:{direct_client}"
        if container.settings.auth_trust_cloudflare_headers:
            candidate = request.headers.get("cf-connecting-ip", "").strip()
            try:
                client = f"cloudflare:{ipaddress.ip_address(candidate).compressed}"
            except ValueError:
                client = f"direct:{direct_client}"
        return container.accounts.allow_auth_attempt(
            action,
            f"{subject}|{client}",
            secret=secret,
            maximum=container.settings.auth_rate_limit_attempts,
            window=timedelta(minutes=container.settings.auth_rate_limit_minutes),
        )

    def set_auth_cookie(response: RedirectResponse, account: Account) -> None:
        container.personas.ensure_main(
            account.id,
            maximum_personas=container.settings.persona_limit,
        )
        session = container.accounts.create_session(
            account,
            ttl=timedelta(days=container.settings.auth_session_days),
        )
        response.set_cookie(
            AUTH_COOKIE,
            session.token,
            max_age=container.settings.auth_session_days * 86_400,
            httponly=True,
            secure=container.settings.auth_secure_cookie,
            samesite="strict",
            path="/",
        )

    def persona_context(
        request: Request,
        *,
        error: str | None = None,
    ) -> dict:
        account = current_account()
        personas = container.personas.list_for_account(account.id) if account else []
        return {
            "personas": personas,
            "persona_limit": container.settings.persona_limit,
            "error": error or request.query_params.get("error"),
            "notice": request.query_params.get("notice"),
            "auth_mode": container.settings.auth_mode,
            "personas_enabled": persona_feature_enabled(request),
            "local_personas_enabled": persona_feature_enabled(request),
            "current_account": account,
            "current_persona": current_persona(),
            "active_page": "personas",
        }

    def require_persona_mode(request: Request) -> Account:
        account = current_account()
        if account is None or not persona_feature_enabled(request):
            raise HTTPException(status_code=404, detail="Page not found")
        return account

    @app.get("/personas", response_class=HTMLResponse, name="personas")
    async def personas_page(request: Request):
        require_persona_mode(request)
        return templates.TemplateResponse(
            request=request,
            name="personas.html",
            context=persona_context(request),
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.post("/personas", response_class=HTMLResponse, name="persona_create")
    async def persona_create(
        request: Request,
        display_name: str = Form(max_length=PERSONA_NAME_MAX_LENGTH),
    ):
        account = require_persona_mode(request)
        try:
            persona = container.personas.create(
                account.id,
                name=display_name,
                maximum_personas=container.settings.persona_limit,
            )
        except PersonaError as exc:
            error = str(exc)
        else:
            container.accounts.set_session_persona(
                request.cookies.get(AUTH_COOKIE),
                account_id=account.id,
                persona_id=persona.id,
            )
            return _redirect("/", notice=f"Persona {display_name.strip()} is now active.")
        return templates.TemplateResponse(
            request=request,
            name="personas.html",
            context=persona_context(request, error=error),
            status_code=400,
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.post(
        "/personas/{persona_id}/switch",
        response_class=HTMLResponse,
        name="persona_switch",
    )
    async def persona_switch(
        request: Request,
        persona_id: UUID,
    ):
        account = require_persona_mode(request)
        try:
            persona = container.personas.get(persona_id, account_id=account.id)
            if persona is None:
                raise PersonaError("Persona not found.")
            container.accounts.set_session_persona(
                request.cookies.get(AUTH_COOKIE),
                account_id=account.id,
                persona_id=persona.id,
            )
        except (AccountError, PersonaError) as exc:
            error = str(exc)
        else:
            return _redirect("/", notice=f"Switched to {persona.name}.")
        return templates.TemplateResponse(
            request=request,
            name="personas.html",
            context=persona_context(request, error=error),
            status_code=400,
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.post("/personas/{persona_id}/rename", name="persona_rename")
    async def persona_rename(
        request: Request,
        persona_id: UUID,
        display_name: str = Form(max_length=PERSONA_NAME_MAX_LENGTH),
    ):
        account = require_persona_mode(request)
        try:
            persona = container.personas.rename(
                persona_id,
                display_name,
                account_id=account.id,
            )
        except PersonaError as exc:
            return _redirect("/personas", error=str(exc))
        return _redirect("/personas", notice=f"Persona renamed to {persona.name}.")

    @app.post("/personas/{persona_id}/delete", name="persona_delete")
    async def persona_delete(
        request: Request,
        persona_id: UUID,
        confirm_delete: bool = Form(default=False),
    ):
        account = require_persona_mode(request)
        if not confirm_delete:
            return _redirect("/personas", error="Confirm persona deletion first.")
        try:
            selected_persona_id = active_persona_id()
            replacement = container.personas.delete(
                persona_id,
                account_id=account.id,
            )
        except PersonaError as exc:
            return _redirect("/personas", error=str(exc))
        if selected_persona_id == persona_id and replacement is not None:
            container.accounts.set_session_persona(
                request.cookies.get(AUTH_COOKIE),
                account_id=account.id,
                persona_id=replacement.id,
            )
        return _redirect("/personas", notice="Persona and its private workspace were deleted.")

    @app.get("/login", response_class=HTMLResponse, name="login")
    async def login_page(request: Request):
        if container.settings.auth_mode != "accounts":
            return _redirect("/")
        if current_account() is not None:
            return _redirect("/")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=auth_context(request),
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        email: str = Form(max_length=320),
        password: str = Form(max_length=1_024),
        next_path: str = Form(default="/"),
    ):
        if not auth_attempt_allowed(request, "login", email):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=auth_context(
                    request,
                    error="Too many sign-in attempts. Wait before trying again.",
                    next_path=next_path,
                ),
                status_code=429,
                headers={"Cache-Control": "no-store"},
            )
        account = container.accounts.authenticate(email, password)
        if account is None:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=auth_context(
                    request,
                    error="The email address or password was not recognized.",
                    next_path=next_path,
                ),
                status_code=400,
            )
        response = RedirectResponse(safe_next_path(next_path), status_code=303)
        set_auth_cookie(response, account)
        return response

    @app.get("/register", response_class=HTMLResponse, name="register")
    async def register_page(request: Request):
        if container.settings.auth_mode != "accounts":
            return _redirect("/")
        context = auth_context(request)
        if not context["registration_available"]:
            return _redirect("/login", error="Registration is not currently open.")
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context=context,
        )

    @app.post("/register", response_class=HTMLResponse)
    async def register_submit(
        request: Request,
        email: str = Form(max_length=320),
        display_name: str = Form(max_length=USERNAME_MAX_LENGTH),
        password: str = Form(max_length=1_024),
        next_path: str = Form(default="/"),
        accept_terms: str | None = Form(default=None),
        acknowledge_privacy: str | None = Form(default=None),
        confirm_adult: str | None = Form(default=None),
    ):
        registration_mode = RegistrationMode(container.settings.registration_mode)
        if (
            container.settings.app_environment in {"staging", "production"}
            and registration_mode == RegistrationMode.FIRST_USER
        ):
            try:
                owner_email = normalize_email(email)
            except AccountError:
                owner_email = ""
            if owner_email not in container.settings.operator_email_set:
                return templates.TemplateResponse(
                    request=request,
                    name="register.html",
                    context=auth_context(
                        request,
                        error=(
                            "Owner bootstrap is restricted to the configured private-alpha "
                            "owner address."
                        ),
                        next_path=next_path,
                    ),
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
        if not accept_terms or not acknowledge_privacy or not confirm_adult:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context=auth_context(
                    request,
                    error=(
                        "Confirm you are at least 18, accept the current Terms, and "
                        "acknowledge the Privacy Notice before creating an account."
                    ),
                    next_path=next_path,
                ),
                status_code=400,
            )
        try:
            account = container.accounts.create(
                email,
                display_name,
                password,
                registration_mode=registration_mode,
            )
        except AccountError as exc:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context=auth_context(request, error=str(exc), next_path=next_path),
                status_code=400,
            )
        container.legal.record_current(account.id)
        response = RedirectResponse(safe_next_path(next_path), status_code=303)
        set_auth_cookie(response, account)
        return response

    @app.get("/invite", response_class=HTMLResponse, name="accept_invitation")
    async def invitation_page(request: Request):
        if container.settings.auth_mode != "accounts":
            return _redirect("/")
        if current_account() is not None:
            return _redirect("/")
        return templates.TemplateResponse(
            request=request,
            name="invitation_accept.html",
            context=auth_context(request),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post("/invite", response_class=HTMLResponse)
    async def invitation_submit(
        request: Request,
        token: str = Form(max_length=512),
        display_name: str = Form(max_length=USERNAME_MAX_LENGTH),
        password: str = Form(max_length=1_024),
        password_confirmation: str = Form(max_length=1_024),
        accept_terms: str | None = Form(default=None),
        acknowledge_privacy: str | None = Form(default=None),
        confirm_adult: str | None = Form(default=None),
    ):
        if not auth_attempt_allowed(request, "invitation", token):
            error = "Too many activation attempts. Wait before trying again."
        elif password != password_confirmation:
            error = "The password confirmation does not match."
        elif not accept_terms or not acknowledge_privacy or not confirm_adult:
            error = (
                "Confirm you are at least 18, accept the current Terms, and acknowledge "
                "the Privacy Notice before activating the account."
            )
        else:
            try:
                account = container.accounts.accept_invitation(token, display_name, password)
            except AccountError as exc:
                error = str(exc)
            else:
                container.legal.record_current(account.id)
                response = RedirectResponse("/", status_code=303)
                set_auth_cookie(response, account)
                return response
        return templates.TemplateResponse(
            request=request,
            name="invitation_accept.html",
            context={
                **auth_context(request, error=error),
                "submitted_token": token,
            },
            status_code=400,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.get("/recover", response_class=HTMLResponse, name="password_recovery")
    async def password_reset_page(request: Request):
        if container.settings.auth_mode != "accounts":
            return _redirect("/")
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context=auth_context(request),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post("/recover", response_class=HTMLResponse)
    async def password_reset_submit(
        request: Request,
        token: str = Form(max_length=512),
        password: str = Form(max_length=1_024),
        password_confirmation: str = Form(max_length=1_024),
    ):
        reset_account = container.accounts.password_reset_account(token)
        subject = reset_account.email if reset_account else token
        if not auth_attempt_allowed(request, "password_reset", subject):
            error = "Too many recovery attempts. Wait before trying again."
        elif password != password_confirmation:
            error = "The password confirmation does not match."
        else:
            try:
                container.accounts.reset_password(token, password)
            except AccountError as exc:
                error = str(exc)
            else:
                response = _redirect(
                    "/login",
                    notice="Your password was changed. Sign in with the new password.",
                )
                response.delete_cookie(AUTH_COOKIE, path="/")
                return response
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context={
                **auth_context(request, error=error),
                "submitted_token": token,
            },
            status_code=400,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post("/logout", name="logout")
    async def logout(request: Request):
        container.accounts.revoke_session(request.cookies.get(AUTH_COOKIE))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(AUTH_COOKIE, path="/")
        return response

    @app.get("/account", response_class=HTMLResponse, name="account")
    async def account_page(request: Request):
        account = current_account()
        if account is None:
            return _redirect("/")
        workspace = latest_workspace()
        profile = workspace.session.profile if workspace is not None else None
        return templates.TemplateResponse(
            request=request,
            name="account.html",
            context={
                "account": account,
                "workspace": workspace,
                "saved_jobs": stored_count(),
                "confirmed_statement_count": (
                    len(profile.confirmed_facts) if profile is not None else 0
                ),
                "open_statement_count": (len(profile.pending_facts) if profile is not None else 0),
                "legal_status": container.legal.status(account.id),
                "provider_choices": container.provider_permissions.choices(
                    account.id,
                    availability=container.provider_availability(),
                ),
                "provider_cost_summary": container.operations.summary_since(
                    account_id=account.id,
                ),
                "job_poster_access": container.job_posters.access_for(account.id),
                "job_posting_available": (container.settings.employer_job_posting_available),
                "operator_access": has_operator_access(account),
                **common(request, "account"),
            },
        )

    @app.get("/employer/jobs", response_class=HTMLResponse, name="employer_jobs")
    async def employer_jobs(request: Request):
        account = current_account()
        if account is None:
            return _redirect("/")
        access = container.job_posters.access_for(account.id)
        return templates.TemplateResponse(
            request=request,
            name="employer_jobs.html",
            context={
                "account": account,
                "poster_access": access,
                "poster_access_status": JobPosterAccessStatus,
                "postings": container.job_posters.list_owned(account.id),
                "posting_status": EmployerPostingStatus,
                "job_posting_available": (container.settings.employer_job_posting_available),
                **common(request, None),
            },
        )

    @app.post("/employer/jobs/request", name="employer_jobs_request")
    async def employer_jobs_request(
        company_name: str = Form(max_length=300),
        company_website: str = Form(max_length=2_000),
        work_email: str = Form(max_length=320),
        requester_note: str = Form(default="", max_length=2_000),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if not container.settings.employer_job_posting_available:
            return _redirect(
                "/employer/jobs",
                error="Employer publication is not enabled in this environment.",
            )
        try:
            container.job_posters.request_access(
                account.id,
                company_name=company_name,
                company_website=company_website,
                work_email=work_email,
                requester_note=requester_note,
            )
        except JobPosterError as exc:
            return _redirect("/employer/jobs", error=str(exc), fragment="poster-access")
        return _redirect(
            "/employer/jobs",
            notice="Verification request saved for operator review.",
            fragment="poster-access",
        )

    @app.post("/employer/jobs", name="employer_job_create")
    async def employer_job_create(
        title: str = Form(max_length=500),
        employer_name: str = Form(max_length=500),
        location: str = Form(max_length=500),
        work_model: str = Form(max_length=80),
        summary: str = Form(max_length=1_500),
        description: str = Form(max_length=30_000),
        application_url: str = Form(default="", max_length=2_000),
        application_email: str = Form(default="", max_length=320),
        publish_now: bool = Form(default=False),
        confirm_public_business_data: bool = Form(default=False),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if not container.settings.employer_job_posting_available:
            return _redirect(
                "/employer/jobs",
                error="Employer publication is not enabled in this environment.",
            )
        if not confirm_public_business_data:
            return _redirect(
                "/employer/jobs",
                error=(
                    "Confirm that the listing contains only authorized public job and "
                    "business-contact data."
                ),
                fragment="new-posting",
            )
        try:
            posting = container.job_posters.create_posting(
                account.id,
                title=title,
                employer_name=employer_name,
                location=location,
                work_model=work_model,
                summary=summary,
                description=description,
                application_url=application_url,
                application_email=application_email,
                publish=publish_now,
            )
        except JobPosterError as exc:
            return _redirect("/employer/jobs", error=str(exc), fragment="new-posting")
        return _redirect(
            "/employer/jobs",
            notice=(
                "Job published to the first-party Explore source."
                if posting.status == EmployerPostingStatus.PUBLISHED
                else "Job saved as a private poster draft."
            ),
            fragment=f"posting-{posting.id}",
        )

    @app.post(
        "/employer/jobs/{posting_id}/update",
        name="employer_job_update",
    )
    async def employer_job_update(
        posting_id: UUID,
        title: str = Form(max_length=500),
        employer_name: str = Form(max_length=500),
        location: str = Form(max_length=500),
        work_model: str = Form(max_length=80),
        summary: str = Form(max_length=1_500),
        description: str = Form(max_length=30_000),
        application_url: str = Form(default="", max_length=2_000),
        application_email: str = Form(default="", max_length=320),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if not container.settings.employer_job_posting_available:
            return _redirect(
                "/employer/jobs",
                error="Employer publication is not enabled in this environment.",
            )
        try:
            container.job_posters.update_posting(
                account.id,
                posting_id,
                title=title,
                employer_name=employer_name,
                location=location,
                work_model=work_model,
                summary=summary,
                description=description,
                application_url=application_url,
                application_email=application_email,
            )
        except JobPosterError as exc:
            return _redirect(
                "/employer/jobs",
                error=str(exc),
                fragment=f"posting-{posting_id}",
            )
        return _redirect(
            "/employer/jobs",
            notice="Posting changes saved.",
            fragment=f"posting-{posting_id}",
        )

    @app.post(
        "/employer/jobs/{posting_id}/status",
        name="employer_job_status",
    )
    async def employer_job_status(
        posting_id: UUID,
        action: str = Form(),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if not container.settings.employer_job_posting_available:
            return _redirect(
                "/employer/jobs",
                error="Employer publication is not enabled in this environment.",
            )
        try:
            if action == "publish":
                posting = container.job_posters.publish(account.id, posting_id)
                notice = "Job published to the first-party Explore source."
            elif action == "withdraw":
                posting = container.job_posters.withdraw(account.id, posting_id)
                notice = "Job withdrawn from Explore."
            else:
                raise JobPosterError("Unknown publication action.")
        except JobPosterError as exc:
            return _redirect(
                "/employer/jobs",
                error=str(exc),
                fragment=f"posting-{posting_id}",
            )
        return _redirect(
            "/employer/jobs",
            notice=notice,
            fragment=f"posting-{posting.id}",
        )

    @app.get(
        "/published-jobs/{posting_id}",
        response_class=HTMLResponse,
        name="published_job",
    )
    async def published_job(request: Request, posting_id: UUID):
        if not container.settings.employer_job_posting_available:
            raise HTTPException(status_code=404, detail="Published job not found")
        posting = container.job_posters.get_published(posting_id)
        if posting is None:
            raise HTTPException(status_code=404, detail="Published job not found")
        return templates.TemplateResponse(
            request=request,
            name="published_job.html",
            context={
                "posting": posting,
                **common(request, None),
            },
        )

    @app.post("/account/providers", name="account_providers")
    async def account_providers(
        enabled_provider: list[str] = Form(default=[]),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        availability = container.provider_availability()
        available_keys = {key for key, (available, _note) in availability.items() if available}
        try:
            container.provider_permissions.replace(
                account.id,
                set(enabled_provider),
                available_keys=available_keys,
            )
        except ProviderPermissionError as exc:
            return _redirect(
                "/account",
                error=str(exc),
                fragment="provider-choices",
            )
        return _redirect(
            "/account",
            notice="Provider choices saved for this account and all of its personas.",
            fragment="provider-choices",
        )

    @app.post("/account/legal", name="account_legal")
    async def account_legal(
        accept_terms: str | None = Form(default=None),
        acknowledge_privacy: str | None = Form(default=None),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if not accept_terms or not acknowledge_privacy:
            return _redirect(
                "/account",
                error="Select both legal-document confirmations to record the current versions.",
                fragment="legal-documents",
            )
        container.legal.record_current(account.id)
        return _redirect(
            "/account",
            notice="Current legal-document versions recorded.",
            fragment="legal-documents",
        )

    @app.get("/account/export", name="account_export")
    async def account_export():
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return PlainTextResponse(
            container.accounts.export_portable_json(account.id),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="worklifebalance-profile-export.json"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/account/username", name="account_username")
    async def account_username(
        username: str = Form(max_length=USERNAME_MAX_LENGTH),
        current_password: str = Form(max_length=1_024),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        try:
            container.accounts.update_username(
                account.id,
                username,
                current_password=current_password,
            )
        except AccountError as exc:
            return _redirect("/account", error=str(exc), fragment="account-settings")
        return _redirect(
            "/account",
            notice="Your username was updated.",
            fragment="account-settings",
        )

    @app.post("/account/password", name="account_password")
    async def account_password(
        current_password: str = Form(max_length=1_024),
        new_password: str = Form(max_length=1_024),
        confirm_password: str = Form(max_length=1_024),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if new_password != confirm_password:
            return _redirect(
                "/account",
                error="The new-password confirmation did not match.",
                fragment="account-settings",
            )
        try:
            container.accounts.change_password(
                account.id,
                current_password=current_password,
                new_password=new_password,
            )
        except AccountError as exc:
            return _redirect("/account", error=str(exc), fragment="account-settings")
        response = RedirectResponse(
            "/login?notice=Password+updated.+Sign+in+again+on+this+device.",
            status_code=303,
        )
        response.delete_cookie(AUTH_COOKIE, path="/")
        return response

    @app.post("/account/delete", response_class=HTMLResponse, name="account_delete")
    async def account_delete(
        request: Request,
        password: str = Form(max_length=1_024),
        confirmation: str = Form(max_length=64),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if confirmation.strip() != "DELETE MY ACCOUNT":
            return _redirect(
                "/account",
                error='Type "DELETE MY ACCOUNT" exactly before deleting your account.',
            )
        if not container.accounts.verify_password(account.id, password):
            return _redirect("/account", error="The password was not correct.")
        try:
            container.accounts.delete_account(account.id)
        except AccountError as exc:
            return _redirect("/account", error=str(exc))
        response = RedirectResponse(
            "/login?notice=Your+account+and+private+data+were+deleted.",
            status_code=303,
        )
        response.delete_cookie(AUTH_COOKIE, path="/")
        return response

    def import_destination(result: JobImportResult):
        if result.record is None:
            return _redirect(
                "/jobs",
                error=(
                    f"That does not look like a usable public job URL. {result.message or ''}"
                ).strip(),
            )
        grant_record(result.record.id)
        path = f"/jobs/{result.record.id}"
        if result.kind == JobObservationKind.NEW:
            return _redirect(path, notice="Job verified, extracted, and added to your archive.")
        if result.kind == JobObservationKind.UNCHANGED:
            return _redirect(
                path, notice="This job was already known. Its link check is now fresh."
            )
        if result.kind == JobObservationKind.CHANGED:
            return _redirect(path, notice="The advertisement changed. A new version was saved.")
        if result.kind == JobObservationKind.EXPIRED:
            return _redirect(
                path,
                error=(
                    "That job page is closed or expired. The link is kept under Closed so it is not lost. "
                    f"{result.message or ''}"
                ).strip(),
            )
        if result.kind == JobObservationKind.EXTRACTION_FAILED:
            return _redirect(
                path,
                error=(
                    "The page was reachable, but its job details could not be extracted yet. "
                    f"{result.message or ''}"
                ).strip(),
            )
        return _redirect(
            path,
            error=(
                "The job page could not be reached. It is saved for another check. "
                f"{result.message or ''}"
            ).strip(),
        )

    def check_storage_capacity(url: str, *, replacing_record_id: UUID | None = None) -> None:
        normalized = normalize_job_url(url)
        existing = container.repository.find_by_urls(normalized)
        allowed = accessible_record_ids()
        if existing is not None and (allowed is None or existing.id in allowed):
            return
        if stored_count() >= container.access_policy.max_stored_jobs:
            replacing_record = next(
                (item for item in accessible_records() if item.id == replacing_record_id),
                None,
            )
            if (
                replacing_record is not None
                and container.repository.get_current_job(replacing_record.id) is None
            ):
                return
            raise JobCorpusError(
                f"Your free workspace stores up to {container.access_policy.max_stored_jobs} jobs. "
                "Remove one from Archive before adding another."
            )

    def compass_action_for_page(active_page: str | None) -> CompassAction | None:
        return {
            "add": CompassAction.ADD,
            "explore": CompassAction.EXPLORE_COMPASS,
            "matches": CompassAction.MATCH,
            "apply": CompassAction.APPLY_NEW,
            "jobs": CompassAction.ARCHIVE,
        }.get(active_page)

    def compass_integrity_context(request: Request, active_page: str | None) -> dict:
        workspace = latest_workspace()
        report = inspect_compass_integrity(workspace.session if workspace is not None else None)
        action = compass_action_for_page(active_page)
        issue = report.primary_issue(action)
        account = current_account()
        can_create_persona = False
        if account is not None and persona_feature_enabled(request):
            can_create_persona = (
                len(container.personas.list_for_account(account.id))
                < container.settings.persona_limit
            )
        fix_url = "/profile"
        if workspace is not None:
            fix_url = f"/profile/{workspace.id}"
            if issue is not None and issue.section is not None:
                fix_url += f"#section-{issue.section.value}"
        return {
            "compass_integrity": report,
            "compass_integrity_issue": issue,
            "compass_integrity_action": action.value if action is not None else None,
            "compass_integrity_blocked_here": (action is not None and not report.allows(action)),
            "compass_integrity_fix_url": fix_url,
            "compass_integrity_can_create_persona": can_create_persona,
            "compass_explore_allowed": report.allows(CompassAction.EXPLORE_COMPASS),
            "application_generation_allowed": report.allows(CompassAction.APPLY_NEW),
        }

    def common(request: Request, active_page: str | None) -> dict:
        context = {
            "active_page": active_page,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
            "auth_mode": container.settings.auth_mode,
            "personas_enabled": persona_feature_enabled(request),
            "local_personas_enabled": persona_feature_enabled(request),
            "current_account": current_account(),
            "current_persona": current_persona(),
            "application_event_labels": {
                state.value: label for state, label in APPLICATION_LABELS.items()
            },
        }
        if active_page in {"profile", "add", "explore", "matches", "apply", "jobs"}:
            context.update(compass_integrity_context(request, active_page))
        return context

    def legal_page_context(request: Request, active_document: str) -> dict:
        settings = container.settings
        optional_providers = [
            ("OpenAI salary web search", settings.salary_research_enabled),
            ("Brave Search", bool(settings.brave_search_api_key)),
            ("Exa", bool(settings.exa_search_api_key)),
            (
                "OpenWebNinja JSearch",
                bool(settings.openwebninja_jsearch_api_key_value),
            ),
            ("EURES via Apify", bool(settings.apify_api_token_value)),
            ("JobsPipe via Apify", bool(settings.apify_api_token_value)),
            ("All Jobs Scraper via Apify", bool(settings.apify_api_token_value)),
            ("Google Routes", bool(settings.google_routes_api_key)),
            ("OpenRouteService", bool(settings.openrouteservice_api_key)),
            ("Transitous", settings.transitous_enabled),
            ("FOSSGIS Valhalla", settings.valhalla_enabled),
            ("public Nominatim", settings.osm_geocoder_enabled),
        ]
        return {
            "active_document": active_document,
            "operator_name": settings.legal_operator_name,
            "operator_address": settings.legal_operator_address,
            "legal_contact_email": settings.legal_contact_email,
            "terms_version": settings.legal_terms_version,
            "privacy_version": settings.legal_privacy_version,
            "legal_review_completed": settings.legal_review_completed,
            "processor_review_completed": settings.processor_review_completed,
            "enabled_optional_providers": [
                name for name, is_enabled in optional_providers if is_enabled
            ],
            "operator_details_complete": bool(
                settings.legal_operator_name
                and settings.legal_operator_address
                and settings.legal_contact_email
            ),
            **common(request, None),
        }

    @app.get("/legal/privacy", response_class=HTMLResponse, name="privacy_notice")
    async def privacy_notice(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="legal_privacy.html",
            context=legal_page_context(request, "privacy"),
        )

    @app.get("/legal/terms", response_class=HTMLResponse, name="terms")
    async def terms(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="legal_terms.html",
            context=legal_page_context(request, "terms"),
        )

    @app.get("/legal/imprint", response_class=HTMLResponse, name="imprint")
    async def imprint(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="legal_imprint.html",
            context=legal_page_context(request, "imprint"),
        )

    @app.get("/legal/ai", response_class=HTMLResponse, name="ai_notice")
    async def ai_notice(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="legal_ai.html",
            context=legal_page_context(request, "ai"),
        )

    @app.get("/legal/storage", response_class=HTMLResponse, name="storage_notice")
    async def storage_notice(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="legal_storage.html",
            context=legal_page_context(request, "storage"),
        )

    def has_operator_access(account: Account | None = None) -> bool:
        if container.settings.auth_mode != "accounts":
            return True
        return container.accounts.has_operator_access(
            account if account is not None else current_account(),
            legacy_operator_emails=container.settings.operator_email_set,
        )

    def require_operator(*, allow_legacy_bridge: bool = False) -> Account | None:
        account = current_account()
        if container.settings.auth_mode != "accounts":
            return account
        persisted = container.accounts.get(account.id) if account is not None else None
        if persisted is None or (
            not persisted.is_admin and not (allow_legacy_bridge and has_operator_access(persisted))
        ):
            raise HTTPException(status_code=404, detail="Page not found")
        return persisted

    @app.exception_handler(HTTPException)
    async def friendly_http_error(request: Request, exc: HTTPException):
        if "text/html" in request.headers.get("accept", ""):
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "status_code": exc.status_code,
                    "message": exc.detail,
                    **common(request, None),
                },
                status_code=exc.status_code,
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/", response_class=HTMLResponse, name="home")
    async def home(request: Request):
        snapshot = dashboard_for_current().overview()
        workspace = latest_workspace()
        current_opportunities = [
            item
            for item in snapshot.opportunities
            if item.availability == JobAvailability.LIVE
            and item.disposition in {MatchDisposition.TOP, MatchDisposition.STRETCH}
            and item.application_state
            not in {ApplicationState.REJECTED, ApplicationState.WITHDRAWN}
        ]
        employer_ratings, employer_rating_available = current_employer_ratings_by_record(
            current_opportunities
        )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            headers={"Cache-Control": "no-store"},
            context={
                "snapshot": snapshot,
                "current_opportunities": current_opportunities,
                "job_ratings": current_job_ratings(),
                "employer_ratings_by_record": employer_ratings,
                "employer_rating_available_by_record": employer_rating_available,
                "employer_names_by_record": current_employer_names_by_record(current_opportunities),
                "employer_keys_by_record": current_employer_keys_by_record(current_opportunities),
                "workspace": workspace,
                "smart_action": smart_home_action(snapshot, workspace),
                **common(request, "home"),
            },
        )

    @app.get("/feedback", response_class=HTMLResponse, name="product_feedback")
    async def product_feedback(request: Request):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Page not found")
        return templates.TemplateResponse(
            request=request,
            name="feedback.html",
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
            context={
                "feedback_items": container.feedback.list_for_account(account.id),
                "feedback_categories": FeedbackCategory,
                "feedback_surfaces": FeedbackSurface,
                "feedback_message_limit": MAX_FEEDBACK_MESSAGE_LENGTH,
                **common(request, "feedback"),
            },
        )

    @app.post("/feedback", name="product_feedback_submit")
    async def product_feedback_submit(
        category: str = Form(max_length=32),
        surface: str = Form(max_length=32),
        rating: str = Form(default="", max_length=1),
        message: str = Form(max_length=MAX_FEEDBACK_MESSAGE_LENGTH),
        contact_allowed: bool = Form(default=False),
    ):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Page not found")
        try:
            parsed_rating = int(rating) if rating else None
            container.feedback.submit(
                account.id,
                category=FeedbackCategory(category),
                surface=FeedbackSurface(surface),
                rating=parsed_rating,
                message=message,
                contact_allowed=contact_allowed,
            )
        except (ProductFeedbackError, ValueError):
            return _redirect(
                "/feedback",
                error="Choose the closest topic and area, then check the optional rating.",
            )
        return _redirect(
            "/feedback",
            notice="Thanks. Your feedback is saved for the private-alpha team.",
        )

    @app.post("/feedback/{feedback_id}/delete", name="product_feedback_delete")
    async def product_feedback_delete(feedback_id: UUID):
        account = current_account()
        if account is None:
            raise HTTPException(status_code=404, detail="Page not found")
        if not container.feedback.delete_owned(feedback_id, account_id=account.id):
            raise HTTPException(status_code=404, detail="Feedback not found")
        return _redirect("/feedback", notice="Feedback deleted.")

    @app.get("/operations", response_class=HTMLResponse, name="operations")
    async def operations(request: Request):
        """Show sanitized provider usage and operator-controlled guard settings."""

        account = require_operator(allow_legacy_bridge=True)
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        week_start = now - timedelta(days=7)
        settings = container.settings
        background_tasks = container.background_tasks.list_recent(limit=100)
        recent_runs = []
        for snapshot in container.results.recent_run_metrics(limit=100):
            providers = container.operations.breakdown_since(workflow_id=snapshot.id)
            recent_runs.append(
                {
                    "snapshot": snapshot,
                    "providers": providers,
                    "provider_names": ", ".join(sorted({row.provider for row in providers}))
                    or "No external provider work",
                }
            )
        billing_reports = container.billing_periods.list_reports(limit=50)
        legal_identity_complete = bool(
            settings.legal_operator_name
            and settings.legal_operator_address
            and settings.legal_contact_email
        )
        readiness_checks = [
            (
                "PostgreSQL deployment database",
                settings.database_url.startswith(("postgresql://", "postgresql+")),
                "SQLite remains appropriate only for local development.",
            ),
            (
                "HTTPS-only session cookies",
                settings.auth_secure_cookie,
                "Enable only behind a verified HTTPS deployment.",
            ),
            (
                "Controller and imprint identity",
                legal_identity_complete,
                "Configure the operator name, address, and legal contact email.",
            ),
            (
                "Externally reviewed legal documents",
                settings.legal_review_completed
                and "draft" not in settings.legal_terms_version.casefold()
                and "draft" not in settings.legal_privacy_version.casefold(),
                "Draft pages are an engineering scaffold, not legal approval.",
            ),
            (
                "Processor and transfer review",
                settings.processor_review_completed,
                "Review every enabled LLM, search, routing, email, and hosting provider.",
            ),
            (
                "Incident-response plan",
                settings.incident_plan_ready,
                "Assign contacts, containment steps, and breach-assessment procedure.",
            ),
            (
                "Backup restore rehearsal",
                settings.backup_restore_tested,
                "A backup is not a control until restoration has been tested.",
            ),
            (
                "Observed provider-cost calibration",
                bool(billing_reports),
                "Enter at least one provider billing window below.",
            ),
        ]
        invitation_readiness = [
            ("Legal review", settings.legal_review_completed),
            ("Processor review", settings.processor_review_completed),
            ("Incident-response plan", settings.incident_plan_ready),
            ("Backup restore drill", settings.backup_restore_tested),
        ]
        accounts = container.accounts.list_accounts()
        feedback_items = container.feedback.list_recent(limit=200)
        accounts_by_id = {item.id: item for item in accounts}
        admin_count = container.accounts.admin_count()
        return templates.TemplateResponse(
            request=request,
            name="operations.html",
            headers={
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
            context={
                "today": container.operations.summary_since(today_start),
                "week": container.operations.summary_since(week_start),
                "breakdown": container.operations.breakdown_since(today_start),
                "operation_limit": settings.provider_daily_operation_limit,
                "cost_limit_usd": settings.provider_daily_cost_limit_usd,
                "action_operation_limit": settings.provider_action_operation_limit,
                "action_cost_limit_usd": settings.provider_action_cost_limit_usd,
                "background_tasks": background_tasks,
                "operations_as_of": now,
                "active_background_tasks": sum(
                    1 for task in background_tasks if not task.is_terminal
                ),
                "background_worker_enabled": background_queue_enabled,
                "background_worker_running": background_worker_available(),
                "cost_estimates": [
                    (
                        "Brave Search call",
                        settings.brave_search_estimated_cost_per_call_usd,
                        "BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD",
                    ),
                    (
                        "Exa Search call",
                        settings.exa_search_estimated_cost_per_call_usd,
                        "BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD",
                    ),
                    (
                        "OpenWebNinja JSearch call",
                        settings.openwebninja_jsearch_estimated_cost_per_call_usd,
                        "BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD",
                    ),
                    (
                        "Apify EURES actor run",
                        settings.apify_eures_estimated_cost_per_run_usd,
                        "BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD",
                    ),
                    (
                        "Apify JobsPipe actor run",
                        settings.apify_jobspipe_estimated_cost_per_run_usd,
                        "BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD",
                    ),
                    (
                        "Apify All Jobs Scraper actor run",
                        settings.apify_all_jobs_estimated_cost_per_run_usd,
                        "BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD",
                    ),
                    (
                        "Company research call",
                        settings.company_research_estimated_cost_per_call_usd,
                        "BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD",
                    ),
                    (
                        "Google Routes call",
                        settings.google_routes_estimated_cost_per_call_usd,
                        "BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD",
                    ),
                ],
                "provider_statuses": [
                    ("Arbeitnow", "Available", "Keyless discovery feed"),
                    (
                        "Brave Search",
                        "Available" if settings.brave_search_api_key else "Not configured",
                        "Search-plan Web Search for discovery and employer research",
                    ),
                    ("Brave Answers", "Not used", "Separate product; no application code path"),
                    (
                        "Exa Search",
                        "Available" if settings.exa_search_api_key else "Not configured",
                        "Focused semantic discovery",
                    ),
                    (
                        "OpenWebNinja JSearch",
                        (
                            "Available"
                            if settings.openwebninja_jsearch_api_key_value
                            else "Not configured"
                        ),
                        "Optional structured job discovery",
                    ),
                    (
                        "EURES via Apify",
                        "Available" if settings.apify_api_token_value else "Not configured",
                        "Bounded structured European vacancy discovery",
                    ),
                    (
                        "JobsPipe via Apify",
                        "Available" if settings.apify_api_token_value else "Not configured",
                        "Separate bounded multi-source job-search actor",
                    ),
                    (
                        "All Jobs Scraper via Apify",
                        "Available" if settings.apify_api_token_value else "Not configured",
                        "Separate multi-board actor with per-platform and total caps",
                    ),
                    (
                        "OpenAI",
                        "Available" if settings.openai_api_key_value else "Not configured",
                        "Structured extraction",
                    ),
                    (
                        "Google Routes",
                        "Available" if settings.google_routes_api_key else "Not configured",
                        "Balanced-mode routing",
                    ),
                    (
                        "Transitous",
                        "Available" if settings.transitous_enabled else "Disabled",
                        "Public transport fallback",
                    ),
                    (
                        "Valhalla",
                        "Available" if settings.valhalla_enabled else "Disabled",
                        "OSM road-mode fallback",
                    ),
                    (
                        "OpenRouteService",
                        "Available" if settings.openrouteservice_api_key else "Not configured",
                        "Optional road-mode fallback",
                    ),
                ],
                "recent_runs": recent_runs,
                "billing_reports": billing_reports,
                "known_provider_names": container.operations.provider_names(),
                "readiness_checks": readiness_checks,
                "readiness_ready_count": sum(1 for _, ready, _ in readiness_checks if ready),
                "accounts": accounts,
                "invitations": container.accounts.list_invitations(),
                "account_role": AccountRole,
                "account_access_tier": AccountAccessTier,
                "feedback_items": feedback_items,
                "feedback_accounts": accounts_by_id,
                "feedback_counts": container.feedback.counts_by_account(),
                "feedback_status": FeedbackStatus,
                "legacy_operator_bridge_active": (
                    admin_count == 0 and bool(settings.operator_email_set)
                ),
                "current_operator": account,
                "job_poster_requests": container.job_posters.list_access_requests(),
                "invitation_readiness": invitation_readiness,
                "invitations_enabled": (
                    settings.registration_mode == RegistrationMode.INVITE_ONLY
                    and all(ready for _, ready in invitation_readiness)
                ),
                "registration_mode": settings.registration_mode,
                **common(request, "operations"),
            },
        )

    @app.post(
        "/operations/accounts/{account_id_value}/access",
        name="operations_account_access",
    )
    async def operations_account_access(
        account_id_value: UUID,
        role: str = Form(max_length=24),
        access_tier: str = Form(max_length=24),
        current_password: str = Form(max_length=1_024),
    ):
        operator = require_operator(allow_legacy_bridge=True)
        if operator is None or not container.accounts.verify_password(
            operator.id,
            current_password,
        ):
            return _redirect(
                "/operations",
                error="Confirm the current admin password before changing account access.",
                fragment=f"account-{account_id_value}",
            )
        try:
            updated = container.accounts.update_access(
                account_id_value,
                role=AccountRole(role),
                access_tier=AccountAccessTier(access_tier),
            )
        except (AccountError, ValueError) as exc:
            return _redirect(
                "/operations",
                error=str(exc),
                fragment=f"account-{account_id_value}",
            )
        return _redirect(
            "/operations",
            notice=(
                f"Access updated for {updated.display_name}: "
                f"{updated.role.value}, {updated.access_tier.value}."
            ),
            fragment=f"account-{account_id_value}",
        )

    @app.post(
        "/operations/feedback/{feedback_id}/review",
        name="operations_feedback_review",
    )
    async def operations_feedback_review(
        feedback_id: UUID,
        status: str = Form(max_length=24),
        operator_note: str = Form(default="", max_length=2_000),
    ):
        operator = require_operator()
        if operator is None:
            raise HTTPException(status_code=404, detail="Page not found")
        try:
            reviewed = container.feedback.review(
                feedback_id,
                status=FeedbackStatus(status),
                reviewer_account_id=operator.id,
                operator_note=operator_note,
            )
        except (ProductFeedbackError, ValueError) as exc:
            return _redirect(
                "/operations",
                error=str(exc),
                fragment="product-feedback",
            )
        return _redirect(
            "/operations",
            notice=f"Feedback marked {reviewed.status.value}.",
            fragment="product-feedback",
        )

    @app.get("/operations/feedback.csv", name="operations_feedback_export")
    async def operations_feedback_export():
        require_operator()

        def csv_cell(value: object | None) -> str:
            clean = "" if value is None else str(value)
            if clean.lstrip().startswith(("=", "+", "-", "@")):
                return "'" + clean
            return clean

        accounts_by_id = {item.id: item for item in container.accounts.list_accounts()}
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                "created_at",
                "status",
                "category",
                "area",
                "rating",
                "display_name",
                "follow_up_email",
                "message",
                "operator_note",
            )
        )
        for item in container.feedback.list_recent(limit=10_000):
            owner = accounts_by_id.get(item.account_id)
            writer.writerow(
                tuple(
                    csv_cell(value)
                    for value in (
                        item.created_at.isoformat(),
                        item.status.value,
                        item.category.value,
                        item.surface.value,
                        item.rating,
                        owner.display_name if owner else "Deleted account",
                        owner.email if owner and item.contact_allowed else "",
                        item.message,
                        item.operator_note,
                    )
                )
            )
        return Response(
            content="\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    'attachment; filename="worklifebalance-private-alpha-feedback.csv"'
                ),
                "X-Content-Type-Options": "nosniff",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post(
        "/operations/job-posters/{account_id_value}/review",
        name="operations_job_poster_review",
    )
    async def operations_job_poster_review(
        account_id_value: UUID,
        decision: str = Form(pattern="^(approve|reject)$"),
        reviewer_note: str = Form(default="", max_length=2_000),
    ):
        require_operator()
        operator = current_account()
        if operator is None:
            raise HTTPException(status_code=404, detail="Page not found")
        try:
            reviewed = container.job_posters.review_access(
                account_id_value,
                approved=decision == "approve",
                reviewer_account_id=operator.id,
                reviewer_note=reviewer_note,
            )
        except JobPosterError as exc:
            return _redirect(
                "/operations",
                error=str(exc),
                fragment="job-poster-access",
            )
        return _redirect(
            "/operations",
            notice=(f"Job-poster access {reviewed.status.value} for {reviewed.company_name}."),
            fragment="job-poster-access",
        )

    def require_external_invitation_readiness() -> None:
        settings = container.settings
        incomplete = [
            label
            for label, ready in (
                ("legal review", settings.legal_review_completed),
                ("processor review", settings.processor_review_completed),
                ("incident-response plan", settings.incident_plan_ready),
                ("backup restore drill", settings.backup_restore_tested),
            )
            if not ready
        ]
        if settings.registration_mode != RegistrationMode.INVITE_ONLY:
            raise AccountError(
                "Set BETTEROPTION_REGISTRATION_MODE=invite_only before creating invitations."
            )
        if incomplete:
            raise AccountError(
                "External invitations remain locked until these readiness items are complete: "
                + ", ".join(incomplete)
                + "."
            )

    @app.post("/operations/invitations", name="operations_invitation")
    async def operations_invitation(
        request: Request,
        email: str = Form(max_length=320),
    ):
        require_operator()
        operator = current_account()
        if operator is None:
            raise HTTPException(status_code=404, detail="Page not found")
        try:
            require_external_invitation_readiness()
            invitation, token = container.accounts.create_invitation(
                email,
                invited_by_account_id=operator.id,
                ttl=timedelta(hours=container.settings.auth_invitation_hours),
            )
        except AccountError as exc:
            return _redirect("/operations", error=str(exc), fragment="account-access")
        link = (
            container.settings.public_base_url.rstrip("/")
            + "/invite#token="
            + quote(token, safe="")
        )
        return templates.TemplateResponse(
            request=request,
            name="one_time_auth_link.html",
            context={
                "kind": "invitation",
                "heading": "Copy this invitation now",
                "description": (
                    f"This exact-email invitation for {invitation.email} expires "
                    f"{invitation.expires_at:%d %b %Y, %H:%M UTC}. The secret link "
                    "cannot be displayed again."
                ),
                "one_time_link": link,
                "back_url": "/operations#account-access",
                "auth_mode": container.settings.auth_mode,
                "current_account": operator,
                "active_page": "operations",
            },
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post(
        "/operations/invitations/{invitation_id}/revoke",
        name="operations_invitation_revoke",
    )
    async def operations_invitation_revoke(invitation_id: UUID):
        require_operator()
        if not container.accounts.revoke_invitation(invitation_id):
            return _redirect(
                "/operations",
                error="That invitation is no longer pending.",
                fragment="account-access",
            )
        return _redirect(
            "/operations",
            notice="Invitation revoked.",
            fragment="account-access",
        )

    @app.post(
        "/operations/accounts/{account_id_value}/recovery",
        name="operations_account_recovery",
    )
    async def operations_account_recovery(
        request: Request,
        account_id_value: UUID,
        current_password: str = Form(max_length=1_024),
    ):
        operator = require_operator()
        if operator is None or not container.accounts.verify_password(
            operator.id,
            current_password,
        ):
            return _redirect(
                "/operations",
                error="Confirm the current admin password before issuing a recovery link.",
                fragment=f"account-{account_id_value}",
            )
        try:
            account, token = container.accounts.create_password_reset(
                account_id_value,
                ttl=timedelta(minutes=container.settings.auth_recovery_minutes),
            )
        except AccountError as exc:
            return _redirect("/operations", error=str(exc), fragment="account-access")
        link = (
            container.settings.public_base_url.rstrip("/")
            + "/recover#token="
            + quote(token, safe="")
        )
        return templates.TemplateResponse(
            request=request,
            name="one_time_auth_link.html",
            context={
                "kind": "recovery",
                "heading": "Copy this recovery link now",
                "description": (
                    f"The recovery link for {account.email} expires in "
                    f"{container.settings.auth_recovery_minutes} minutes. It is single-use, "
                    "and a successful reset revokes all existing sessions."
                ),
                "one_time_link": link,
                "back_url": "/operations#account-access",
                "auth_mode": container.settings.auth_mode,
                "current_account": current_account(),
                "active_page": "operations",
            },
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )

    @app.post("/operations/calibrations", name="operations_calibration")
    async def operations_calibration(
        provider: str = Form(max_length=80),
        period_start: date = Form(),
        period_end: date = Form(),
        billed_amount: float = Form(ge=0),
        currency: str = Form(max_length=3),
        source_label: str = Form(default="", max_length=120),
    ):
        require_operator()
        if period_end < period_start:
            return _redirect(
                "/operations",
                error="Billing period end cannot be before its start.",
                fragment="billing-calibration",
            )
        start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
        try:
            container.billing_periods.add(
                ProviderBillingPeriod(
                    provider=provider,
                    period_start=start_at,
                    period_end=end_at,
                    billed_amount=billed_amount,
                    currency=currency,
                    source_label=source_label.strip() or None,
                )
            )
        except ValueError as exc:
            return _redirect(
                "/operations",
                error=str(exc),
                fragment="billing-calibration",
            )
        return _redirect(
            "/operations",
            notice="Billing period saved and correlated with recorded provider operations.",
            fragment="billing-calibration",
        )

    @app.post(
        "/operations/calibrations/{period_id}/delete",
        name="operations_calibration_delete",
    )
    async def operations_calibration_delete(period_id: UUID):
        require_operator()
        if not container.billing_periods.delete(period_id):
            raise HTTPException(status_code=404, detail="Billing period not found")
        return _redirect(
            "/operations",
            notice="Billing period removed.",
            fragment="billing-calibration",
        )

    def task_for_active_workspace(task_id: UUID):
        task = container.background_tasks.get(task_id)
        workspace = latest_workspace()
        if task is None or workspace is None or task.workspace_id != workspace.id:
            raise HTTPException(status_code=404, detail="Background workflow not found")
        return task

    def active_matching_pipeline(workspace_id: UUID):
        """Keep the complete Explore-import-to-Match chain visible."""

        candidates = [
            container.background_job_imports.find_active(
                workspace_id,
                JobImportDestination.MATCHING,
            ),
            container.background_tasks.find_active(
                workspace_id,
                BackgroundTaskKind.MATCH_RUN,
            ),
        ]
        active = [task for task in candidates if task is not None]
        return max(active, key=lambda task: task.created_at) if active else None

    def explore_task_preview(task_id: UUID) -> list[dict[str, object]]:
        """Return a bounded set of link-free public rows for the running-task preview."""

        snapshot = container.explore_searches.get(task_id)
        if snapshot is None:
            return []
        preview: list[dict[str, object]] = []
        for position, job in enumerate(
            snapshot.results[: container.settings.explore_preview_limit],
            start=1,
        ):
            is_own = "betteroption-posted" in job.effective_source_providers
            visible_tags: list[str] = []
            for raw_tag in job.tags:
                tag = " ".join(str(raw_tag).split())[:80]
                if (
                    not tag
                    or tag in EXPLORE_HIDDEN_SOURCE_TAGS
                    or tag.startswith("Source:")
                    or tag.startswith("Published via ")
                ):
                    continue
                visible_tags.append(tag)
                if len(visible_tags) >= 3:
                    break
            readiness_label = {
                SourceReadiness.READY: "Source checked",
                SourceReadiness.MANUAL_REQUIRED: "Needs pasted text",
                SourceReadiness.PROVIDER_LISTED: "Verify on save",
            }[job.source_readiness]
            preview.append(
                {
                    "rank": position,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "remote": job.remote,
                    "search_score": job.search_score,
                    "role_relevance": (
                        job.compass_relevance
                        if job.compass_relevance is not None
                        else job.keyword_relevance
                    ),
                    "seniority_relevance": job.seniority_relevance,
                    "distance_km": job.distance_km,
                    "provider_label": EXPLORE_PROVIDER_LABELS.get(
                        job.provider,
                        job.provider.replace("-", " ").title(),
                    ),
                    "is_own": is_own,
                    "readiness": job.source_readiness.value,
                    "readiness_label": readiness_label,
                    "tags": visible_tags,
                }
            )
        return preview

    @app.get("/tasks/{task_id}", response_class=HTMLResponse, name="task_progress")
    async def task_progress(request: Request, task_id: UUID):
        task = task_for_active_workspace(task_id)
        if task.status == BackgroundTaskStatus.SUCCEEDED and task.result_url:
            return RedirectResponse(task.result_url, status_code=303)
        is_explore = task.kind == BackgroundTaskKind.EXPLORE_SEARCH
        is_import = task.kind == BackgroundTaskKind.JOB_IMPORT
        explore_wait = container.explore_searches.get(task.id) if is_explore else None
        import_batch = container.background_job_imports.get(task.id) if is_import else None
        is_matching_import = (
            import_batch is not None and import_batch.destination == JobImportDestination.MATCHING
        )
        task_view = {
            "active_page": (
                "matches" if is_matching_import or not (is_explore or is_import) else "explore"
            ),
            "browser_title": (
                "Explore search in progress"
                if is_explore
                else "Job import in progress"
                if is_import
                else "Matching in progress"
            ),
            "heading": (
                "Searching public feeds and employer job boards."
                if is_explore
                else "Verifying and saving your selected jobs."
                if is_import
                else "Building your evidence-backed matches."
            ),
            "progress_label": (
                "Explore search progress"
                if is_explore
                else "Job import progress"
                if is_import
                else "Matching progress"
            ),
            "resume_copy": (
                "Returning to Explore resumes this progress view."
                if is_explore or (is_import and not is_matching_import)
                else "Returning to Match resumes this progress view."
            ),
            "failure_heading": (
                "Explore needs attention."
                if is_explore
                else "The selected sources need attention."
                if is_import
                else "Matching needs attention."
            ),
            "return_url": (
                "/explore" if is_explore or (is_import and not is_matching_import) else "/matches"
            ),
            "return_label": (
                "Return to Explore"
                if is_explore or (is_import and not is_matching_import)
                else "Return to Matching"
            ),
            "waiting_location": explore_wait.location if explore_wait is not None else "",
        }
        return templates.TemplateResponse(
            request=request,
            name="task_progress.html",
            context={
                "task": task,
                "task_view": task_view,
                "task_status": BackgroundTaskStatus,
                "background_worker_running": background_worker_available(task),
                "background_worker_recovery_needed": (
                    task.status == BackgroundTaskStatus.RUNNING and not task_lease_fresh(task)
                ),
                "explore_preview_limit": container.settings.explore_preview_limit,
                **common(request, task_view["active_page"]),
            },
        )

    @app.post("/tasks/{task_id}/cancel", name="task_cancel")
    async def task_cancel(task_id: UUID):
        task = task_for_active_workspace(task_id)
        cancelled = container.background_tasks.request_cancel(task.id)
        # External workers observe the cleared lease on their next heartbeat;
        # an embedded local worker can be nudged immediately as well.
        background_worker.cancel(task.id)
        if cancelled.kind == BackgroundTaskKind.JOB_IMPORT and cancelled.is_terminal:
            container.background_job_imports.delete(cancelled.id)
        background_worker.wake()
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    @app.get("/tasks/{task_id}/status", name="task_status")
    async def task_status(task_id: UUID):
        task = task_for_active_workspace(task_id)
        payload: dict[str, object] = {
            "id": str(task.id),
            "kind": task.kind.value,
            "status": task.status.value,
            "phase": task.phase,
            "message": task.message,
            "completed_units": task.completed_units,
            "total_units": task.total_units,
            "progress_percent": task.progress_percent,
            "progress_indeterminate": task.total_units <= 0 and not task.is_terminal,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "next_attempt_at": (task.next_attempt_at.isoformat() if task.next_attempt_at else None),
            "result_url": task.result_url
            if task.status == BackgroundTaskStatus.SUCCEEDED
            else None,
            "updated_at": task.updated_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "worker_running": background_worker_available(task),
            "worker_error": background_worker.last_loop_error,
            "lease_fresh": (
                task_lease_fresh(task) if task.status == BackgroundTaskStatus.RUNNING else None
            ),
            "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None,
            "lease_expires_at": (
                task.lease_expires_at.isoformat() if task.lease_expires_at else None
            ),
            "cancel_requested_at": (
                task.cancel_requested_at.isoformat() if task.cancel_requested_at else None
            ),
            "cancelled_at": task.cancelled_at.isoformat() if task.cancelled_at else None,
            "cancellable": not task.is_terminal and task.cancel_requested_at is None,
            "error_message": (
                task.error_message if task.status == BackgroundTaskStatus.FAILED else None
            ),
        }
        if task.kind == BackgroundTaskKind.EXPLORE_SEARCH:
            payload["preview"] = explore_task_preview(task.id)
        return JSONResponse(payload)

    @app.get("/profile", response_class=HTMLResponse, name="profile")
    async def profile(request: Request):
        workspace = latest_workspace()
        if workspace is None:
            return templates.TemplateResponse(
                request=request,
                name="profile_start.html",
                context={
                    "opening_definition": CORE_SECTION_DEFINITIONS[0],
                    **common(request, "profile"),
                },
            )
        return _redirect(f"/profile/{workspace.id}")

    @app.post("/profile/start", name="profile_start")
    async def profile_start(
        answer: str | None = Form(default=None, max_length=20_000),
        confirm_restart: bool = Form(default=False),
    ):
        current = latest_workspace()
        if current is not None and not confirm_restart:
            return _redirect(
                f"/profile/{current.id}",
                error="Confirm that you want to start a new compass before replacing the active one.",
            )
        existing_record_ids = accessible_record_ids() or set()
        try:
            workspace = workflow().start()
        except (PersonaError, ProfileWorkflowError, ValueError) as exc:
            destination = f"/profile/{current.id}" if current is not None else "/profile"
            return _redirect(destination, error=str(exc))
        if container.settings.auth_mode == "accounts":
            for record_id in existing_record_ids:
                container.results.grant_job(workspace.id, record_id)
        if not answer or not answer.strip():
            return _redirect(f"/profile/{workspace.id}")
        try:
            profile_workflow = workflow(require_extractor=True)
            with provider_operation_scope(uuid4(), "profile-extraction"):
                workspace = profile_workflow.answer(workspace.id, answer)
        except (ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect(f"/profile/{workspace.id}", error=str(exc))
        destination = (
            f"/profile/{workspace.id}/review?return_to=guided"
            if next_review_section(workspace.session)
            else f"/profile/{workspace.id}/guided"
        )
        return _redirect(destination, error=profile_workflow.last_extraction_warning)

    @app.get("/profile/{workspace_id}", response_class=HTMLResponse, name="profile_conversation")
    async def profile_compass(request: Request, workspace_id: UUID):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        if workspace_stage(workspace) == "review":
            return _redirect(f"/profile/{workspace.id}/review?return_to=compass")
        confirmed = [
            fact
            for fact in workspace.session.profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
        ]
        section_cards = [
            {
                "definition": definition,
                "progress": progress_for(workspace.session, definition.section),
                "raw_answer": workspace.session.profile.raw_sections.get(definition.section, ""),
                "facts": [
                    fact
                    for fact in confirmed
                    if fact.source.section == definition.section
                    and not is_language_editor_fact(fact)
                ],
            }
            for definition in CORE_SECTION_DEFINITIONS
        ]
        latest_groups = result_service().latest(workspace)
        return templates.TemplateResponse(
            request=request,
            name="profile_compass.html",
            context={
                "workspace": workspace,
                "section_cards": section_cards,
                "confirmed_count": len(confirmed),
                "levels": list(RequirementLevel),
                "has_guided_work": workspace.session.state != SessionState.COMPLETED,
                "matches_are_current": (
                    latest_groups.profile_is_current if latest_groups is not None else None
                ),
                "progress_percent": round(
                    100 * workspace.session.completed_count / len(workspace.session.sections)
                ),
                "cv_documents": container.cvs.list_for_workspace(workspace.id),
                "mobility_preferences": mobility_widget_preferences(workspace.session.profile),
                "compensation_currencies": SUPPORTED_COMPENSATION_CURRENCIES,
                "spoken_languages": SPOKEN_LANGUAGES,
                "spoken_language_selections": profile_language_selections(
                    workspace.session.profile,
                    programming=False,
                ),
                "spoken_language_mentions": profile_language_mentions(
                    workspace.session.profile,
                    programming=False,
                ),
                "programming_languages": PROGRAMMING_LANGUAGES,
                "programming_language_selections": profile_language_selections(
                    workspace.session.profile,
                    programming=True,
                ),
                "programming_language_mentions": profile_language_mentions(
                    workspace.session.profile,
                    programming=True,
                ),
                "practical_proficiencies": list(PracticalProficiency),
                "proficiency_slider_indexes": {
                    level.value: index for index, level in enumerate(PracticalProficiency)
                },
                **common(request, "profile"),
            },
        )

    @app.post("/profile/{workspace_id}/cv", name="profile_cv_upload")
    async def profile_cv_upload(
        request: Request,
        workspace_id: UUID,
        cv_file: UploadFile = File(),
        acknowledge_cv_rules: bool = Form(default=False),
    ):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        if not acknowledge_cv_rules:
            return _redirect(
                f"/profile/{workspace_id}",
                error="Read and acknowledge the CV data rules before preparing a preview.",
            )
        filename = cv_file.filename or "cv"
        try:
            content = await cv_file.read(MAX_CV_BYTES + 1)
            extracted_text, _media_type = extract_cv_text(filename, content)
            preview = sanitize_cv_text(extracted_text)
        except (RuntimeError, ValueError) as exc:
            return _redirect(f"/profile/{workspace_id}", error=str(exc))
        if preview.blocked:
            return _redirect(
                f"/profile/{workspace_id}",
                error=(
                    "CV processing stopped locally because the text appears to contain: "
                    f"{', '.join(preview.blocked_categories)}. Remove that information "
                    "from the source file and try again."
                ),
            )
        return templates.TemplateResponse(
            request=request,
            name="profile_cv_preview.html",
            context={
                "workspace": workspace,
                "selected_text": preview.text,
                "redactions": preview.redactions,
                "preview_changed": False,
                **common(request, "profile"),
            },
        )

    @app.post("/profile/{workspace_id}/cv/confirm", name="profile_cv_confirm")
    async def profile_cv_confirm(
        request: Request,
        workspace_id: UUID,
        selected_text: str = Form(min_length=20, max_length=MAX_CV_TEXT),
        cv_ai_consent: bool = Form(default=False),
        confirm_no_sensitive_data: bool = Form(default=False),
    ):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        if not cv_ai_consent or not confirm_no_sensitive_data:
            return _redirect(
                f"/profile/{workspace_id}",
                error=(
                    "The optional CV extraction requires both the specific OpenAI action "
                    "and confirmation that the displayed text contains no prohibited data."
                ),
            )
        try:
            checked = sanitize_cv_text(selected_text)
        except ValueError as exc:
            return _redirect(f"/profile/{workspace_id}", error=str(exc))
        if checked.blocked:
            return _redirect(
                f"/profile/{workspace_id}",
                error=(
                    "CV processing stopped locally because the edited text appears to contain: "
                    f"{', '.join(checked.blocked_categories)}. Remove it and prepare a new preview."
                ),
            )
        if checked.text != canonical_cv_preview_text(selected_text):
            return templates.TemplateResponse(
                request=request,
                name="profile_cv_preview.html",
                context={
                    "workspace": workspace,
                    "selected_text": checked.text,
                    "redactions": checked.redactions,
                    "preview_changed": True,
                    **common(request, "profile"),
                },
            )
        try:
            profile_workflow = workflow(require_extractor=True)
            with provider_operation_scope(uuid4(), "profile-extraction"):
                profile_workflow.add_private_evidence(
                    workspace_id,
                    checked.text,
                    source_label="user-reviewed CV preview",
                )
        except (KeyError, ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect(f"/profile/{workspace_id}", error=str(exc))
        return _redirect(
            f"/profile/{workspace_id}/review?return_to=compass",
            notice=(
                "CV proposals are ready. The original file and transient selected text "
                "were not retained by WorkLifeBalance."
            ),
        )

    @app.post(
        "/profile/{workspace_id}/cv/{document_id}/review",
        name="profile_cv_review",
    )
    async def profile_cv_review(workspace_id: UUID, document_id: UUID):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        document = container.cvs.get(workspace_id, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="CV document not found")
        return _redirect(
            f"/profile/{workspace_id}",
            error=(
                "Direct processing of legacy saved CV text is disabled. Delete it and "
                "use the new local-redaction preview flow."
            ),
        )

    @app.post(
        "/profile/{workspace_id}/cv/{document_id}/delete",
        name="profile_cv_delete",
    )
    async def profile_cv_delete(
        workspace_id: UUID,
        document_id: UUID,
        confirm_delete: bool = Form(default=False),
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        if not confirm_delete:
            return _redirect(f"/profile/{workspace_id}", error="Confirm CV deletion first.")
        if not container.cvs.delete(workspace_id, document_id):
            raise HTTPException(status_code=404, detail="CV document not found")
        return _redirect(f"/profile/{workspace_id}", notice="Saved CV text deleted.")

    @app.get(
        "/profile/{workspace_id}/guided",
        response_class=HTMLResponse,
        name="profile_guided",
    )
    async def profile_guided(request: Request, workspace_id: UUID):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        if workspace_stage(workspace) == "review":
            return _redirect(f"/profile/{workspace.id}/review?return_to=guided")
        clarification_section = next_clarification_section(workspace.session)
        section = clarification_section or next_pending_section(workspace.session)
        clarification_question = (
            progress_for(workspace.session, clarification_section).follow_up_question
            if clarification_section
            else None
        )
        return templates.TemplateResponse(
            request=request,
            name="profile_conversation.html",
            context={
                "workspace": workspace,
                "messages": container.workspaces.messages(workspace.id),
                "definition": definition_for(section) if section else None,
                "clarification_question": clarification_question,
                "ready_with_skips": workspace.session.state == SessionState.READY_WITH_SKIPS,
                "progress_percent": round(
                    100 * workspace.session.completed_count / len(workspace.session.sections)
                ),
                **common(request, "profile"),
            },
        )

    @app.post(
        "/profile/{workspace_id}/sections/{section}/detail",
        name="profile_section_detail",
    )
    async def profile_section_detail(
        workspace_id: UUID,
        section: str,
        answer: str = Form(min_length=1, max_length=20_000),
    ):
        try:
            profile_section = ProfileSection(section)
            definition_for(profile_section)
            existing = owned_workspace(workspace_id)
            if existing is None:
                raise KeyError("Profile workspace not found")
            before = {
                (fact.key, str(fact.value), fact.level)
                for fact in existing.session.profile.facts
                if fact.evidence_status == EvidenceStatus.CONFIRMED
            }
            profile_workflow = workflow(require_extractor=True)
            with provider_operation_scope(uuid4(), "profile-extraction"):
                workspace = profile_workflow.add_section_detail(
                    workspace_id,
                    profile_section,
                    answer,
                )
        except (KeyError, ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment=f"section-{section}",
            )
        after = {
            (fact.key, str(fact.value), fact.level)
            for fact in workspace.session.profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
        }
        if profile_workflow.last_extraction_warning:
            return _redirect(
                f"/profile/{workspace.id}",
                error=profile_workflow.last_extraction_warning,
                fragment=f"section-{profile_section.value}",
            )
        if after == before:
            return _redirect(
                f"/profile/{workspace.id}",
                notice=(
                    "No new Compass statement was found. Your existing statements remain active."
                ),
                fragment=f"section-{profile_section.value}",
            )
        return _redirect(
            f"/profile/{workspace.id}",
            notice="Your Compass section was updated. Run Matching again when you are ready.",
            fragment=f"section-{profile_section.value}",
        )

    @app.post(
        "/profile/{workspace_id}/compensation-range",
        name="profile_compensation_range",
    )
    async def profile_compensation_range(
        workspace_id: UUID,
        currency: str = Form(default="EUR", min_length=3, max_length=3),
        minimum_gross_annual: int = Form(ge=0, le=300_000),
        target_gross_annual: int | None = Form(default=None, ge=0, le=300_000),
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            workspace = workflow().save_compensation_range(
                workspace_id,
                minimum_gross_annual=minimum_gross_annual,
                target_gross_annual=target_gross_annual,
                currency=currency,
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment=f"section-{ProfileSection.COMPENSATION_TIME.value}",
            )
        return _redirect(
            f"/profile/{workspace.id}",
            notice=("Annual gross salary range saved. Run Matching again when you are ready."),
            fragment=f"section-{ProfileSection.COMPENSATION_TIME.value}",
        )

    @app.post(
        "/profile/{workspace_id}/spoken-languages",
        name="profile_spoken_languages",
    )
    async def profile_spoken_languages(
        request: Request,
        workspace_id: UUID,
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        form = await request.form()
        names = [str(value) for value in form.getlist("language_name")]
        slider_levels = list(PracticalProficiency)
        submitted_levels = [str(form.get(f"proficiency::{name}", "")) for name in names]
        proficiencies = [
            slider_levels[int(value)].value
            if value.isdigit() and 0 <= int(value) < len(slider_levels)
            else value
            for value in submitted_levels
        ]
        try:
            workspace = workflow().save_candidate_languages(
                workspace_id,
                names=names,
                proficiencies=proficiencies,
                programming=False,
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment="spoken-languages",
            )
        return _redirect(
            f"/profile/{workspace.id}",
            notice="Spoken languages saved as candidate evidence.",
            fragment="spoken-languages",
        )

    @app.post(
        "/profile/{workspace_id}/programming-languages",
        name="profile_programming_languages",
    )
    async def profile_programming_languages(
        request: Request,
        workspace_id: UUID,
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        form = await request.form()
        names = [str(value) for value in form.getlist("language_name")]
        slider_levels = list(PracticalProficiency)
        submitted_levels = [str(form.get(f"proficiency::{name}", "")) for name in names]
        proficiencies = [
            slider_levels[int(value)].value
            if value.isdigit() and 0 <= int(value) < len(slider_levels)
            else value
            for value in submitted_levels
        ]
        try:
            workspace = workflow().save_candidate_languages(
                workspace_id,
                names=names,
                proficiencies=proficiencies,
                programming=True,
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment="programming-languages",
            )
        return _redirect(
            f"/profile/{workspace.id}",
            notice="Programming languages saved as candidate evidence.",
            fragment="programming-languages",
        )

    @app.post(
        "/profile/{workspace_id}/location-suggestions",
        name="profile_location_suggestions",
    )
    async def profile_location_suggestions(
        workspace_id: UUID,
        query: str = Form(min_length=2, max_length=200),
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        suggestion = normalize_compass_origin(query)
        return JSONResponse(
            {
                "suggestions": [suggestion] if suggestion else [],
            }
        )

    @app.post(
        "/profile/{workspace_id}/mobility-preferences",
        name="profile_mobility_preferences",
    )
    async def profile_mobility_preferences(
        workspace_id: UUID,
        origin_label: str = Form(default="", max_length=200),
        car_minutes: int = Form(default=0, ge=0, le=360),
        transit_minutes: int = Form(default=0, ge=0, le=360),
        bicycle_minutes: int = Form(default=0, ge=0, le=360),
    ):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            workspace = workflow().save_mobility_preferences(
                workspace_id,
                origin_label=normalize_compass_origin(origin_label),
                car_minutes=car_minutes,
                transit_minutes=transit_minutes,
                bicycle_minutes=bicycle_minutes,
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment=f"section-{ProfileSection.LOCATION_MOBILITY.value}",
            )
        return _redirect(
            f"/profile/{workspace.id}",
            notice="Location and mobility saved. Run Matching again when you are ready.",
            fragment=f"section-{ProfileSection.LOCATION_MOBILITY.value}",
        )

    @app.post(
        "/profile/{workspace_id}/saved-facts/{fact_id}",
        name="profile_saved_fact_action",
    )
    async def profile_saved_fact_action(
        workspace_id: UUID,
        fact_id: UUID,
        action: str = Form(),
        new_value: str | None = Form(default=None, max_length=1_000),
        new_level: str | None = Form(default=None),
    ):
        existing = owned_workspace(workspace_id)
        existing_fact = (
            next(
                (fact for fact in existing.session.profile.facts if fact.id == fact_id),
                None,
            )
            if existing is not None
            else None
        )
        section_fragment = (
            f"section-{existing_fact.source.section.value}" if existing_fact is not None else None
        )
        try:
            workflow().revise_confirmed_fact(
                workspace_id,
                fact_id,
                action=ReviewAction(action),
                new_value=new_value,
                new_level=RequirementLevel(new_level) if new_level else None,
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}",
                error=str(exc),
                fragment=section_fragment,
            )
        message = (
            "Statement removed from active matching."
            if action == ReviewAction.REJECT.value
            else "Compass statement updated. Run Matching again to compare the change."
        )
        return _redirect(
            f"/profile/{workspace_id}",
            notice=message,
            fragment=(
                section_fragment if action == ReviewAction.REJECT.value else f"fact-{fact_id}"
            ),
        )

    @app.post("/profile/{workspace_id}/answer", name="profile_answer")
    async def profile_answer(
        workspace_id: UUID,
        answer: str = Form(min_length=1, max_length=20_000),
    ):
        try:
            profile_workflow = workflow(require_extractor=True)
            with provider_operation_scope(uuid4(), "profile-extraction"):
                workspace = profile_workflow.answer(workspace_id, answer)
        except (ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect(f"/profile/{workspace_id}/guided", error=str(exc))
        destination = (
            f"/profile/{workspace.id}/review?return_to=guided"
            if next_review_section(workspace.session)
            else f"/profile/{workspace.id}/guided"
        )
        return _redirect(destination, error=profile_workflow.last_extraction_warning)

    @app.post("/profile/{workspace_id}/skip", name="profile_skip")
    async def profile_skip(workspace_id: UUID):
        try:
            workspace = workflow().skip(workspace_id)
        except ProfileWorkflowError as exc:
            return _redirect(f"/profile/{workspace_id}/guided", error=str(exc))
        return _redirect(f"/profile/{workspace.id}/guided", notice="Section saved for later.")

    @app.post("/profile/{workspace_id}/revisit-skipped", name="profile_revisit_skipped")
    async def profile_revisit_skipped(workspace_id: UUID):
        try:
            workspace = workflow().revisit_skipped(workspace_id)
        except ProfileWorkflowError as exc:
            return _redirect(f"/profile/{workspace_id}/guided", error=str(exc))
        return _redirect(
            f"/profile/{workspace.id}/guided",
            notice="Your skipped questions are ready again.",
        )

    @app.get("/profile/{workspace_id}/review", response_class=HTMLResponse, name="profile_review")
    async def profile_review(request: Request, workspace_id: UUID):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        section = next_review_section(workspace.session)
        reference_ids = pending_reference_learning_ids(workspace.session.profile)
        if section is None and not reference_ids:
            destination = (
                f"/profile/{workspace.id}"
                if request.query_params.get("return_to") == "compass"
                else f"/profile/{workspace.id}/guided"
            )
            return _redirect(destination)
        if section is not None:
            progress = progress_for(workspace.session, section)
            definition = definition_for(section)
            proposed_ids = set(progress.proposed_fact_ids)
        else:
            progress = {
                "summary": (
                    "These suggestions come from your own reference notes and verified job "
                    "evidence. They remain inactive until you confirm or edit them."
                ),
                "follow_up_question": None,
            }
            definition = {"title": "Reference learning"}
            proposed_ids = set(reference_ids)
        facts = [fact for fact in workspace.session.profile.facts if fact.id in proposed_ids]
        references_by_id = {
            reference.id: reference for reference in workspace.session.profile.reference_jobs
        }
        reference_urls_by_fact = {
            fact.id: list(
                dict.fromkeys(
                    str(reference.resolved_url or reference.url)
                    for reference_id in fact.source_reference_ids
                    if (reference := references_by_id.get(reference_id)) is not None
                )
            )
            for fact in facts
        }
        return templates.TemplateResponse(
            request=request,
            name="profile_review.html",
            context={
                "workspace": workspace,
                "definition": definition,
                "progress": progress,
                "facts": facts,
                "reference_urls_by_fact": reference_urls_by_fact,
                "levels": list(RequirementLevel),
                "return_to": (
                    "compass" if request.query_params.get("return_to") == "compass" else "guided"
                ),
                **common(request, "profile"),
            },
        )

    @app.post("/profile/{workspace_id}/facts/{fact_id}", name="profile_fact_action")
    async def profile_fact_action(
        workspace_id: UUID,
        fact_id: UUID,
        action: str = Form(),
        new_value: str | None = Form(default=None),
        new_level: str | None = Form(default=None),
        return_to: str = Form(default="guided"),
    ):
        try:
            workspace = workflow().review_fact(
                workspace_id,
                fact_id,
                ReviewAction(action),
                new_value=new_value,
                new_level=RequirementLevel(new_level) if new_level else None,
                continue_guided=return_to != "compass",
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}/review?return_to={return_to}", error=str(exc)
            )
        destination = (
            f"/profile/{workspace.id}/review?return_to={return_to}"
            if workspace_stage(workspace) == "review"
            else (
                f"/profile/{workspace.id}"
                if return_to == "compass"
                else f"/profile/{workspace.id}/guided"
            )
        )
        return _redirect(destination, notice="Your decision is saved.")

    @app.post(
        "/profile/{workspace_id}/confirm-selected",
        name="profile_facts_confirm_selected",
    )
    async def profile_facts_confirm_selected(
        workspace_id: UUID,
        selected_fact_ids: list[UUID] = Form(default=[]),
        return_to: str = Form(default="guided"),
    ):
        try:
            workspace = workflow().confirm_facts(
                workspace_id,
                selected_fact_ids,
                continue_guided=return_to != "compass",
            )
        except (KeyError, ProfileWorkflowError, ValueError) as exc:
            return _redirect(
                f"/profile/{workspace_id}/review?return_to={return_to}", error=str(exc)
            )
        destination = (
            f"/profile/{workspace.id}/review?return_to={return_to}"
            if workspace_stage(workspace) == "review"
            else (
                f"/profile/{workspace.id}"
                if return_to == "compass"
                else f"/profile/{workspace.id}/guided"
            )
        )
        return _redirect(destination, notice="Selected statements confirmed.")

    @app.get(
        "/profile/{workspace_id}/references",
        response_class=HTMLResponse,
        name="profile_references",
    )
    async def profile_references(request: Request, workspace_id: UUID):
        workspace = owned_workspace(workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        return _redirect(
            "/add",
            notice="Job intake now lives on Add, separate from the match results.",
        )

    @app.post("/profile/{workspace_id}/references", name="profile_reference_add")
    async def profile_reference_add(
        workspace_id: UUID,
        url: str = Form(min_length=8, max_length=2_000),
        positives: str = Form(default="", max_length=5_000),
        negatives: str = Form(default="", max_length=5_000),
        learning_enabled: bool = Form(default=False),
        learning_scope: list[str] = Form(default=[]),
    ):
        return _redirect(
            "/add",
            notice="Add this URL on the dedicated Add page.",
        )

    @app.post(
        "/profile/{workspace_id}/references/{reference_id}/delete",
        name="profile_reference_delete",
    )
    async def profile_reference_delete(workspace_id: UUID, reference_id: UUID):
        if owned_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            workflow().delete_reference(workspace_id, reference_id)
        except ProfileWorkflowError as exc:
            return _redirect("/add", error=str(exc))
        return _redirect("/add", notice="Reference preferences removed.")

    @app.get("/jobs", response_class=HTMLResponse, name="jobs")
    async def jobs(request: Request, status: str | None = Query(default=None)):
        selected = None
        if status:
            try:
                selected = JobAvailability(status)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Unknown opportunity status") from exc
        scoped_dashboard = dashboard_for_current()
        workspace = latest_workspace()
        draft_counts = (
            container.application_drafts.counts_for_workspace(workspace.id)
            if workspace is not None
            else {}
        )
        count = stored_count()
        opportunities = scoped_dashboard.list_opportunities(selected)
        employer_ratings, employer_rating_available = current_employer_ratings_by_record(
            opportunities
        )
        return templates.TemplateResponse(
            request=request,
            name="jobs.html",
            headers={"Cache-Control": "no-store"},
            context={
                "opportunities": opportunities,
                "selected_status": selected.value if selected else "all",
                "stored_count": count,
                "max_stored_jobs": container.access_policy.max_stored_jobs,
                "available_slots": max(
                    0,
                    container.access_policy.max_stored_jobs - count,
                ),
                "application_labels": APPLICATION_LABELS,
                "draft_counts": draft_counts,
                "job_ratings": current_job_ratings(),
                "employer_ratings_by_record": employer_ratings,
                "employer_rating_available_by_record": employer_rating_available,
                "employer_names_by_record": current_employer_names_by_record(opportunities),
                "employer_keys_by_record": current_employer_keys_by_record(opportunities),
                **common(request, "jobs"),
            },
        )

    def prepare_explore_query(
        *,
        q: str | None,
        location: str,
        use_compass: bool,
        hide_remote_only: bool,
        worldwide: bool,
        include_custom_portals: bool,
    ) -> tuple[DiscoveryQuery | None, str, str, bool, str | None]:
        query_text = (q or "").strip()
        resolved_location = location.strip()
        compass_used = False
        search_error = None
        discovery_query = None
        if use_compass:
            workspace = latest_workspace()
            if workspace is None:
                search_error = "Create your Compass before using it for discovery."
            elif integrity_error := compass_action_error(
                workspace,
                CompassAction.EXPLORE_COMPASS,
            ):
                search_error = integrity_error
            else:
                try:
                    discovery_query = discovery_query_from_profile(workspace.session.profile)
                    discovery_query = discovery_query.model_copy(
                        update={
                            "include_remote_jobs": True,
                            "worldwide": worldwide,
                        }
                    )
                    query_text = discovery_query.text
                    resolved_location = discovery_query.location
                    compass_used = True
                except DiscoveryError as exc:
                    search_error = str(exc)
        elif query_text:
            discovery_query = DiscoveryQuery(
                text=query_text,
                location=resolved_location,
                include_remote_jobs=True,
                regional_target=30 if resolved_location else 0,
                worldwide=worldwide,
            )
        account = current_account()
        persona = current_persona()
        if discovery_query is not None and account is not None and persona is not None:
            preferred_portals = container.portal_sources.enabled_portal_urls(
                persona.id,
                account_id=account.id,
            )
            availability = container.provider_availability()
            enabled_keys = container.provider_permissions.enabled_keys(account.id)
            portal_search_available = any(
                key in enabled_keys and availability.get(key, (False, ""))[0]
                for key in ("brave", "exa")
            )
            portals_active = bool(
                include_custom_portals and preferred_portals and portal_search_available
            )
            discovery_query = discovery_query.model_copy(
                update={
                    "include_custom_portals": portals_active,
                    "preferred_portals": preferred_portals if portals_active else [],
                    "preferred_domains": [],
                }
            )
        return (
            discovery_query,
            query_text,
            resolved_location,
            compass_used,
            search_error,
        )

    def explore_provider_activity(
        workflow_id: UUID,
        results: list,
        query: DiscoveryQuery,
    ) -> list[dict[str, object]]:
        """Describe source contributions using metadata only."""

        visible_counts: dict[str, int] = {}
        for result in results:
            providers = getattr(result, "effective_source_providers", ())
            if not providers:
                provider = str(getattr(result, "provider", ""))
                providers = (provider,) if provider else ()
            # One merged vacancy can legitimately count as a contribution from
            # several providers. Repeated provenance on one row counts once.
            for provider in dict.fromkeys(str(item) for item in providers if item):
                visible_counts[provider] = visible_counts.get(provider, 0) + 1
        activity: list[dict[str, object]] = []
        represented_providers: set[str] = set()
        for row in container.operations.breakdown_since(workflow_id=workflow_id):
            if row.purpose != "job-discovery":
                continue
            represented_providers.add(row.provider)
            succeeded = (
                row.total_operations
                - row.failed_operations
                - row.blocked_operations
                - row.pending_operations
            )
            if row.pending_operations:
                status = "Pending"
            elif row.blocked_operations:
                status = "Blocked"
            elif row.failed_operations and succeeded:
                status = "Partly reached"
            elif row.failed_operations:
                status = "Failed"
            else:
                status = "Reached"
            visible = visible_counts.get(row.provider, 0)
            contribution = (
                f"Found {row.result_count} usable job(s); {visible} contributed to these "
                "ranked results."
            )
            guidance = None
            if row.provider == "brave-web" and row.failed_operations:
                guidance = brave_search_failure_guidance(row.failure_types)
            if row.pending_operations:
                guidance = (
                    "This provider has not reached a terminal result. Its conservative "
                    "budget reservation remains recorded until the operation is finalized."
                )
            elif row.blocked_operations:
                guidance = (
                    "The provider safety budget blocked this source before any request. "
                    "Review the operation and cost rails in Operations."
                )
            elif row.failed_operations and guidance is None:
                guidance = (
                    "The source failed without storing its query, URL, response, or key. "
                    "Open Operations for the sanitized failure category."
                )
            activity.append(
                {
                    "provider": row.provider,
                    "label": EXPLORE_PROVIDER_LABELS.get(
                        row.provider,
                        row.provider.replace("-", " ").title(),
                    ),
                    "status": status,
                    "contribution": contribution,
                    "contributed_count": visible,
                    "filterable": visible > 0 and status not in {"Blocked", "Failed"},
                    "guidance": guidance,
                    "failure_types": row.failure_types,
                }
            )
        # Direct/internal sources and older adapters may contribute rows without
        # writing a provider-operation entry. They still need a checked filter,
        # otherwise the presence of any ledger-backed source would hide their
        # cards on first render.
        for provider in sorted(visible_counts.keys() - represented_providers):
            visible = visible_counts[provider]
            activity.append(
                {
                    "provider": provider,
                    "label": EXPLORE_PROVIDER_LABELS.get(
                        provider,
                        provider.replace("-", " ").title(),
                    ),
                    "status": "Included",
                    "contribution": (
                        f"{visible} job(s) contributed to these ranked results. "
                        "This source did not need a separately metered discovery call."
                    ),
                    "contributed_count": visible,
                    "filterable": True,
                    "guidance": None,
                    "failure_types": [],
                }
            )
        if query.include_custom_portals and query.preferred_portals:
            portal_results = sum(
                web_discovery_matches_portal(str(result.source_url), query) for result in results
            )
            included = min(MAX_PORTAL_SEARCH_SCOPES, len(query.preferred_portals))
            activity.append(
                {
                    "provider": "saved-employer-portals",
                    "label": "Saved employer portals",
                    "status": "Included",
                    "contribution": (
                        f"{portal_results} final result(s) belong to the {included} of "
                        f"{len(query.preferred_portals)} enabled saved portal scope(s) "
                        "included in this run. Portal membership does not imply that the "
                        "portal hint caused the result."
                    ),
                    "contributed_count": 0,
                    "filterable": False,
                    "guidance": None,
                    "failure_types": [],
                }
            )
        return activity

    def render_explore(
        request: Request,
        *,
        query_text: str = "",
        location: str = "",
        work_arrangement: str = "Hybrid, remote, and on-site roles",
        compass_used: bool = False,
        hide_remote_only: bool = False,
        worldwide: bool = False,
        include_custom_portals: bool = True,
        results: list | None = None,
        regional_result_count: int = 0,
        search_error: str | None = None,
        provider_activity: list[dict[str, object]] | None = None,
        source_explore_task_id: UUID | None = None,
        snapshot_workspace_id: UUID | None = None,
    ):
        count = stored_count()
        account = current_account()
        persona = current_persona()
        portal_urls = (
            container.portal_sources.enabled_portal_urls(
                persona.id,
                account_id=account.id,
            )
            if account is not None and persona is not None
            else []
        )
        availability = container.provider_availability()
        enabled_keys = (
            container.provider_permissions.enabled_keys(account.id)
            if account is not None
            else frozenset()
        )
        portal_search_available = any(
            key in enabled_keys and availability.get(key, (False, ""))[0]
            for key in ("brave", "exa")
        )
        activity = provider_activity or []
        return templates.TemplateResponse(
            request=request,
            name="explore.html",
            context={
                "query_text": query_text,
                "location": location,
                "work_arrangement": work_arrangement,
                "compass_used": compass_used,
                "hide_remote_only": hide_remote_only,
                "worldwide": worldwide,
                "include_custom_portals": include_custom_portals,
                "custom_portal_count": len(portal_urls),
                "custom_portal_search_available": portal_search_available,
                "results": results or [],
                "regional_result_count": regional_result_count,
                "search_error": search_error,
                "provider_activity": activity,
                "filterable_provider_count": sum(bool(item.get("filterable")) for item in activity),
                "explore_provider_labels": EXPLORE_PROVIDER_LABELS,
                "explore_hidden_source_tags": EXPLORE_HIDDEN_SOURCE_TAGS,
                "provider_attributions": provider_attributions(discovery),
                "source_explore_task_id": source_explore_task_id,
                "enhanced_discovery_enabled": bool(
                    container.settings.brave_search_api_key
                    or container.settings.exa_search_api_key
                    or container.settings.apify_api_token_value
                    or container.settings.greenhouse_boards
                    or container.settings.lever_sites
                    or container.settings.ashby_boards
                ),
                "stored_count": count,
                "max_stored_jobs": container.access_policy.max_stored_jobs,
                "available_slots": max(
                    0,
                    container.access_policy.max_stored_jobs - count,
                ),
                **common(request, "explore"),
            },
        )

    def durable_explore_task(
        *,
        discovery_query: DiscoveryQuery,
        query_text: str,
        location: str,
        compass_used: bool,
        hide_remote_only: bool,
    ):
        workspace = latest_workspace()
        if workspace is None or not background_queue_enabled:
            return None
        task, created = container.background_tasks.get_or_create_active(
            workspace.id,
            BackgroundTaskKind.EXPLORE_SEARCH,
            max_attempts=container.settings.background_task_max_attempts,
        )
        if not created:
            return task
        container.explore_searches.create(
            task_id=task.id,
            workspace_id=workspace.id,
            query=discovery_query,
            query_text=query_text,
            location=location,
            compass_used=compass_used,
            hide_remote_only=hide_remote_only,
        )
        background_worker.wake()
        return task

    def render_completed_explore(request: Request, search):
        return render_explore(
            request,
            query_text=search.query_text,
            location=search.location,
            work_arrangement=search.work_arrangement,
            compass_used=search.compass_used,
            hide_remote_only=search.hide_remote_only,
            worldwide=search.query.worldwide,
            include_custom_portals=search.query.include_custom_portals,
            results=search.results,
            regional_result_count=search.regional_result_count,
            provider_activity=explore_provider_activity(
                search.task_id,
                search.results,
                search.query,
            ),
            source_explore_task_id=search.task_id,
        )

    @app.get("/explore", response_class=HTMLResponse, name="explore")
    async def explore(
        request: Request,
        q: str | None = Query(default=None, max_length=400),
        location: str = Query(default="", max_length=200),
        use_compass: bool = Query(default=False),
        hide_remote_only: bool = Query(default=False),
        worldwide: bool = Query(default=False),
        include_custom_portals: bool = Query(default=True),
        source_explore_task_id: UUID | None = Query(default=None),
    ):
        nonlocal explore_snapshot
        workspace = latest_workspace()
        if workspace is not None and background_queue_enabled:
            active_task = container.background_tasks.find_active(
                workspace.id,
                BackgroundTaskKind.EXPLORE_SEARCH,
            )
            if active_task is not None:
                return RedirectResponse(f"/tasks/{active_task.id}", status_code=303)

        search_requested = use_compass or q is not None
        if not search_requested:
            if workspace is not None:
                if source_explore_task_id is not None:
                    origin_search = container.explore_searches.get(source_explore_task_id)
                    if (
                        origin_search is not None
                        and origin_search.workspace_id == workspace.id
                        and origin_search.completed_at is not None
                    ):
                        return render_completed_explore(request, origin_search)
                saved_search = container.explore_searches.latest_completed(workspace.id)
                if saved_search is not None:
                    return render_completed_explore(request, saved_search)
            if explore_snapshot is not None:
                return render_explore(request, **dict(explore_snapshot))
            return render_explore(request)

        (
            discovery_query,
            query_text,
            resolved_location,
            compass_used,
            search_error,
        ) = prepare_explore_query(
            q=q,
            location=location,
            use_compass=use_compass,
            hide_remote_only=hide_remote_only,
            worldwide=worldwide,
            include_custom_portals=include_custom_portals,
        )
        if discovery_query is None or search_error is not None:
            return render_explore(
                request,
                query_text=query_text,
                location=resolved_location,
                compass_used=compass_used,
                hide_remote_only=hide_remote_only,
                worldwide=worldwide,
                include_custom_portals=include_custom_portals,
                search_error=search_error,
            )

        if workspace is not None and background_queue_enabled:
            saved_search = container.explore_searches.latest_completed(workspace.id)
            if saved_search is not None and saved_search.query == discovery_query:
                return render_completed_explore(request, saved_search)
            task = durable_explore_task(
                discovery_query=discovery_query,
                query_text=query_text,
                location=resolved_location,
                compass_used=compass_used,
                hide_remote_only=hide_remote_only,
            )
            assert task is not None
            return RedirectResponse(f"/tasks/{task.id}", status_code=303)

        explore_workflow_id = uuid4()
        try:
            with provider_operation_scope(explore_workflow_id, "explore-search"):
                results = discovery.search(discovery_query)
            search_error = None
        except (DiscoveryError, RuntimeError, ValueError) as exc:
            results = []
            search_error = str(exc)
        provider_activity = explore_provider_activity(
            explore_workflow_id,
            results,
            discovery_query,
        )
        regional_result_count = getattr(discovery, "last_regional_count", 0)
        if search_error is None:
            explore_snapshot = {
                "query_text": query_text,
                "location": resolved_location,
                "work_arrangement": discovery_query.work_arrangement_label,
                "compass_used": compass_used,
                "hide_remote_only": hide_remote_only,
                "worldwide": worldwide,
                "include_custom_portals": discovery_query.include_custom_portals,
                "results": results,
                "regional_result_count": regional_result_count,
                "search_error": None,
                "provider_activity": provider_activity,
                "snapshot_workspace_id": workspace.id if workspace is not None else None,
            }
        return render_explore(
            request,
            query_text=query_text,
            location=resolved_location,
            work_arrangement=discovery_query.work_arrangement_label,
            compass_used=compass_used,
            hide_remote_only=hide_remote_only,
            worldwide=worldwide,
            include_custom_portals=discovery_query.include_custom_portals,
            results=results,
            regional_result_count=regional_result_count,
            search_error=search_error,
            provider_activity=provider_activity,
        )

    @app.post("/explore/search", name="explore_search")
    async def explore_search(
        q: str | None = Form(default=None, max_length=400),
        location: str = Form(default="", max_length=200),
        use_compass: bool = Form(default=False),
        hide_remote_only: bool = Form(default=False),
        worldwide: bool = Form(default=False),
        include_custom_portals: bool = Form(default=False),
    ):
        nonlocal explore_snapshot
        (
            discovery_query,
            query_text,
            resolved_location,
            compass_used,
            search_error,
        ) = prepare_explore_query(
            q=q,
            location=location,
            use_compass=use_compass,
            hide_remote_only=hide_remote_only,
            worldwide=worldwide,
            include_custom_portals=include_custom_portals,
        )
        if discovery_query is None or search_error is not None:
            return _redirect(
                "/explore",
                error=search_error or "Enter a role, skill, or keyword before searching.",
            )
        task = durable_explore_task(
            discovery_query=discovery_query,
            query_text=query_text,
            location=resolved_location,
            compass_used=compass_used,
            hide_remote_only=hide_remote_only,
        )
        if task is not None:
            return RedirectResponse(f"/tasks/{task.id}", status_code=303)

        explore_workflow_id = uuid4()
        try:
            with provider_operation_scope(explore_workflow_id, "explore-search"):
                results = discovery.search(discovery_query)
        except (DiscoveryError, RuntimeError, ValueError) as exc:
            return _redirect("/explore", error=str(exc))
        provider_activity = explore_provider_activity(
            explore_workflow_id,
            results,
            discovery_query,
        )
        explore_snapshot = {
            "query_text": query_text,
            "location": resolved_location,
            "work_arrangement": discovery_query.work_arrangement_label,
            "compass_used": compass_used,
            "hide_remote_only": hide_remote_only,
            "worldwide": worldwide,
            "include_custom_portals": discovery_query.include_custom_portals,
            "results": results,
            "regional_result_count": getattr(discovery, "last_regional_count", 0),
            "search_error": None,
            "provider_activity": provider_activity,
            "snapshot_workspace_id": (
                current_workspace.id
                if (current_workspace := latest_workspace()) is not None
                else None
            ),
        }
        return _redirect("/explore")

    @app.post("/explore/save", name="explore_save")
    def explore_save(
        selected_urls: list[str] = Form(default=[]),
        destination: str = Form(default="archive"),
        source_explore_task_id: str = Form(default="", max_length=36),
    ):
        nonlocal explore_snapshot
        selected = list(dict.fromkeys(url.strip() for url in selected_urls if url.strip()))
        if not selected:
            return _redirect("/explore", error="Select at least one job first.")
        if destination not in {"archive", "matching"}:
            return _redirect("/explore", error="Unknown Explore action.")
        workspace = latest_workspace()
        if destination == "matching" and workspace is None:
            return _redirect(
                "/explore",
                error="Create your Compass before saving jobs and running Matching.",
            )
        origin_search = None
        origin_task_id: UUID | None = None
        if source_explore_task_id.strip():
            try:
                origin_task_id = UUID(source_explore_task_id.strip())
            except ValueError:
                return _redirect("/explore", error="The Explore result snapshot is invalid.")
            origin_search = container.explore_searches.get(origin_task_id)
            if (
                workspace is None
                or origin_search is None
                or origin_search.workspace_id != workspace.id
                or origin_search.completed_at is None
            ):
                return _redirect(
                    "/explore",
                    error="The Explore result snapshot is not available in this workspace.",
                )
            try:
                selected_identities = {normalize_job_url(url) for url in selected}
                origin_identities = {
                    normalize_job_url(str(job.source_url)) for job in origin_search.results
                }
            except ValueError:
                return _redirect("/explore", error="A selected job URL is invalid.")
            if not selected_identities.issubset(origin_identities):
                return _redirect(
                    "/explore",
                    error="A selected job does not belong to this Explore result snapshot.",
                )
        inline_origin = False
        if origin_search is None and explore_snapshot is not None:
            current_workspace_id = workspace.id if workspace is not None else None
            if explore_snapshot.get("snapshot_workspace_id") == current_workspace_id:
                try:
                    selected_identities = {normalize_job_url(url) for url in selected}
                    inline_identities = {
                        normalize_job_url(str(job.source_url))
                        for job in explore_snapshot.get("results", [])
                    }
                except (AttributeError, ValueError):
                    pass
                else:
                    inline_origin = selected_identities.issubset(inline_identities)

        allowed = accessible_record_ids()

        def is_already_saved(url: str) -> bool:
            existing = container.repository.find_by_urls(url, url)
            return existing is not None and (allowed is None or existing.id in allowed)

        count = stored_count()
        new_urls = [url for url in selected if not is_already_saved(url)]
        available_slots = max(0, container.access_policy.max_stored_jobs - count)
        if len(new_urls) > available_slots:
            return _redirect(
                "/explore",
                error=(
                    f"This selection needs {len(new_urls)} new slots, but only "
                    f"{available_slots} remain. Remove jobs from Archive or Matching, "
                    "or select fewer roles. Nothing was added."
                ),
            )

        if background_queue_enabled and workspace is not None:
            task, created = container.background_job_imports.get_or_create_active(
                workspace.id,
                selected,
                JobImportDestination(destination),
                source_explore_task_id=origin_task_id,
                max_attempts=container.settings.background_task_max_attempts,
            )
            if created:
                background_worker.wake()
            return RedirectResponse(f"/tasks/{task.id}", status_code=303)

        imported = 0
        failures: list[str] = []
        discarded_urls: set[str] = set()
        manual_required_urls: set[str] = set()
        selected_record_ids: set[UUID] = set()
        import_workflow_id = uuid4()
        for url in selected:
            try:
                check_storage_capacity(url)
                with provider_operation_scope(import_workflow_id, "job-import"):
                    result = corpus().import_url(url)
                if result.job is not None and result.kind not in {
                    JobObservationKind.EXPIRED,
                    JobObservationKind.UNREACHABLE,
                    JobObservationKind.EXTRACTION_FAILED,
                }:
                    if result.record is not None:
                        selected_record_ids.add(result.record.id)
                        grant_record(result.record.id)
                    imported += 1
                else:
                    failures.append(
                        result.message or "A selected URL was closed or not a usable live job."
                    )
                    normalized_url = normalize_job_url(url)
                    if result.kind == JobObservationKind.EXPIRED:
                        discarded_urls.add(normalized_url)
                        if result.record is not None and container.settings.auth_mode == "local":
                            corpus().delete_record(result.record.id)
                    elif (
                        result.kind
                        in {
                            JobObservationKind.UNREACHABLE,
                            JobObservationKind.EXTRACTION_FAILED,
                        }
                        or result.manual_input_recommended
                    ):
                        manual_required_urls.add(normalized_url)
                    if (
                        result.record is not None
                        and container.settings.auth_mode == "local"
                        and result.kind != JobObservationKind.EXPIRED
                    ):
                        corpus().delete_record(result.record.id)
            except (JobCorpusError, RuntimeError, ValueError) as exc:
                failures.append(str(exc))
        if discarded_urls:
            if origin_search is not None:
                container.explore_searches.remove_result_urls(
                    origin_search.task_id,
                    discarded_urls,
                )
            elif inline_origin and explore_snapshot is not None:
                explore_snapshot = {
                    **explore_snapshot,
                    "results": [
                        job
                        for job in explore_snapshot.get("results", [])
                        if normalize_job_url(str(job.source_url)) not in discarded_urls
                    ],
                }
        if manual_required_urls:
            if origin_search is not None:
                container.explore_searches.update_result_readiness(
                    origin_search.task_id,
                    manual_required_urls,
                    readiness=SourceReadiness.MANUAL_REQUIRED,
                )
            elif inline_origin and explore_snapshot is not None:
                explore_snapshot = {
                    **explore_snapshot,
                    "results": [
                        job.model_copy(update={"source_readiness": SourceReadiness.MANUAL_REQUIRED})
                        if normalize_job_url(str(job.source_url)) in manual_required_urls
                        else job
                        for job in explore_snapshot.get("results", [])
                    ],
                }
        if imported == 0:
            detail = failures[0] if failures else "No selected job could be imported."
            if len(selected) == 1 and manual_required_urls:
                return RedirectResponse(
                    "/add?"
                    + urlencode({"url": selected[0], "manual": "true"})
                    + "#manual-job-input",
                    status_code=303,
                )
            origin_path = (
                "/explore?" + urlencode({"source_explore_task_id": str(origin_task_id)})
                if origin_task_id is not None
                else "/explore"
            )
            return _redirect(origin_path, error=detail)

        if destination == "matching":
            workspace = latest_workspace()
            assert workspace is not None
            integrity_error = compass_action_error(workspace, CompassAction.MATCH)
            if integrity_error:
                return _redirect(
                    "/matches",
                    error=f"{imported} selected job(s) were saved. {integrity_error}",
                )
            try:
                groups = result_service().run(
                    workspace,
                    record_ids=selected_record_ids,
                )
            except (KeyError, ResultServiceError, RuntimeError, ValueError) as exc:
                return _redirect(
                    "/matches",
                    error=f"{imported} selected job(s) were saved, but Matching needs attention: {exc}",
                )
            return _redirect(
                "/matches",
                notice=(
                    f"{imported} selected job(s) saved and matched: {len(groups.top)} Top, "
                    f"{len(groups.stretch)} Stretch, {len(groups.blocked)} Blocked."
                ),
            )
        notice = f"{imported} selected job(s) saved to Archive."
        if failures:
            notice += f" {len(failures)} selection(s) need another source or check."
        return _redirect("/jobs", notice=notice)

    @app.post("/jobs/import", name="job_import")
    def job_import(url: str = Form(min_length=8, max_length=2_000)):
        try:
            check_storage_capacity(url)
            with provider_operation_scope(uuid4(), "job-import"):
                result = corpus().import_url(url)
        except (JobCorpusError, RuntimeError, ValueError) as exc:
            return _redirect("/jobs", error=str(exc))
        return import_destination(result)

    @app.post("/jobs/{record_id}/delete", name="job_delete")
    def job_delete(record_id: UUID, confirm_delete: bool = Form(default=False)):
        record = next(
            (item for item in accessible_records() if item.id == record_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        if not confirm_delete:
            return _redirect(
                f"/jobs/{record_id}",
                error="Confirm deletion before removing this job and its saved history.",
            )
        if delete_job_records([record_id]) != 1:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return _redirect(
            "/jobs",
            notice="Job, reference settings, match history, and local source copies removed. One slot is free again.",
        )

    @app.post("/jobs/bulk-delete", name="jobs_bulk_delete")
    def jobs_bulk_delete(
        record_ids: list[UUID] = Form(default=[]),
        confirm_delete: bool = Form(default=False),
        return_to: str = Form(default="jobs"),
    ):
        destination = "/matches" if return_to == "matches" else "/jobs"
        unique_ids = list(dict.fromkeys(record_ids))
        if not unique_ids:
            return _redirect(destination, error="Select at least one job to delete.")
        if not confirm_delete:
            return _redirect(
                destination,
                error="Confirm complete deletion before removing the selected jobs.",
            )
        deleted = delete_job_records(unique_ids)
        if deleted == 0:
            return _redirect(destination, error="None of the selected jobs still exists.")
        return _redirect(
            destination,
            notice=(
                f"{deleted} job(s), reference settings, match history, and local source "
                f"copies removed. {deleted} slot(s) are free again."
            ),
        )

    @app.post("/jobs/{record_id}/refresh", name="job_refresh")
    def job_refresh(record_id: UUID):
        record = next(
            (item for item in accessible_records() if item.id == record_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        current_job = container.repository.get_current_job(record.id)
        if current_job is not None and current_job.source_type == JobSourceType.MANUAL_TEXT:
            return _redirect(
                f"/jobs/{record_id}",
                notice="Manual input is never fetched or reverified. Its saved text is unchanged.",
            )
        try:
            with provider_operation_scope(uuid4(), "job-import"):
                result = corpus().import_url(record.canonical_url)
        except (JobCorpusError, RuntimeError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return import_destination(result)

    @app.get("/jobs/{record_id}", response_class=HTMLResponse, name="job_detail")
    async def job_detail(request: Request, record_id: UUID):
        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        workspace = latest_workspace()
        matched = None
        if workspace is not None:
            try:
                matched = result_service().latest_detail(workspace, record_id)
            except ResultAccessError:
                matched = None
        application_drafts = (
            container.application_drafts.list_for_job(workspace.id, record_id)
            if workspace is not None
            else []
        )
        evidence_overrides = (
            container.job_overrides.list_for_job(workspace.id, record_id)
            if workspace is not None
            else []
        )
        employer_rating = None
        source_application_guidance = ApplicationGuidance()
        if detail.job is not None:
            deterministic_guidance = extract_application_guidance(
                detail.job.source_text,
                source_url=str(detail.job.source_url or detail.card.source_url),
            )
            source_application_guidance = merge_application_guidance(
                deterministic_guidance,
                detail.job.application_guidance,
            )
        application_guidance_override = None
        application_guidance = ApplicationGuidance()
        if container.settings.application_guidance_available:
            application_guidance = source_application_guidance
            if workspace is not None:
                application_guidance_override = container.application_guidance.get(
                    workspace.id,
                    record_id,
                )
                application_guidance = container.application_guidance.effective(
                    workspace.id,
                    record_id,
                    source_application_guidance,
                )
        source_application_guidance_items = [
            (label, entry)
            for label, entry in (
                ("Contact name", source_application_guidance.contact_name),
                ("Contact role", source_application_guidance.contact_role),
                ("Application email", source_application_guidance.contact_email),
                ("Application phone", source_application_guidance.contact_phone),
                ("Published address", source_application_guidance.postal_address),
                ("Application channel", source_application_guidance.application_channel),
                ("Application URL", source_application_guidance.application_url),
                ("Maximum file size", source_application_guidance.max_file_size),
                ("Maximum pages", source_application_guidance.max_pages),
                ("Application deadline", source_application_guidance.application_deadline),
            )
            if entry is not None
        ]
        source_application_guidance_items.extend(
            ("Requested document", entry)
            for entry in source_application_guidance.requested_documents
        )
        source_application_guidance_items.extend(
            ("Application instruction", entry) for entry in source_application_guidance.instructions
        )
        context_overrides = {
            override.target_key: override
            for override in evidence_overrides
            if override.kind == JobEvidenceOverrideKind.CONTEXT
        }
        employer_type_override = context_overrides.get(CONTEXT_EMPLOYER_TYPES)

        def inferred_employer_types(employer, intelligence) -> set[str]:
            inferred: set[str] = set()
            if employer is not None:
                mapped = {
                    EmployerKind.STAFFING_AGENCY: "staffing_recruiting",
                    EmployerKind.RECRUITMENT_AGENCY: "staffing_recruiting",
                    EmployerKind.CONSULTANCY: "consultancy",
                    EmployerKind.PLATFORM: "platform_marketplace",
                }.get(employer.kind)
                if mapped:
                    inferred.add(mapped)
            if intelligence is None:
                return inferred
            company_material = " ".join(
                [
                    intelligence.product.revenue_model,
                    intelligence.product.summary,
                    *intelligence.product.categories,
                ]
            ).casefold()
            type_markers = {
                "producer_manufacturer": ("manufactur", "producer", "industrial"),
                "product_company": ("product company", "software product", "saas"),
                "consultancy": ("consult", "project delivery"),
                "professional_services": ("professional service", "service provider"),
                "staffing_recruiting": ("staffing", "recruit", "temporary employment"),
                "platform_marketplace": ("platform", "marketplace"),
                "healthcare_provider": (
                    "hospital",
                    "clinic",
                    "healthcare",
                    "care provider",
                ),
                "education_research": ("university", "research", "education", "school"),
                "public_sector": ("public sector", "municipal", "government"),
                "non_profit": ("non-profit", "nonprofit", "charity"),
                "association": ("association", "federation"),
                "startup_scaleup": ("start-up", "startup", "scale-up", "scaleup"),
                "retail_hospitality": ("retail", "hospitality", "hotel", "restaurant"),
                "logistics_transport": ("logistics", "transport", "mobility"),
                "financial_services": ("bank", "insurance", "financial service", "fintech"),
            }
            inferred.update(
                key
                for key, markers in type_markers.items()
                if any(marker in company_material for marker in markers)
            )
            return inferred

        automatic_employer_types: set[str] = set()
        effective_employer_types: set[str] = set()
        if matched is not None:
            result = matched.item.stored.result
            automatic_employer_types = inferred_employer_types(
                result.employer_assessment,
                result.company_intelligence,
            )
            effective_employer_types = inferred_employer_types(
                result.effective_employer_assessment or result.employer_assessment,
                result.effective_company_intelligence or result.company_intelligence,
            )
        if employer_type_override and employer_type_override.text_value:
            selected_employer_types = {
                value.strip()
                for value in employer_type_override.text_value.split(",")
                if value.strip()
            }
        else:
            selected_employer_types = effective_employer_types
        employer_name = effective_employer_name(record_id, detail.card.company)
        shared_employer_context = None
        if workspace is not None and employer_name is not None:
            try:
                _, employer_key = normalize_employer_name(employer_name)
                opportunities = dashboard_for_current().list_opportunities()
                overrides_by_record = container.job_overrides.list_for_jobs(
                    workspace.id,
                    {opportunity.record_id for opportunity in opportunities},
                )
                candidates = []
                for opportunity in opportunities:
                    candidate_name = effective_employer_name(
                        opportunity.record_id,
                        opportunity.company,
                    )
                    if candidate_name is None:
                        continue
                    _, candidate_key = normalize_employer_name(candidate_name)
                    if candidate_key != employer_key:
                        continue
                    candidates.extend(
                        override
                        for override in overrides_by_record.get(opportunity.record_id, [])
                        if override.kind == JobEvidenceOverrideKind.CONTEXT
                        and override.target_key == CONTEXT_REPUTATION_SUMMARY
                        and override.text_value
                    )
                shared_employer_context = max(
                    candidates,
                    key=lambda override: override.updated_at,
                    default=None,
                )
            except EmployerReputationError:
                shared_employer_context = None
        if (
            shared_employer_context is not None
            and CONTEXT_REPUTATION_SUMMARY not in context_overrides
        ):
            context_overrides[CONTEXT_REPUTATION_SUMMARY] = shared_employer_context
        account = current_account()
        persona = current_persona()
        job_rating = current_job_ratings().get(record_id)
        persona_compass_skill_presence: dict[str, bool] = {}
        if workspace is not None and matched is not None:
            persona_compass_skill_presence = {
                skill.casefold(): skill_is_evidenced_by_profile(
                    workspace.session.profile,
                    skill,
                )
                for skill in [
                    *matched.item.stored.result.matched_required_skills,
                    *matched.item.stored.result.missing_required_skills,
                ]
            }
        if account is not None and persona is not None and employer_name is not None:
            try:
                employer_rating = container.employer_reputation.get(
                    persona.id,
                    employer_name,
                    account_id=account.id,
                )
            except EmployerReputationError:
                employer_rating = None
        score_sections = {
            section.key: section
            for section in (
                matched.item.stored.result.score_mechanics.sections
                if matched and matched.item.stored.result.score_mechanics
                else []
            )
        }
        match_only_allowed = False
        match_only_reason = None
        if matched is None and detail.job is not None and detail.card.source_is_manual:
            if workspace is None:
                match_only_reason = "Create or select a Compass before matching this job."
            elif integrity_error := compass_action_error(workspace, CompassAction.MATCH):
                match_only_reason = integrity_error
            else:
                status = result_service().match_only_status(workspace, record_id)
                match_only_allowed = status.allowed
                match_only_reason = None if status.allowed else status.reason
        previous_match = None
        next_match = None
        detail_navigation = None
        if matched is not None:
            match_navigation = [
                candidate
                for candidate in [
                    *matched.groups.top,
                    *matched.groups.stretch,
                    *matched.groups.blocked,
                ]
                if candidate.accessible
            ]
            current_index = next(
                (
                    index
                    for index, candidate in enumerate(match_navigation)
                    if candidate.record.id == record_id
                ),
                None,
            )
            if current_index is not None:
                if len(match_navigation) > 1:
                    previous_match = match_navigation[(current_index - 1) % len(match_navigation)]
                    next_match = match_navigation[(current_index + 1) % len(match_navigation)]
                detail_navigation = {
                    "previous_url": (
                        f"/jobs/{previous_match.record.id}" if previous_match else None
                    ),
                    "next_url": f"/jobs/{next_match.record.id}" if next_match else None,
                    "position": current_index + 1,
                    "total": len(match_navigation),
                }
        return templates.TemplateResponse(
            request=request,
            name="job_detail.html",
            headers={"Cache-Control": "no-store"},
            context={
                "detail": detail,
                "matched": matched,
                "source_guidance": (
                    None
                    if detail.card.source_is_manual
                    else source_guidance(detail.card.source_url)
                ),
                "feedback_labels": FEEDBACK_LABELS,
                "application_labels": APPLICATION_LABELS,
                "application_drafts": application_drafts,
                "max_application_drafts": MAX_APPLICATION_DRAFTS_PER_JOB,
                "evidence_overrides": evidence_overrides,
                "reason_overrides": {
                    override.target_key: override
                    for override in evidence_overrides
                    if override.kind == JobEvidenceOverrideKind.REASON
                },
                "commute_overrides": {
                    override.target_key: override
                    for override in evidence_overrides
                    if override.kind == JobEvidenceOverrideKind.COMMUTE_MINUTES
                },
                "skill_overrides": {
                    override.target_key: override
                    for override in evidence_overrides
                    if override.kind == JobEvidenceOverrideKind.SKILL
                },
                "posting_date_override": next(
                    (
                        override
                        for override in evidence_overrides
                        if override.kind == JobEvidenceOverrideKind.POSTING_DATE
                        and override.target_key == "posting_date"
                    ),
                    None,
                ),
                "context_overrides": context_overrides,
                "score_sections": score_sections,
                "context_keys": {
                    "employer_relationship": CONTEXT_EMPLOYER_RELATIONSHIP,
                    "company_name": CONTEXT_COMPANY_NAME,
                    "company_revenue": CONTEXT_COMPANY_REVENUE_MODEL,
                    "company_summary": CONTEXT_COMPANY_SUMMARY,
                    "company_categories": CONTEXT_COMPANY_CATEGORIES,
                    "employer_types": CONTEXT_EMPLOYER_TYPES,
                    "reputation_summary": CONTEXT_REPUTATION_SUMMARY,
                    "salary_range": CONTEXT_SALARY_RANGE,
                    "work_mode_prefix": CONTEXT_WORK_MODE_PREFIX,
                },
                "effective_employer_name": employer_name,
                "display_employer_name": employer_name or detail.card.company,
                "employer_identity_resolved": employer_name is not None,
                "shared_employer_context": (
                    shared_employer_context
                    if shared_employer_context is not None
                    and shared_employer_context.job_record_id != record_id
                    else None
                ),
                "employer_rating": employer_rating,
                "employer_type_options": EMPLOYER_TYPE_OPTIONS,
                "automatic_employer_types": automatic_employer_types,
                "selected_employer_types": selected_employer_types,
                "job_rating": job_rating,
                "persona_compass_skill_presence": persona_compass_skill_presence,
                "also_update_compass_skills": (
                    persona.also_update_compass_skills if persona is not None else True
                ),
                "application_guidance_enabled": (container.settings.application_guidance_available),
                "application_guidance": application_guidance,
                "application_guidance_override": application_guidance_override,
                "source_application_guidance": source_application_guidance,
                "application_job_page_url": (
                    str(detail.card.source_url)
                    if not application_guidance.application_url
                    and detail.card.source_is_verified
                    and not detail.card.source_is_manual
                    else None
                ),
                "source_application_guidance_items": source_application_guidance_items,
                "previous_match": previous_match,
                "next_match": next_match,
                "detail_navigation": detail_navigation,
                "evidence_rematch_pending": request.query_params.get("rematch") == "1",
                "match_only_allowed": match_only_allowed,
                "match_only_reason": match_only_reason,
                **common(request, "matches" if matched else "jobs"),
            },
        )

    @app.post(
        "/jobs/{record_id}/application-guidance",
        name="job_application_guidance_save",
    )
    async def job_application_guidance_save(
        record_id: UUID,
        contact_name: str = Form(default="", max_length=300),
        contact_role: str = Form(default="", max_length=300),
        contact_email: str = Form(default="", max_length=320),
        contact_phone: str = Form(default="", max_length=100),
        postal_address: str = Form(default="", max_length=500),
        application_channel: str = Form(default="", max_length=40),
        application_url: str = Form(default="", max_length=2_000),
        requested_documents: str = Form(default="", max_length=2_000),
        max_file_size: str = Form(default="", max_length=100),
        max_pages: str = Form(default="", max_length=20),
        application_deadline: str = Form(default="", max_length=200),
        instructions: str = Form(default="", max_length=5_000),
    ):
        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        workspace = latest_workspace()
        if workspace is None:
            return _redirect(
                f"/jobs/{record_id}",
                error="Create or select a persona before editing application guidance.",
                fragment="application-guidance",
            )
        if not container.settings.application_guidance_available:
            return _redirect(
                f"/jobs/{record_id}",
                error=(
                    "Application contact processing is unavailable until the legal and "
                    "processor reviews are complete."
                ),
                fragment="application-guidance",
            )
        try:
            parsed_channel = (
                ApplicationChannel(application_channel) if application_channel else None
            )
            clean_pages = max_pages.strip()
            parsed_pages = int(clean_pages) if clean_pages else None
            container.application_guidance.save(
                workspace.id,
                record_id,
                edited_fields=set(ApplicationGuidanceField),
                contact_name=contact_name,
                contact_role=contact_role,
                contact_email=contact_email,
                contact_phone=contact_phone,
                postal_address=postal_address,
                application_channel=parsed_channel,
                application_url=application_url,
                requested_documents=tuple(requested_documents.splitlines()),
                max_file_size=max_file_size,
                max_pages=parsed_pages,
                application_deadline=application_deadline,
                instructions=tuple(instructions.splitlines()),
            )
        except (TypeError, ValueError) as exc:
            return _redirect(
                f"/jobs/{record_id}",
                error=str(exc),
                fragment="application-guidance",
            )
        return _redirect(
            f"/jobs/{record_id}",
            notice=(
                "Your private contact and application-process corrections were saved. "
                "Nothing was sent or submitted."
            ),
            fragment="application-guidance",
        )

    @app.post(
        "/jobs/{record_id}/application-guidance/restore",
        name="job_application_guidance_restore",
    )
    async def job_application_guidance_restore(record_id: UUID):
        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Persona workspace not found")
        container.application_guidance.delete(workspace.id, record_id)
        return _redirect(
            f"/jobs/{record_id}",
            notice="Your corrections were removed; source-published values are shown again.",
            fragment="application-guidance",
        )

    def fast_rescore_saved_job(record_id: UUID) -> RatingProjection:
        workspace = latest_workspace()
        if workspace is None:
            return RatingProjection.no_latest_match()
        return result_service().project_job_rating_from_stored_evidence(
            workspace,
            record_id,
        )

    def fast_rescore_employer(record_id: UUID, employer_name: str) -> RatingProjection:
        workspace = latest_workspace()
        if workspace is None:
            return RatingProjection.no_latest_match()
        return result_service().project_employer_rating_from_stored_evidence(
            workspace,
            record_id,
            employer_name,
        )

    def score_update_payload(rescored_by_record) -> list[dict[str, object]]:
        labels = {
            MatchDisposition.TOP: "Top match",
            MatchDisposition.STRETCH: "Stretch match",
            MatchDisposition.BLOCKED: "Blocked by a boundary",
        }
        return [
            {
                "record_id": str(record_id),
                "score": result.score,
                "disposition": result.disposition.value,
                "disposition_label": labels[result.disposition],
            }
            for record_id, result in rescored_by_record.items()
        ]

    def match_layout_payload() -> dict[str, object] | None:
        """Return the exact visible order currently persisted for Matching."""

        workspace = latest_workspace()
        groups = result_service().latest(workspace) if workspace is not None else None
        if groups is None:
            return None
        ordered_items: list[dict[str, object]] = []
        for disposition, items in (
            (MatchDisposition.TOP, groups.top),
            (MatchDisposition.STRETCH, groups.stretch),
            (MatchDisposition.BLOCKED, groups.blocked),
        ):
            for group_position, item in enumerate(items, start=1):
                ordered_items.append(
                    {
                        "record_id": str(item.record.id),
                        "position": item.stored.position,
                        "group_position": group_position,
                        "score": item.stored.result.score,
                        "disposition": disposition.value,
                        "disposition_label": item.disposition_label,
                    }
                )
        return {
            "run_id": str(groups.run.id),
            "items": ordered_items,
            "counts": {
                "top": len(groups.top),
                "stretch": len(groups.stretch),
                "blocked": len(groups.blocked),
            },
        }

    def opportunity_layout_payload() -> dict[str, object]:
        """Return canonical card values and order for Home and Archive."""

        opportunities = dashboard_for_current().list_opportunities()
        items = [
            {
                "record_id": str(item.record_id),
                "score": item.score,
                "disposition": item.disposition.value if item.disposition is not None else None,
                "disposition_label": item.disposition_label,
            }
            for item in opportunities
        ]
        home_order = [
            str(item.record_id)
            for item in opportunities
            if item.availability == JobAvailability.LIVE
            and item.disposition in {MatchDisposition.TOP, MatchDisposition.STRETCH}
            and item.application_state
            not in {ApplicationState.REJECTED, ApplicationState.WITHDRAWN}
        ]
        return {
            "items": items,
            "archive_order": [str(item.record_id) for item in opportunities],
            "home_order": home_order,
        }

    def safe_rating_layouts(record_id: UUID) -> tuple[object, object, str | None]:
        """Build optional UI projections without invalidating a saved rating."""

        warning = None
        match_layout = None
        opportunity_layout = None
        try:
            match_layout = match_layout_payload()
        except Exception:
            logger.exception("Could not project the saved rating into Match for %s", record_id)
            warning = (
                "The rating was saved, but the current Match layout could not be loaded. "
                "Refresh to load it."
            )
        try:
            opportunity_layout = opportunity_layout_payload()
        except Exception:
            logger.exception("Could not project the saved rating into cards for %s", record_id)
            warning = (
                "The rating was saved, but the current card layout could not be loaded. "
                "Refresh to load it."
            )
        return match_layout, opportunity_layout, warning

    def rating_record_ids_for_employer(employer_name: str) -> list[str]:
        try:
            _, target_key = normalize_employer_name(employer_name)
        except EmployerReputationError:
            return []
        record_ids: list[str] = []
        for opportunity in dashboard_for_current().list_opportunities():
            candidate_name = effective_employer_name(
                opportunity.record_id,
                opportunity.company,
            )
            if candidate_name is None:
                continue
            try:
                _, candidate_key = normalize_employer_name(candidate_name)
            except EmployerReputationError:
                continue
            if candidate_key == target_key:
                record_ids.append(str(opportunity.record_id))
        return record_ids

    def employer_rating_response(
        request: Request,
        record_id: UUID,
        *,
        employer_name: str,
        stars: int | None,
        message: str,
    ):
        try:
            projection = fast_rescore_employer(record_id, employer_name)
        except Exception:
            logger.exception("Could not quickscore a saved employer rating for %s", record_id)
            projection = RatingProjection.failed()
        rescored_by_record = projection.results
        projection_warning = projection.warning
        rescored = rescored_by_record.get(record_id)
        try:
            rating_record_ids = rating_record_ids_for_employer(employer_name)
        except Exception:
            logger.exception("Could not synchronize employer rating controls for %s", record_id)
            rating_record_ids = [str(record_id)]
            projection_warning = (
                projection_warning
                or "The rating was saved, but its peer controls could not be synchronized."
            )
        match_layout, opportunity_layout, layout_warning = safe_rating_layouts(record_id)
        projection_warning = projection_warning or layout_warning
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                {
                    "stars": stars,
                    "label": "Not rated" if stars is None else f"{stars}/5",
                    "message": message,
                    # Kept for older clients. A felt rating never requires an
                    # evidence rematch; an existing Match is rescored locally.
                    "needs_rematch": False,
                    "rematch_url": None,
                    "score": rescored.score if rescored is not None else None,
                    "disposition": (rescored.disposition.value if rescored is not None else None),
                    "score_updates": score_update_payload(rescored_by_record),
                    "rating_record_ids": rating_record_ids,
                    "match_layout": match_layout,
                    "opportunity_layout": opportunity_layout,
                    "match_layout_updated": bool(rescored_by_record),
                    "projection_status": projection.status.value,
                    "projection_warning": projection_warning,
                    "ranking_warning": projection_warning,
                }
            )
        return _redirect(
            f"/jobs/{record_id}",
            notice=f"{message} {projection_warning}" if projection_warning else message,
            fragment="employer-reputation",
        )

    @app.post("/jobs/{record_id}/employer-rating", name="job_employer_rating")
    async def job_employer_rating(
        request: Request,
        record_id: UUID,
        stars: int = Form(ge=0, le=5),
    ):
        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        employer_name = effective_employer_name(record_id, detail.card.company)
        if employer_name is None:
            raise HTTPException(
                status_code=400,
                detail="Set a specific employer name before rating this employer.",
            )
        try:
            container.employer_reputation.set_rating(
                persona.id,
                employer_name,
                stars,
                account_id=account.id,
            )
        except EmployerReputationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        notice = (
            "Your private 0-star employer compatibility rating was saved."
            if stars == 0
            else f"Your private employer rating was saved as {stars} of 5 stars."
        )
        return employer_rating_response(
            request,
            record_id,
            employer_name=employer_name,
            stars=stars,
            message=notice,
        )

    @app.post(
        "/jobs/{record_id}/employer-rating/clear",
        name="job_employer_rating_clear",
    )
    async def job_employer_rating_clear(request: Request, record_id: UUID):
        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        employer_name = effective_employer_name(record_id, detail.card.company)
        if employer_name is None:
            raise HTTPException(
                status_code=400,
                detail="Set a specific employer name before clearing its rating.",
            )
        try:
            container.employer_reputation.clear(
                persona.id,
                employer_name,
                account_id=account.id,
            )
        except EmployerReputationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return employer_rating_response(
            request,
            record_id,
            employer_name=employer_name,
            stars=None,
            message=("Your private employer rating was cleared."),
        )

    def job_rating_response(
        request: Request,
        record_id: UUID,
        *,
        stars: int | None,
        message: str,
    ):
        try:
            projection = fast_rescore_saved_job(record_id)
        except Exception:
            logger.exception("Could not quickscore a saved job rating for %s", record_id)
            projection = RatingProjection.failed()
        rescored_by_record = projection.results
        rescored = rescored_by_record.get(record_id)
        projection_warning = projection.warning
        match_layout, opportunity_layout, layout_warning = safe_rating_layouts(record_id)
        projection_warning = projection_warning or layout_warning
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                {
                    "stars": stars,
                    "label": "Not rated" if stars is None else f"{stars}/5",
                    "message": message,
                    "needs_rematch": False,
                    "rematch_url": None,
                    "score": rescored.score if rescored is not None else None,
                    "disposition": (rescored.disposition.value if rescored is not None else None),
                    "score_updates": score_update_payload(rescored_by_record),
                    "rating_record_ids": [str(record_id)],
                    "match_layout": match_layout,
                    "opportunity_layout": opportunity_layout,
                    "match_layout_updated": rescored is not None,
                    "projection_status": projection.status.value,
                    "projection_warning": projection_warning,
                    "ranking_warning": projection_warning,
                }
            )
        return _redirect(
            f"/jobs/{record_id}",
            notice=f"{message} {projection_warning}" if projection_warning else message,
            fragment="evidence-rematch",
        )

    @app.post("/jobs/{record_id}/job-rating", name="job_rating")
    async def job_rating(
        request: Request,
        record_id: UUID,
        stars: int = Form(ge=0, le=5),
    ):
        if dashboard_for_current().opportunity_detail(record_id) is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        try:
            rating = container.job_ratings.set_rating(
                persona.id,
                record_id,
                stars,
                account_id=account.id,
            )
        except PersonaJobRatingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        message = (
            "Your private 0-star job compatibility rating was saved."
            if stars == 0
            else f"Your private job rating was saved as {stars} of 5."
        )
        return job_rating_response(
            request,
            record_id,
            stars=rating.stars,
            message=message,
        )

    @app.post("/jobs/{record_id}/job-rating/clear", name="job_rating_clear")
    async def job_rating_clear(request: Request, record_id: UUID):
        if dashboard_for_current().opportunity_detail(record_id) is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        try:
            container.job_ratings.clear(
                persona.id,
                record_id,
                account_id=account.id,
            )
        except PersonaJobRatingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return job_rating_response(
            request,
            record_id,
            stars=None,
            message=("Your private job rating was cleared."),
        )

    def editable_match_detail(record_id: UUID):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Persona workspace not found")
        try:
            detail = result_service().latest_detail(workspace, record_id)
        except ResultAccessError as exc:
            raise HTTPException(status_code=404, detail="Match not found") from exc
        if detail is None:
            raise HTTPException(status_code=404, detail="Match not found")
        return workspace, detail

    def evidence_rescore_redirect(
        workspace,
        record_id: UUID,
        *,
        notice: str,
        fragment: str = "evidence-heading",
    ):
        try:
            result_service().rescore_from_stored_evidence(workspace, record_id)
        except ResultServiceError as exc:
            return _redirect(
                f"/jobs/{record_id}",
                error=f"The correction was saved, but the score was not updated: {exc}",
                fragment=fragment,
            )
        return _redirect(
            f"/jobs/{record_id}",
            notice=f"{notice} The compatibility score was updated.",
            fragment=fragment,
        )

    @app.post("/jobs/{record_id}/evidence/bulk", name="job_evidence_bulk")
    async def job_evidence_bulk(request: Request, record_id: UUID):
        """Validate the complete editor payload before atomically storing changes."""

        workspace, detail = editable_match_detail(record_id)
        form = await request.form()
        kinds = [str(value) for value in form.getlist("evidence_kind")]
        keys = [str(value) for value in form.getlist("evidence_key")]
        values = [str(value) for value in form.getlist("evidence_value")]
        initial_values = [str(value) for value in form.getlist("evidence_initial")]
        account = current_account()
        persona = current_persona()
        preference_field_present = form.get("also_update_compass_skills_present") == "true"
        also_update_compass_skills = (
            form.get("also_update_compass_skills") == "true"
            if preference_field_present
            else bool(persona and persona.also_update_compass_skills)
        )
        preference_changed = bool(
            preference_field_present
            and account is not None
            and persona is not None
            and persona.also_update_compass_skills != also_update_compass_skills
        )
        lengths = {len(kinds), len(keys), len(values), len(initial_values)}
        if len(lengths) != 1 or not kinds or len(kinds) > 100:
            return _redirect(
                f"/jobs/{record_id}",
                error="The evidence edit payload was incomplete. Nothing was saved.",
                fragment="evidence-heading",
            )

        result = detail.item.stored.result
        reason_labels = {str(item.profile_fact_id): item.profile_value for item in result.reasons}
        commute_labels = {
            str(item.profile_fact_id): (f"{item.mode.value.title()} commute to {item.destination}")
            for item in result.commutes
        }
        skill_labels = {
            item.casefold(): item
            for item in [
                *result.matched_required_skills,
                *result.missing_required_skills,
            ]
        }
        context_labels: dict[str, str] = {}
        context_labels[CONTEXT_COMPANY_NAME] = "Employer name"
        context_labels[CONTEXT_EMPLOYER_TYPES] = "Employer types"
        if result.employer_assessment is not None:
            context_labels[CONTEXT_EMPLOYER_RELATIONSHIP] = "Employer relationship"
        intelligence = result.company_intelligence
        if intelligence is not None:
            context_labels.update(
                {
                    CONTEXT_COMPANY_REVENUE_MODEL: "Company revenue model",
                    CONTEXT_COMPANY_SUMMARY: "Company product summary",
                    CONTEXT_COMPANY_CATEGORIES: "Company product categories",
                    CONTEXT_REPUTATION_SUMMARY: "Employer reputation context",
                }
            )
        context_labels[CONTEXT_SALARY_RANGE] = "Annual salary orientation in EUR"
        for fact in result.derived_work_mode_facts:
            context_labels[f"{CONTEXT_WORK_MODE_PREFIX}{fact.key}"] = (
                f"Working-mode evidence: {fact.key.replace('_', ' ')}"
            )

        pending: list[JobEvidenceOverride] = []
        try:
            for kind_value, target_key, raw_value, initial in zip(
                kinds,
                keys,
                values,
                initial_values,
                strict=True,
            ):
                if raw_value == initial:
                    continue
                kind = JobEvidenceOverrideKind(kind_value)
                common_fields = {
                    "workspace_id": workspace.id,
                    "job_record_id": record_id,
                    "kind": kind,
                    "target_key": target_key,
                }
                if kind == JobEvidenceOverrideKind.REASON:
                    label = reason_labels[target_key]
                    pending.append(
                        JobEvidenceOverride(
                            **common_fields,
                            target_label=label,
                            reason_value=ReasonOverrideValue(raw_value),
                        )
                    )
                elif kind == JobEvidenceOverrideKind.COMMUTE_MINUTES:
                    label = commute_labels[target_key]
                    pending.append(
                        JobEvidenceOverride(
                            **common_fields,
                            target_label=label,
                            commute_minutes=int(raw_value),
                        )
                    )
                elif kind == JobEvidenceOverrideKind.SKILL:
                    label = skill_labels[target_key.casefold()]
                    common_fields["target_key"] = label.casefold()
                    pending.append(
                        JobEvidenceOverride(
                            **common_fields,
                            target_label=label,
                            skill_value=SkillOverrideValue(raw_value),
                        )
                    )
                elif kind == JobEvidenceOverrideKind.POSTING_DATE:
                    if target_key != "posting_date" or result.posting_date is None:
                        raise KeyError(target_key)
                    pending.append(
                        JobEvidenceOverride(
                            **common_fields,
                            target_label="Posting date",
                            posting_date=date.fromisoformat(raw_value),
                        )
                    )
                elif kind == JobEvidenceOverrideKind.CONTEXT:
                    label = context_labels[target_key]
                    clean_value = raw_value.strip()
                    if not clean_value or len(clean_value) > 2_000:
                        raise ValueError("context evidence must contain 1–2000 characters")
                    if target_key == CONTEXT_EMPLOYER_RELATIONSHIP:
                        try:
                            EmployerKind(clean_value)
                        except ValueError as exc:
                            raise ValueError("unknown employer relationship") from exc
                    if target_key == CONTEXT_COMPANY_NAME:
                        if resolved_employer_name(clean_value) is None:
                            raise ValueError(
                                "enter a specific employer name rather than a placeholder"
                            )
                    if (
                        target_key == CONTEXT_REPUTATION_SUMMARY
                        and effective_employer_name(
                            record_id,
                            detail.item.stored.job.company,
                        )
                        is None
                    ):
                        raise ValueError(
                            "set a specific employer name before saving shared employer context"
                        )
                    if target_key == CONTEXT_SALARY_RANGE:
                        match = re.fullmatch(r"\s*(\d{1,7})\s*:\s*(\d{1,7})\s*", clean_value)
                        if match is None:
                            raise ValueError(
                                "salary range must use min:max, for example 55000:70000"
                            )
                        minimum, maximum = (int(value) for value in match.groups())
                        if minimum < 0 or maximum < minimum or maximum > 300_000:
                            raise ValueError("salary range is outside the supported annual range")
                    pending.append(
                        JobEvidenceOverride(
                            **common_fields,
                            target_label=label,
                            text_value=clean_value,
                        )
                    )
                else:
                    raise ValueError("unsupported evidence type")
            container.job_overrides.upsert_many(pending)
        except (KeyError, TypeError, ValueError) as exc:
            return _redirect(
                f"/jobs/{record_id}",
                error=f"No evidence changes were saved: {exc}",
                fragment="evidence-heading",
            )
        if preference_changed and account is not None and persona is not None:
            try:
                container.personas.set_skill_compass_update_preference(
                    persona.id,
                    also_update_compass_skills,
                    account_id=account.id,
                )
            except PersonaError as exc:
                return _redirect(
                    f"/jobs/{record_id}",
                    error=f"Evidence was saved, but the Compass preference was not: {exc}",
                    fragment="evidence-heading",
                )
        if not pending and not preference_changed:
            return _redirect(
                f"/jobs/{record_id}",
                notice="No evidence values changed.",
                fragment="evidence-heading",
            )

        compass_skills_added: list[str] = []
        if also_update_compass_skills:
            confirmed_values = {
                " ".join(str(value).split()).casefold()
                for fact in workspace.session.profile.confirmed_candidate_evidence
                for value in (fact.value if isinstance(fact.value, list) else [fact.value])
            }
            for override in pending:
                if (
                    override.kind != JobEvidenceOverrideKind.SKILL
                    or override.skill_value != SkillOverrideValue.MATCHED
                ):
                    continue
                normalized = " ".join(override.target_label.split()).casefold()
                if normalized in confirmed_values:
                    continue
                workspace.session.profile.facts.append(
                    ProfileFact(
                        key="skill.demonstrated",
                        value=override.target_label,
                        level=RequirementLevel.OPEN,
                        evidence_status=EvidenceStatus.CONFIRMED,
                        confidence=Confidence.HIGH,
                        source=SourceExcerpt(
                            section=ProfileSection.EXPERIENCE,
                            text=(
                                "Explicitly confirmed from a required skill check: "
                                f"{override.target_label}"
                            ),
                        ),
                        user_note="Added explicitly from bulk job-evidence corrections",
                        needs_confirmation=False,
                    )
                )
                confirmed_values.add(normalized)
                compass_skills_added.append(override.target_label)
            if compass_skills_added:
                now = datetime.now(timezone.utc)
                workspace.session.profile.updated_at = now
                workspace.session.updated_at = now
                container.workspaces.save(workspace)
        rescored = None
        rescore_error = None
        if pending:
            try:
                rescored = result_service().rescore_from_stored_evidence(
                    workspace,
                    record_id,
                )
            except ResultServiceError as exc:
                rescore_error = str(exc)
        return _redirect(
            f"/jobs/{record_id}",
            notice=(
                (
                    f"{len(pending)} private evidence correction(s) saved together. "
                    if pending
                    else "Your skill-to-Compass preference was saved. "
                )
                + (
                    f"{len(compass_skills_added)} newly confirmed skill(s) were also added "
                    "to this persona’s Compass. Run complete Match to apply that persona-wide "
                    "change."
                    if compass_skills_added
                    else (
                        "Its compatibility score was updated."
                        if rescored is not None
                        else (
                            f"The correction is saved, but the score could not be updated: "
                            f"{rescore_error}"
                        )
                        if pending
                        else "It will be reused on this persona’s Job Detail pages."
                    )
                )
            ),
            fragment="evidence-heading" if pending else "required-skills",
        )

    @app.post("/jobs/{record_id}/evidence/reason", name="job_evidence_reason")
    async def job_evidence_reason(
        record_id: UUID,
        target_key: str = Form(min_length=1, max_length=500),
        value: str = Form(),
    ):
        workspace, detail = editable_match_detail(record_id)
        reason = next(
            (
                item
                for item in detail.item.stored.result.reasons
                if str(item.profile_fact_id) == target_key
            ),
            None,
        )
        if reason is None:
            return _redirect(f"/jobs/{record_id}", error="Evidence check not found.")
        try:
            reason_value = ReasonOverrideValue(value)
            container.job_overrides.upsert(
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record_id,
                    kind=JobEvidenceOverrideKind.REASON,
                    target_key=target_key,
                    target_label=reason.profile_value,
                    reason_value=reason_value,
                )
            )
        except (KeyError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return evidence_rescore_redirect(
            workspace,
            record_id,
            notice="Correction saved.",
        )

    @app.post("/jobs/{record_id}/evidence/commute", name="job_evidence_commute")
    async def job_evidence_commute(
        record_id: UUID,
        target_key: str = Form(min_length=1, max_length=500),
        minutes: int = Form(ge=1, le=360),
    ):
        workspace, detail = editable_match_detail(record_id)
        commute = next(
            (
                item
                for item in detail.item.stored.result.commutes
                if str(item.profile_fact_id) == target_key
            ),
            None,
        )
        if commute is None:
            return _redirect(f"/jobs/{record_id}", error="Commute check not found.")
        try:
            container.job_overrides.upsert(
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record_id,
                    kind=JobEvidenceOverrideKind.COMMUTE_MINUTES,
                    target_key=target_key,
                    target_label=f"{commute.mode.value.title()} commute to {commute.destination}",
                    commute_minutes=minutes,
                )
            )
        except (KeyError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return evidence_rescore_redirect(
            workspace,
            record_id,
            notice="Correction saved.",
        )

    @app.post("/jobs/{record_id}/evidence/skill", name="job_evidence_skill")
    async def job_evidence_skill(
        record_id: UUID,
        skill: str = Form(min_length=1, max_length=500),
        value: str = Form(),
    ):
        workspace, detail = editable_match_detail(record_id)
        available_skills = {
            item.casefold(): item
            for item in [
                *detail.item.stored.result.matched_required_skills,
                *detail.item.stored.result.missing_required_skills,
            ]
        }
        label = available_skills.get(skill.casefold())
        if label is None:
            return _redirect(f"/jobs/{record_id}", error="Required skill not found.")
        try:
            skill_value = SkillOverrideValue(value)
            container.job_overrides.upsert(
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record_id,
                    kind=JobEvidenceOverrideKind.SKILL,
                    target_key=label.casefold(),
                    target_label=label,
                    skill_value=skill_value,
                )
            )
        except (KeyError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return evidence_rescore_redirect(
            workspace,
            record_id,
            notice="Correction saved.",
        )

    @app.post(
        "/jobs/{record_id}/evidence/posting-date",
        name="job_evidence_posting_date",
    )
    async def job_evidence_posting_date(
        record_id: UUID,
        posting_date: date = Form(),
    ):
        workspace, detail = editable_match_detail(record_id)
        if detail.item.stored.result.posting_date is None:
            return _redirect(f"/jobs/{record_id}", error="Posting-date check not found.")
        try:
            container.job_overrides.upsert(
                JobEvidenceOverride(
                    workspace_id=workspace.id,
                    job_record_id=record_id,
                    kind=JobEvidenceOverrideKind.POSTING_DATE,
                    target_key="posting_date",
                    target_label="Posting date",
                    posting_date=posting_date,
                )
            )
        except (KeyError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return evidence_rescore_redirect(
            workspace,
            record_id,
            notice="Posting-date correction saved.",
        )

    @app.post(
        "/jobs/{record_id}/evidence/skill/add-to-compass",
        name="job_skill_add_to_compass",
    )
    async def job_skill_add_to_compass(
        record_id: UUID,
        skill: str = Form(min_length=1, max_length=500),
    ):
        workspace, detail = editable_match_detail(record_id)
        result = detail.item.stored.result
        required_skills = {
            " ".join(item.split()).casefold(): item
            for item in [
                *result.matched_required_skills,
                *result.missing_required_skills,
            ]
        }
        label = required_skills.get(" ".join(skill.split()).casefold())
        if label is None:
            return _redirect(f"/jobs/{record_id}", error="Required skill not found.")
        result_matched = label in result.matched_required_skills
        automatic_matched = (
            result_matched and label not in result.user_overridden_matched_skills
        ) or label in result.user_overridden_missing_skills
        if automatic_matched:
            return _redirect(
                f"/jobs/{record_id}",
                notice="This required skill is already evidenced by the persona Compass.",
                fragment="required-skills",
            )

        normalized_label = " ".join(label.split()).casefold()
        already_confirmed = any(
            any(
                " ".join(str(value).split()).casefold() == normalized_label
                for value in (fact.value if isinstance(fact.value, list) else [fact.value])
            )
            for fact in workspace.session.profile.confirmed_candidate_evidence
        )
        if already_confirmed:
            return _redirect(
                f"/jobs/{record_id}",
                notice="This demonstrated skill is already in the persona Compass.",
                fragment="required-skills",
            )

        now = datetime.now(timezone.utc)
        workspace.session.profile.facts.append(
            ProfileFact(
                key="skill.demonstrated",
                value=label,
                level=RequirementLevel.OPEN,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.EXPERIENCE,
                    text=f"Explicitly confirmed from a required skill check: {label}",
                ),
                user_note="Added explicitly from a job’s required skill check",
                needs_confirmation=False,
            )
        )
        workspace.session.profile.updated_at = now
        workspace.session.updated_at = now
        container.workspaces.save(workspace)
        return _redirect(
            f"/jobs/{record_id}",
            notice=(
                f"{label} was added to this persona’s Compass. Fully rematch this job or "
                "run complete Match when you want the wider Compass change applied."
            ),
            fragment="evidence-rematch",
        )

    @app.post("/jobs/{record_id}/evidence/delete", name="job_evidence_delete")
    async def job_evidence_delete(
        record_id: UUID,
        kind: str = Form(),
        target_key: str = Form(min_length=1, max_length=500),
    ):
        workspace, _detail = editable_match_detail(record_id)
        try:
            override_kind = JobEvidenceOverrideKind(kind)
        except ValueError:
            return _redirect(f"/jobs/{record_id}", error="Unknown evidence correction.")
        if not container.job_overrides.delete(
            workspace.id,
            record_id,
            override_kind,
            target_key,
        ):
            return _redirect(f"/jobs/{record_id}", error="Evidence correction not found.")
        return evidence_rescore_redirect(
            workspace,
            record_id,
            notice="Automatic evidence restored.",
        )

    @app.post("/jobs/{record_id}/evidence/rematch", name="job_evidence_rematch")
    async def job_evidence_rematch(record_id: UUID):
        workspace, _detail = editable_match_detail(record_id)
        if integrity_error := compass_action_error(workspace, CompassAction.MATCH):
            return _redirect(
                f"/jobs/{record_id}",
                error=integrity_error,
                fragment="evidence-rematch",
            )
        status = result_service().full_rematch_status(workspace, record_id)
        if not status.allowed:
            return _redirect(
                f"/jobs/{record_id}",
                error=status.reason,
                fragment="evidence-rematch",
            )
        try:
            task, created = container.background_single_job_matches.get_or_create_active(
                workspace.id,
                record_id,
                max_attempts=container.settings.background_task_max_attempts,
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            return _redirect(
                f"/jobs/{record_id}",
                error=str(exc),
                fragment="evidence-rematch",
            )
        if created:
            background_worker.wake()
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    @app.post("/jobs/{record_id}/match", name="job_match_only")
    async def job_match_only(record_id: UUID):
        """Match one accessible manual job without evaluating the full corpus."""

        detail = dashboard_for_current().opportunity_detail(record_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        if detail.job is None or not detail.card.source_is_manual:
            return _redirect(
                f"/jobs/{record_id}",
                error="Match this job only is available for saved manual job text.",
                fragment="evidence-heading",
            )
        workspace = latest_workspace()
        if workspace is None:
            return _redirect(
                f"/jobs/{record_id}",
                error="Create or select a Compass before matching this job.",
                fragment="evidence-heading",
            )
        if integrity_error := compass_action_error(workspace, CompassAction.MATCH):
            return _redirect(
                f"/jobs/{record_id}",
                error=integrity_error,
                fragment="evidence-heading",
            )
        status = result_service().match_only_status(workspace, record_id)
        if not status.allowed:
            return _redirect(
                f"/jobs/{record_id}",
                error=status.reason,
                fragment="evidence-heading",
            )
        try:
            task, created = container.background_single_job_matches.get_or_create_active(
                workspace.id,
                record_id,
                max_attempts=container.settings.background_task_max_attempts,
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            return _redirect(
                f"/jobs/{record_id}",
                error=str(exc),
                fragment="evidence-heading",
            )
        if created:
            background_worker.wake()
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    @app.post("/jobs/{record_id}/canonical-source", name="job_canonical_source")
    def job_canonical_source(
        record_id: UUID,
        url: str = Form(min_length=8, max_length=2_000),
        replace_restricted_source: bool = Form(default=False),
    ):
        old_record = next(
            (item for item in accessible_records() if item.id == record_id),
            None,
        )
        if old_record is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        try:
            check_storage_capacity(url, replacing_record_id=record_id)
            with provider_operation_scope(uuid4(), "job-import"):
                result = corpus().import_url(url, replace_manual=True)
        except (JobCorpusError, RuntimeError, ValueError) as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        if result.record is None or container.repository.get_current_job(result.record.id) is None:
            return _redirect(
                f"/jobs/{record_id}",
                error="The replacement URL did not produce a verified job. The original record remains unchanged.",
            )
        grant_record(result.record.id)
        if replace_restricted_source and result.record.id != old_record.id:
            if container.repository.get_current_job(old_record.id) is None:
                delete_job_records([old_record.id])
        return _redirect(
            f"/jobs/{result.record.id}",
            notice="Canonical employer source verified and saved.",
        )

    def add_page_context(
        request: Request,
        *,
        add_form: dict | None = None,
        manual_input_required: bool = False,
        manual_input_reason: str | None = None,
        manual_job_text: str = "",
        manual_source_url: str | None = None,
    ) -> dict:
        workspace = latest_workspace()
        account = current_account()
        persona = current_persona()
        portals = (
            container.portal_sources.list_for_persona(
                persona.id,
                account_id=account.id,
            )
            if account is not None and persona is not None
            else []
        )
        return {
            "workspace": workspace,
            "references": workspace.session.profile.reference_jobs if workspace else [],
            "stored_count": stored_count(),
            "max_stored_jobs": container.access_policy.max_stored_jobs,
            "portals": portals,
            "add_form": add_form,
            "manual_input_required": manual_input_required,
            "manual_input_reason": manual_input_reason,
            "manual_job_text": manual_job_text,
            "manual_source_url": manual_source_url,
            **common(request, "add"),
        }

    @app.get("/add", response_class=HTMLResponse, name="add_jobs")
    async def add_jobs(
        request: Request,
        url: str | None = Query(default=None, max_length=2_000),
        manual: bool = Query(default=False),
    ):
        safe_url: str | None = None
        if url:
            try:
                safe_url = normalize_job_url(url)
            except ValueError:
                pass
        manual_recovery = manual and safe_url is not None
        return templates.TemplateResponse(
            request=request,
            name="add.html",
            context=add_page_context(
                request,
                add_form=(
                    {
                        "url": safe_url,
                        "positives": "",
                        "negatives": "",
                        "learning_enabled": False,
                        "learning_scope": [],
                    }
                    if safe_url is not None
                    else None
                ),
                manual_input_required=manual_recovery,
                manual_input_reason=(MANUAL_ADD_RECOVERY_COPY if manual_recovery else None),
                manual_source_url=(safe_url if manual_recovery else None),
            ),
        )

    @app.post("/add/portals", name="portal_create")
    async def portal_create(
        url: str = Form(min_length=8, max_length=2_000),
        label: str = Form(default="", max_length=80),
    ):
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        try:
            container.portal_sources.create(
                persona.id,
                account_id=account.id,
                url=url,
                label=label,
            )
        except PortalSourceError as exc:
            return _redirect("/add", error=str(exc), fragment="employer-portals")
        return _redirect(
            "/add",
            notice="Employer career portal saved for this persona’s Explore searches.",
            fragment="employer-portals",
        )

    @app.post("/add/portals/{source_id}/toggle", name="portal_toggle")
    async def portal_toggle(
        source_id: UUID,
        enabled: bool = Form(default=False),
    ):
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        try:
            container.portal_sources.set_enabled(
                source_id,
                account_id=account.id,
                persona_id=persona.id,
                enabled=enabled,
            )
        except PortalSourceError as exc:
            return _redirect("/add", error=str(exc), fragment="employer-portals")
        return _redirect(
            "/add", notice="Employer portal setting updated.", fragment="employer-portals"
        )

    @app.post("/add/portals/{source_id}/delete", name="portal_delete")
    async def portal_delete(
        source_id: UUID,
        confirm_delete: bool = Form(default=False),
    ):
        account = current_account()
        persona = current_persona()
        if account is None or persona is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        if not confirm_delete:
            return _redirect(
                "/add",
                error="Confirm employer-portal deletion first.",
                fragment="employer-portals",
            )
        try:
            container.portal_sources.delete(
                source_id,
                account_id=account.id,
                persona_id=persona.id,
            )
        except PortalSourceError as exc:
            return _redirect("/add", error=str(exc), fragment="employer-portals")
        return _redirect("/add", notice="Employer portal removed.", fragment="employer-portals")

    @app.get("/matches", response_class=HTMLResponse, name="matches")
    async def matches(request: Request):
        workspace = latest_workspace()
        if workspace is not None:
            active_task = active_matching_pipeline(workspace.id)
            if active_task is not None:
                return RedirectResponse(f"/tasks/{active_task.id}", status_code=303)
        groups = result_service().latest(workspace) if workspace else None
        integrity_report = inspect_compass_integrity(
            workspace.session if workspace is not None else None
        )
        draft_counts = (
            container.application_drafts.counts_for_workspace(workspace.id)
            if workspace is not None
            else {}
        )
        opportunities = dashboard_for_current().list_opportunities()
        has_compass = bool(workspace and workspace.session.profile.confirmed_facts)
        runnable_record_ids = {
            record.id
            for record in accessible_records()
            if record.availability == JobAvailability.LIVE
            and container.repository.get_current_job(record.id) is not None
        }
        match_can_run = (
            has_compass
            and bool(runnable_record_ids)
            and integrity_report.allows(CompassAction.MATCH)
        )
        match_block_reason = None
        if not has_compass:
            match_block_reason = (
                "Add at least one active Compass statement to give Matching a direction."
            )
        elif not runnable_record_ids:
            match_block_reason = (
                "Save an open, extracted job through Add or Explore before running Matching."
            )
        elif not integrity_report.allows(CompassAction.MATCH):
            match_block_reason = integrity_report.blocked_reason(CompassAction.MATCH)
        employer_ratings, employer_rating_available = current_employer_ratings_by_record(
            opportunities
        )
        return templates.TemplateResponse(
            request=request,
            name="matches.html",
            headers={"Cache-Control": "no-store"},
            context={
                "workspace": workspace,
                "groups": groups,
                "opportunities": opportunities,
                "match_can_run": match_can_run,
                "match_block_reason": match_block_reason,
                "application_labels": APPLICATION_LABELS,
                "draft_counts": draft_counts,
                "job_ratings": current_job_ratings(),
                "employer_ratings_by_record": employer_ratings,
                "employer_rating_available_by_record": employer_rating_available,
                "employer_names_by_record": current_employer_names_by_record(opportunities),
                "employer_keys_by_record": current_employer_keys_by_record(opportunities),
                **common(request, "matches"),
            },
        )

    def application_focus_path(
        record_id: UUID,
        draft_id: UUID | None = None,
        *,
        create: bool = False,
    ) -> str:
        path = f"/apply?job={record_id}"
        if draft_id is not None:
            return f"{path}&draft={draft_id}"
        return f"{path}&create=true" if create else path

    @app.get("/apply", response_class=HTMLResponse, name="apply")
    async def apply_page(
        request: Request,
        job: UUID | None = Query(default=None),
        draft: UUID | None = Query(default=None),
        create: bool = Query(default=False),
    ):
        workspace = latest_workspace()
        groups = result_service().latest(workspace) if workspace else None
        items = [*groups.top, *groups.stretch] if groups else []
        drafts = container.application_drafts.list_for_workspace(workspace.id) if workspace else []
        draft_counts = (
            container.application_drafts.counts_for_workspace(workspace.id) if workspace else {}
        )
        requested_draft = None
        if draft is not None:
            if workspace is None:
                raise HTTPException(status_code=404, detail="Cover letter not found")
            requested_draft = next(
                (saved_draft for saved_draft in drafts if saved_draft.id == draft),
                None,
            )
            if requested_draft is None:
                raise HTTPException(status_code=404, detail="Cover letter not found")
            if job is not None and requested_draft.job_record_id != job:
                raise HTTPException(status_code=404, detail="Cover letter not found for this job")
        focused_job_id = (
            job
            if job is not None
            else requested_draft.job_record_id
            if requested_draft is not None
            else None
        )
        creation_focus = bool(create and focused_job_id is not None and requested_draft is None)
        candidates = [
            {
                "item": item,
                "employer_name": (
                    effective_employer_name(item.record.id, item.stored.job.company)
                    or item.stored.job.company
                ),
                "draft_count": draft_counts.get(item.record.id, 0),
                "selected": item.record.id == focused_job_id,
                "eligible": bool(
                    groups
                    and item.source_is_current
                    and item.accessible
                    and draft_counts.get(item.record.id, 0) < MAX_APPLICATION_DRAFTS_PER_JOB
                ),
            }
            for item in items
        ]
        drafts_by_job: dict[UUID, list] = {}
        for saved_draft in drafts:
            drafts_by_job.setdefault(saved_draft.job_record_id, []).append(saved_draft)
        draft_groups = []
        for job_record_id, saved_drafts in drafts_by_job.items():
            detail = dashboard_for_current().opportunity_detail(job_record_id)
            if detail is not None:
                selected = job_record_id == focused_job_id
                selected_draft_id = (
                    requested_draft.id
                    if selected
                    and requested_draft is not None
                    and requested_draft.job_record_id == job_record_id
                    else None
                )
                draft_groups.append(
                    {
                        "job_record_id": job_record_id,
                        "detail": detail,
                        "employer_name": (
                            effective_employer_name(job_record_id, detail.card.company)
                            or detail.card.company
                        ),
                        "drafts": saved_drafts,
                        "selected": selected,
                        "selected_draft_id": selected_draft_id,
                    }
                )
        return templates.TemplateResponse(
            request=request,
            name="apply.html",
            context={
                "workspace": workspace,
                "groups": groups,
                "candidates": candidates,
                "draft_groups": draft_groups,
                "draft_total": len(drafts),
                "creation_focus": creation_focus,
                "focused_job_id": focused_job_id,
                "batch_limit": container.settings.application_batch_limit,
                "max_draft_length": MAX_APPLICATION_DRAFT_LENGTH,
                "max_draft_name_length": MAX_APPLICATION_DRAFT_NAME_LENGTH,
                "max_drafts_per_job": MAX_APPLICATION_DRAFTS_PER_JOB,
                **common(request, "apply"),
            },
        )

    @app.post("/apply/generate", name="application_generate")
    def application_generate(
        record_ids: list[UUID] = Form(default=[]),
        confirm_ai_processing: bool = Form(default=False),
    ):
        workspace = latest_workspace()
        if workspace is None:
            return _redirect("/apply", error="Create the active persona’s Compass first.")
        if integrity_error := compass_action_error(workspace, CompassAction.APPLY_NEW):
            return _redirect("/apply", error=integrity_error)
        selected_ids = list(dict.fromkeys(record_ids))
        if not selected_ids:
            return _redirect("/apply", error="Select at least one matched job.")
        if len(selected_ids) > container.settings.application_batch_limit:
            return _redirect(
                "/apply",
                error=(
                    f"Generate at most {container.settings.application_batch_limit} letters "
                    "in one action."
                ),
            )
        if not confirm_ai_processing:
            return _redirect(
                "/apply",
                error=(
                    "Confirm the one-time OpenAI action for the selected public job evidence "
                    "and minimized confirmed Compass facts."
                ),
            )
        try:
            details = [
                current_application_match(workspace, record_id) for record_id in selected_ids
            ]
            service = application_service()
        except ApplicationDraftError as exc:
            return _redirect("/apply", error=str(exc))
        completed = 0
        created_drafts = []
        workflow_id = uuid4()
        try:
            with provider_operation_scope(workflow_id, "application-draft"):
                for detail in details:
                    record_id = detail.item.record.id
                    created = service.generate(
                        workspace,
                        record_id,
                        detail.item.stored.job,
                        DraftAction.CREATE,
                    )
                    created_drafts.append(created)
                    container.results.set_application_state(
                        workspace.id,
                        record_id,
                        ApplicationState.PREPARING,
                    )
                    completed += 1
        except (ApplicationDraftError, KeyError, RuntimeError, ValueError) as exc:
            message = str(exc)
            if completed:
                message = f"{completed} letter(s) were saved before generation stopped. {message}"
            destination = (
                application_focus_path(
                    created_drafts[0].job_record_id,
                    created_drafts[0].id,
                )
                if created_drafts
                else "/apply"
            )
            return _redirect(
                destination,
                error=message,
                fragment=(f"draft-{created_drafts[0].id}" if created_drafts else None),
            )
        first_created = created_drafts[0]
        destination = application_focus_path(
            first_created.job_record_id,
            first_created.id,
        )
        return _redirect(
            destination,
            notice=f"{completed} grounded cover letter(s) are ready to review and edit.",
            fragment=f"draft-{first_created.id}",
        )

    @app.post("/apply/{record_id}/transform", name="application_transform")
    def application_transform(
        record_id: UUID,
        action: str = Form(),
        draft_id: UUID | None = Form(default=None),
        confirm_ai_processing: bool = Form(default=False),
    ):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Persona workspace not found")
        if integrity_error := compass_action_error(workspace, CompassAction.APPLY_NEW):
            return _redirect(
                application_focus_path(record_id, draft_id),
                error=integrity_error,
                fragment=(f"draft-{draft_id}" if draft_id is not None else None),
            )
        if not confirm_ai_processing:
            return _redirect(
                application_focus_path(record_id, draft_id),
                error="Confirm the one-time OpenAI action before changing this draft.",
                fragment=(f"draft-{draft_id}" if draft_id is not None else None),
            )
        try:
            requested_action = DraftAction(action)
            if requested_action == DraftAction.CREATE:
                requested_action = DraftAction.RECREATE
            detail = current_application_match(workspace, record_id)
            with provider_operation_scope(uuid4(), "application-draft"):
                transformed = application_service().generate(
                    workspace,
                    record_id,
                    detail.item.stored.job,
                    requested_action,
                    draft_id=draft_id,
                )
        except (ApplicationDraftError, ValueError) as exc:
            return _redirect(
                application_focus_path(record_id, draft_id),
                error=str(exc),
                fragment=(f"draft-{draft_id}" if draft_id is not None else None),
            )
        return _redirect(
            application_focus_path(record_id, transformed.id),
            notice=f"The {requested_action.value} version is ready.",
            fragment=f"draft-{transformed.id}",
        )

    @app.post("/apply/{record_id}/save", name="application_save")
    def application_save(
        record_id: UUID,
        content: str = Form(min_length=1, max_length=MAX_APPLICATION_DRAFT_LENGTH),
        draft_id: UUID | None = Form(default=None),
        name: str = Form(default="", max_length=MAX_APPLICATION_DRAFT_NAME_LENGTH),
    ):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Persona workspace not found")
        existing = (
            container.application_drafts.get_by_id(
                workspace.id,
                record_id,
                draft_id,
            )
            if draft_id is not None
            else container.application_drafts.get(workspace.id, record_id)
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Cover letter not found")
        try:
            saved = container.application_drafts.save(
                workspace.id,
                record_id,
                content,
                generator_model=existing.generator_model,
                generated_action=existing.generated_action,
                manually_edited=True,
                draft_id=existing.id,
                name=name,
            )
        except ApplicationDraftError as exc:
            return _redirect(
                application_focus_path(record_id, existing.id),
                error=str(exc),
                fragment=f"draft-{existing.id}",
            )
        return _redirect(
            application_focus_path(record_id, saved.id),
            notice="Your cover-letter edits were saved locally.",
            fragment=f"draft-{saved.id}",
        )

    @app.post("/apply/{record_id}/delete", name="application_delete")
    def application_delete(
        record_id: UUID,
        draft_id: UUID | None = Form(default=None),
        confirm_delete: bool = Form(default=False),
    ):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Persona workspace not found")
        if not confirm_delete:
            return _redirect(
                application_focus_path(record_id, draft_id),
                error="Confirm cover-letter deletion first.",
                fragment=(f"draft-{draft_id}" if draft_id is not None else None),
            )
        if not container.application_drafts.delete(workspace.id, record_id, draft_id):
            raise HTTPException(status_code=404, detail="Cover letter not found")
        remaining = container.application_drafts.list_for_job(workspace.id, record_id)
        destination = application_focus_path(
            record_id,
            remaining[0].id if remaining else None,
        )
        return _redirect(destination, notice="Cover letter deleted.")

    @app.post(
        "/jobs/{record_id}/application-state",
        name="job_application_state",
    )
    def job_application_state(
        record_id: UUID,
        application_state: str = Form(),
    ):
        """Auto-save the application stage from an overview card."""

        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        allowed = accessible_record_ids()
        if allowed is not None and record_id not in allowed:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        try:
            state = ApplicationState(application_state)
            interaction = container.results.set_application_state(
                workspace.id,
                record_id,
                state,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Opportunity not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Unknown application state") from exc
        return JSONResponse(
            {
                "state": interaction.application_state.value,
                "label": APPLICATION_LABELS[interaction.application_state],
            }
        )

    @app.post(
        "/matches/references/{reference_id}/delete",
        name="match_reference_delete",
        include_in_schema=False,
    )
    @app.post(
        "/add/references/{reference_id}/delete",
        name="add_reference_delete",
    )
    def add_reference_delete(
        reference_id: UUID,
        confirm_delete: bool = Form(default=False),
    ):
        workspace = latest_workspace()
        if workspace is None:
            return _redirect("/add", error="No active Compass exists.")
        if active_matching_pipeline(workspace.id) is not None:
            return _redirect(
                "/add",
                error="Wait for the active import or Match run before changing saved jobs.",
            )
        reference = next(
            (item for item in workspace.session.profile.reference_jobs if item.id == reference_id),
            None,
        )
        if reference is None:
            return _redirect("/add", error="Reference settings were not found.")
        if not confirm_delete:
            return _redirect(
                "/add",
                error="Confirm complete deletion of the reference and archived job.",
            )
        record_id = stored_record_for_reference(reference)
        if record_id is not None:
            delete_job_records([record_id])
            return _redirect(
                "/add",
                notice="Reference, archived job, match history, and local source copies deleted.",
            )
        workflow().delete_reference(workspace.id, reference_id)
        return _redirect(
            "/add",
            notice="Reference settings deleted; no linked archived job remained.",
        )

    @app.post("/matches/jobs", name="match_job_add", include_in_schema=False)
    @app.post("/add/jobs", name="add_job")
    def add_job(
        request: Request,
        url: str = Form(min_length=8, max_length=2_000),
        positives: str = Form(default="", max_length=5_000),
        negatives: str = Form(default="", max_length=5_000),
        manual_source_text: str = Form(default="", max_length=150_000),
        learning_enabled: bool = Form(default=False),
        learning_scope: list[str] = Form(default=[]),
    ):
        workspace = latest_workspace()
        if workspace is None:
            return _redirect("/add", error="Create your compass before adding jobs.")
        if active_matching_pipeline(workspace.id) is not None:
            return _redirect(
                "/add",
                error="Wait for the active import or Match run before changing saved jobs.",
            )
        invalid_scopes = set(learning_scope).difference(REFERENCE_LEARNING_SCOPES)
        if invalid_scopes:
            return _redirect("/add", error="Unknown reference-learning scope.")
        positive_lines = [line.strip() for line in positives.splitlines() if line.strip()]
        negative_lines = [line.strip() for line in negatives.splitlines() if line.strip()]
        if learning_enabled and not learning_scope:
            return _redirect(
                "/add",
                error="Choose at least one allowed scope before enabling reference learning.",
            )
        if learning_enabled and not positive_lines:
            return _redirect(
                "/add",
                error=(
                    "Write at least one point that appeals to you before enabling reference "
                    "learning. A liked job never implies that every property should be learned."
                ),
            )
        pending_before = set(pending_reference_learning_ids(workspace.session.profile))
        manual_text = manual_source_text.strip()
        try:
            check_storage_capacity(url)
            with provider_operation_scope(uuid4(), "job-import"):
                result = (
                    corpus().import_manual(manual_text, source_url=url)
                    if manual_text
                    else corpus().import_url(url, persist_failure=False)
                )
            if manual_text:
                if result.record is None or result.job is None:
                    raise JobCorpusError("Manual job text did not produce a saved job.")
                grant_record(result.record.id)
                workflow().upsert_manual_reference(
                    workspace.id,
                    identity_url=result.record.canonical_url,
                    positives=positive_lines,
                    negatives=negative_lines,
                    learning_enabled=learning_enabled,
                    learning_scope=learning_scope,
                    job=result.job,
                )
            else:
                if result.manual_input_recommended and result.record is None:
                    return templates.TemplateResponse(
                        request=request,
                        name="add.html",
                        context=add_page_context(
                            request,
                            add_form={
                                "url": url,
                                "positives": positives,
                                "negatives": negatives,
                                "learning_enabled": learning_enabled,
                                "learning_scope": learning_scope,
                            },
                            manual_input_required=True,
                            manual_input_reason=(
                                "The source could not be read safely. Paste the public "
                                "advertisement text below; your link and Compass-learning "
                                f"choices are preserved. {result.message or ''}"
                            ).strip(),
                            manual_source_url=url,
                        ),
                        status_code=200,
                    )
                if result.record is not None:
                    grant_record(result.record.id)
                if (
                    result.record is not None
                    and result.record.last_http_status is not None
                    and 200 <= result.record.last_http_status < 300
                ):
                    workflow().upsert_verified_reference(
                        workspace.id,
                        requested_url=url,
                        resolved_url=result.record.canonical_url,
                        http_status=result.record.last_http_status,
                        verified_at=result.record.last_checked_at,
                        positives=positive_lines,
                        negatives=negative_lines,
                        learning_enabled=learning_enabled,
                        learning_scope=learning_scope,
                        job=result.job,
                    )
        except (JobCorpusError, ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect("/add", error=str(exc))

        count = stored_count()
        if not manual_text and result.kind in {
            JobObservationKind.EXPIRED,
            JobObservationKind.UNREACHABLE,
        }:
            return _redirect(
                "/add",
                error=(
                    "The URL could not become a current verified job and was not added. "
                    f"{result.message or ''}"
                ).strip(),
            )
        if not manual_text and result.kind == JobObservationKind.EXTRACTION_FAILED:
            return templates.TemplateResponse(
                request=request,
                name="add.html",
                context=add_page_context(
                    request,
                    add_form={
                        "url": url,
                        "positives": positives,
                        "negatives": negatives,
                        "learning_enabled": learning_enabled,
                        "learning_scope": learning_scope,
                    },
                    manual_input_required=True,
                    manual_input_reason=(
                        "The page was reachable, but its advertisement could not be extracted. "
                        "Paste the job text below instead; nothing incomplete was added to Archive."
                    ),
                    manual_source_url=url,
                ),
                status_code=200,
            )
        refreshed_workspace = latest_workspace()
        pending_after = (
            set(pending_reference_learning_ids(refreshed_workspace.session.profile))
            if refreshed_workspace is not None
            else set()
        )
        if learning_enabled and pending_after.difference(pending_before):
            return _redirect(
                f"/profile/{workspace.id}/review?return_to=compass",
                notice=(
                    "Reference learning created reviewable Compass suggestions. Nothing affects "
                    "Matching until you confirm it."
                ),
            )
        return _redirect(
            "/add",
            notice=(
                (
                    f"Manual job text saved ({count}/{container.access_policy.max_stored_jobs}). "
                    "It is marked as manual input and will never be fetched or reverified. "
                    if manual_text
                    else f"Job and reference settings saved ({count}/{container.access_policy.max_stored_jobs}). "
                )
                + (
                    "The notes were already reflected in reviewed or pending Compass decisions. "
                    if learning_enabled
                    else ""
                )
                + "It is ready for matching and stored in Archive."
            ),
        )

    @app.post("/add/jobs/manual", name="add_job_manual")
    def add_job_manual(
        source_text: str = Form(min_length=80, max_length=150_000),
        source_url: str = Form(default="", max_length=2_000),
        positives: str = Form(default="", max_length=5_000),
        negatives: str = Form(default="", max_length=5_000),
        learning_enabled: bool = Form(default=False),
        learning_scope: list[str] = Form(default=[]),
    ):
        workspace = latest_workspace()
        if workspace is None:
            return _redirect("/add", error="Create your Compass before adding jobs.")
        if active_matching_pipeline(workspace.id) is not None:
            return _redirect(
                "/add",
                error="Wait for the active import or Match run before changing saved jobs.",
            )
        if set(learning_scope).difference(REFERENCE_LEARNING_SCOPES):
            return _redirect("/add", error="Unknown reference-learning scope.")
        positive_lines = [line.strip() for line in positives.splitlines() if line.strip()]
        negative_lines = [line.strip() for line in negatives.splitlines() if line.strip()]
        if learning_enabled and not learning_scope:
            return _redirect(
                "/add",
                error="Choose at least one allowed scope before enabling reference learning.",
            )
        if learning_enabled and not positive_lines:
            return _redirect(
                "/add",
                error=(
                    "Write at least one point that appeals to you before enabling reference "
                    "learning."
                ),
            )

        optional_url = source_url.strip() or None
        pending_before = set(pending_reference_learning_ids(workspace.session.profile))
        try:
            if optional_url is not None:
                check_storage_capacity(optional_url)
            elif stored_count() >= container.access_policy.max_stored_jobs:
                raise JobCorpusError(
                    f"Your free workspace stores up to {container.access_policy.max_stored_jobs} "
                    "jobs. Remove one from Archive before adding another."
                )
            with provider_operation_scope(uuid4(), "job-import"):
                result = corpus().import_manual(source_text, source_url=optional_url)
            if result.record is None or result.job is None:
                raise JobCorpusError("Manual job text did not produce a saved job.")
            grant_record(result.record.id)
            workflow().upsert_manual_reference(
                workspace.id,
                identity_url=result.record.canonical_url,
                positives=positive_lines,
                negatives=negative_lines,
                learning_enabled=learning_enabled,
                learning_scope=learning_scope,
                job=result.job,
            )
        except (JobCorpusError, ProfileWorkflowError, RuntimeError, ValueError) as exc:
            return _redirect("/add", error=str(exc))

        refreshed_workspace = latest_workspace()
        pending_after = (
            set(pending_reference_learning_ids(refreshed_workspace.session.profile))
            if refreshed_workspace is not None
            else set()
        )
        if learning_enabled and pending_after.difference(pending_before):
            return _redirect(
                f"/profile/{workspace.id}/review?return_to=compass",
                notice=(
                    "Manual job text created reviewable Compass suggestions. Nothing affects "
                    "Matching until you confirm it."
                ),
            )
        count = stored_count()
        return _redirect(
            "/add",
            notice=(
                f"Manual job text saved ({count}/{container.access_policy.max_stored_jobs}). "
                "It is marked as manual input and will never be fetched or reverified."
            ),
        )

    @app.post("/matches/run", name="match_run")
    def match_run():
        workspace = latest_workspace()
        if workspace is None:
            return _redirect("/matches", error="Create your compass before matching jobs.")
        # A task that already exists is not a new search decision. Resume it
        # even if the Compass has since become incomplete, then apply the gate
        # before creating any new work.
        active_task = active_matching_pipeline(workspace.id) if background_queue_enabled else None
        if active_task is not None:
            return _redirect(f"/tasks/{active_task.id}")
        if integrity_error := compass_action_error(workspace, CompassAction.MATCH):
            return _redirect("/matches", error=integrity_error)
        if background_queue_enabled:
            active_task, created = container.background_tasks.get_or_create_active(
                workspace.id,
                BackgroundTaskKind.MATCH_RUN,
                max_attempts=container.settings.background_task_max_attempts,
            )
            if created:
                background_worker.wake()
            return _redirect(f"/tasks/{active_task.id}")
        try:
            groups = result_service().run(workspace)
        except (KeyError, ResultServiceError, RuntimeError, ValueError) as exc:
            return _redirect("/matches", error=str(exc))
        return _redirect(
            "/matches",
            notice=(
                f"Your match run is ready: {len(groups.top)} Top, "
                f"{len(groups.stretch)} Stretch, and {len(groups.blocked)} Blocked."
            ),
        )

    @app.get(
        "/matches/{run_id}/{record_id}",
        response_class=HTMLResponse,
        name="match_detail",
    )
    async def match_detail(request: Request, run_id: UUID, record_id: UUID):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            result_service().detail(workspace, run_id, record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Match result not found") from exc
        except ResultAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return _redirect(f"/jobs/{record_id}")

    @app.post("/matches/{run_id}/{record_id}/feedback", name="match_feedback")
    def match_feedback(
        run_id: UUID,
        record_id: UUID,
        feedback: str = Form(),
        note: str | None = Form(default=None, max_length=5_000),
        teach_compass: bool = Form(default=False),
    ):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            result_service().detail(workspace, run_id, record_id)
            state = FeedbackState(feedback)
            if state == FeedbackState.NONE:
                raise ValueError("Choose a feedback signal")
            container.results.set_feedback(workspace.id, record_id, state, note=note)
            if teach_compass:
                learned_text = (note or "").strip() or {
                    FeedbackState.INTERESTED: "More roles with work like this",
                    FeedbackState.NOT_RELEVANT: "Fewer roles with work like this",
                    FeedbackState.TOO_MUCH_CONSULTING: (
                        "Responsibilities and day-to-day work closer to my preferences"
                    ),
                    FeedbackState.TOO_LITTLE_DEVELOPMENT: (
                        "Work content aligned with what I want to spend time on"
                    ),
                    FeedbackState.TOO_SENIOR: ("A role level and scope aligned with my experience"),
                    FeedbackState.CONTEXT_MISMATCH: (
                        "Similar role content in a company and work context that fit me"
                    ),
                }.get(state, "")
                workflow().add_feedback_preference(
                    workspace.id,
                    learned_text,
                    source_label=f"job {record_id}",
                )
        except ResultAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Match result not found") from exc
        except ValueError as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return _redirect(
            f"/jobs/{record_id}",
            notice=(
                "Feedback saved and added as an editable Compass preference."
                if teach_compass
                else "Your feedback is saved as an explicit job signal."
            ),
        )

    @app.post("/matches/{run_id}/{record_id}/application", name="match_application")
    def match_application(
        run_id: UUID,
        record_id: UUID,
        application_state: str = Form(),
    ):
        workspace = latest_workspace()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Profile workspace not found")
        try:
            result_service().detail(workspace, run_id, record_id)
            state = ApplicationState(application_state)
            container.results.set_application_state(workspace.id, record_id, state)
        except ResultAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Match result not found") from exc
        except ValueError as exc:
            return _redirect(f"/jobs/{record_id}", error=str(exc))
        return _redirect(
            f"/jobs/{record_id}",
            notice="Application state updated.",
        )

    @app.get("/health", name="health")
    async def health():
        return {"status": "ok", "version": __version__, "mode": "match-results"}

    @app.get("/health/live", name="health_live")
    async def health_live():
        """Process-level probe that intentionally does not touch external providers."""

        return {"status": "live", "version": __version__}

    @app.get("/health/ready", name="health_ready")
    async def health_ready():
        """Readiness probe for the app and its required database connection."""

        try:
            with container.database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - exercised against a failed deployment
            return JSONResponse(
                {
                    "status": "unavailable",
                    "version": __version__,
                    "database": "unavailable",
                    "reason": type(exc).__name__,
                },
                status_code=503,
            )
        return {
            "status": "ready",
            "version": __version__,
            "database": container.database.engine.url.get_backend_name(),
        }

    return app
