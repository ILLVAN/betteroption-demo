"""Application composition root for CLI and web entry points."""

from __future__ import annotations

from .access import ProductAccessPolicy
from .accounts import AccountRepository
from .application_guidance import ApplicationGuidanceOverrideRepository
from .applications import ApplicationDraftRepository
from .background import (
    BackgroundJobImportRepository,
    BackgroundSingleJobMatchRepository,
    BackgroundTaskRepository,
)
from .company_intelligence import (
    BraveCompanyResearchProvider,
    CompanyResearchProvider,
    CompositeCompanyResearchProvider,
    WikimediaCompanyResearchProvider,
)
from .database import Database
from .employer_reputation import EmployerReputationRepository
from .explore_repository import ExploreSearchRepository
from .feedback import ProductFeedbackRepository
from .discovery import (
    ArbeitnowDiscoveryProvider,
    BraveWebDiscoveryProvider,
    DiscoveryAvailabilityFilter,
    JobDiscoveryProvider,
)
from .discovery_sources import (
    AtsDiscoveryExpander,
    DiscoverySourceMesh,
    ExaFallbackDiscoveryProvider,
    YouWebDiscoveryProvider,
    parse_configured_boards,
)
from .cv import CvRepository
from .cost_calibration import ProviderBillingPeriodRepository
from .job_corpus import JobCorpusService
from .job_overrides import JobEvidenceOverrideRepository
from .job_posters import BetterOptionPostedJobProvider, JobPosterRepository
from .job_ratings import PersonaJobRatingRepository
from .job_repository import JobRepository
from .legal import LegalAcceptanceRepository
from .llm import ApplicationDrafterPort, JobExtractorPort, LLMTask, ProfileExtractorPort
from .match_evidence import MatchEvidenceResolverPort
from .mobility import (
    CommuteRepository,
    FallbackTravelTimeProvider,
    GoogleRoutesTravelTimeProvider,
    MobilityService,
    NominatimPlaceResolver,
    OpenRouteServiceTravelTimeProvider,
    TransitousTravelTimeProvider,
    TravelTimeProvider,
    UnavailableTravelTimeProvider,
    ValhallaTravelTimeProvider,
)
from .personas import PersonaRepository
from .portal_sources import PortalSourceRepository
from .profile_repository import ProfileWorkspaceRepository
from .provider_permissions import ProviderPermissionRepository, require_provider_permission
from .provider_registry import ProviderRegistry, default_provider_registry
from .providers.apify_all_jobs import ApifyAllJobsDiscoveryProvider
from .providers.apify_eures import ApifyEuresDiscoveryProvider
from .providers.apify_jobspipe import ApifyJobsPipeDiscoveryProvider
from .providers.openwebninja_jsearch import OpenWebNinjaJSearchProvider
from .operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    RecordingCompanyResearchProvider,
    RecordingDiscoveryProvider,
    RecordingSalaryBenchmarkProvider,
)
from .result_repository import ResultRepository
from .settings import Settings
from .salary import SalaryBenchmarkProvider
from .telemetry import SqlAlchemyInvocationRecorder


class ApplicationContainer:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        registry: ProviderRegistry | None = None,
        database: Database | None = None,
        access_policy: ProductAccessPolicy | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.database = database or Database(self.settings.database_url)
        self.repository = JobRepository(database=self.database)
        self.accounts = AccountRepository(self.database)
        self.personas = PersonaRepository(self.database)
        self.application_drafts = ApplicationDraftRepository(self.database)
        self.application_guidance = ApplicationGuidanceOverrideRepository(self.database)
        self.employer_reputation = EmployerReputationRepository(self.database)
        self.job_overrides = JobEvidenceOverrideRepository(self.database)
        self.job_posters = JobPosterRepository(self.database)
        self.job_ratings = PersonaJobRatingRepository(self.database)
        self.provider_permissions = ProviderPermissionRepository(self.database)
        self.portal_sources = PortalSourceRepository(self.database)
        self.workspaces = ProfileWorkspaceRepository(self.database)
        self.results = ResultRepository(self.database)
        self.commutes = CommuteRepository(self.database)
        self.cvs = CvRepository(self.database)
        self.operations = ProviderOperationLedger(self.database)
        self.legal = LegalAcceptanceRepository(
            self.database,
            terms_version=self.settings.legal_terms_version,
            privacy_version=self.settings.legal_privacy_version,
        )
        self.billing_periods = ProviderBillingPeriodRepository(
            self.database,
            self.operations,
        )
        self.background_tasks = BackgroundTaskRepository(self.database)
        self.background_job_imports = BackgroundJobImportRepository(self.database)
        self.background_single_job_matches = BackgroundSingleJobMatchRepository(self.database)
        self.explore_searches = ExploreSearchRepository(
            self.database,
            preview_limit=self.settings.explore_preview_limit,
        )
        self.feedback = ProductFeedbackRepository(self.database)
        self.provider_budget = ProviderBudgetPolicy(
            self.operations,
            daily_operation_limit=self.settings.provider_daily_operation_limit,
            daily_cost_limit_usd=self.settings.provider_daily_cost_limit_usd,
            action_operation_limit=self.settings.provider_action_operation_limit,
            action_cost_limit_usd=self.settings.provider_action_cost_limit_usd,
        )
        self.telemetry = SqlAlchemyInvocationRecorder(
            self.database,
            operation_ledger=self.operations,
            operation_budget=self.provider_budget,
        )
        self.policy = self.settings.model_policy()
        self.registry = registry or default_provider_registry()
        self.access_policy = access_policy or ProductAccessPolicy(
            exact_route_match_limit=self.settings.exact_route_match_limit,
        )

    @property
    def reviewed_processors_available(self) -> bool:
        return (
            self.settings.app_environment not in {"staging", "production"}
            or self.settings.processor_review_completed
        )

    def _require_reviewed_processors(self) -> None:
        if not self.reviewed_processors_available:
            raise RuntimeError(
                "External AI processing is disabled until the processor review is complete."
            )

    def profile_extractor(self) -> ProfileExtractorPort:
        self._require_reviewed_processors()
        require_provider_permission(self.settings.llm_provider)
        return self.registry.build_profile(
            self.policy,
            self.telemetry,
            provider_options=self._llm_provider_options(),
        )

    def job_extractor(self) -> JobExtractorPort:
        self._require_reviewed_processors()
        require_provider_permission(self.settings.llm_provider)
        return self.registry.build_job(
            self.policy,
            self.telemetry,
            provider_options={
                **self._llm_provider_options(),
                "application_guidance_enabled": self.settings.application_guidance_available,
            },
        )

    def application_drafter(self) -> ApplicationDrafterPort:
        self._require_reviewed_processors()
        require_provider_permission(self.settings.llm_provider)
        return self.registry.build_application(
            self.policy,
            self.telemetry,
            provider_options={
                **self._llm_provider_options(),
                "application_guidance_enabled": self.settings.application_guidance_available,
            },
        )

    def match_evidence_resolver(self) -> MatchEvidenceResolverPort:
        self._require_reviewed_processors()
        require_provider_permission(self.settings.llm_provider)
        return self.registry.build_match_evidence(
            self.policy,
            self.telemetry,
            provider_options={
                **self._llm_provider_options(),
                "max_jobs": self.settings.match_evidence_max_jobs,
            },
        )

    def _llm_provider_options(self) -> dict[str, object]:
        if self.settings.llm_provider.casefold() != "openai":
            return {}
        return {"api_key": self.settings.openai_api_key_value}

    def job_corpus_service(self, *, require_llm: bool = False) -> JobCorpusService:
        extractor_factory = None
        if require_llm or self.settings.openai_api_key_value:
            extractor_factory = self.job_extractor
        return JobCorpusService(
            self.repository,
            extractor_factory=extractor_factory,
        )

    def job_discovery_provider(self) -> JobDiscoveryProvider:
        primary: list[JobDiscoveryProvider] = []
        if self.settings.employer_job_posting_available:
            primary.append(
                BetterOptionPostedJobProvider(
                    self.job_posters,
                    public_base_url=self.settings.public_base_url,
                )
            )
        jsearch_key = self.settings.openwebninja_jsearch_api_key_value
        if self.reviewed_processors_available and jsearch_key:
            primary.append(
                RecordingDiscoveryProvider(
                    OpenWebNinjaJSearchProvider(
                        jsearch_key,
                        max_requests=self.settings.openwebninja_jsearch_max_requests,
                        connect_timeout_seconds=(
                            self.settings.openwebninja_jsearch_connect_timeout_seconds
                        ),
                        read_timeout_seconds=(
                            self.settings.openwebninja_jsearch_read_timeout_seconds
                        ),
                        search_budget_seconds=(
                            self.settings.openwebninja_jsearch_search_budget_seconds
                        ),
                    ),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.openwebninja_jsearch_estimated_cost_per_call_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=bool(
                        self.settings.openwebninja_jsearch_estimated_cost_per_call_usd
                    ),
                )
            )
        apify_token = self.settings.apify_api_token_value
        if self.reviewed_processors_available and apify_token:
            primary.append(
                RecordingDiscoveryProvider(
                    ApifyEuresDiscoveryProvider(
                        apify_token,
                        max_results=self.settings.apify_eures_max_results,
                    ),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.apify_eures_estimated_cost_per_run_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=True,
                )
            )
            all_jobs_available = (
                self.settings.app_environment not in {"staging", "production"}
                or self.settings.apify_all_jobs_hosted_enabled
            )
            if all_jobs_available:
                primary.append(
                    RecordingDiscoveryProvider(
                        ApifyAllJobsDiscoveryProvider(
                            apify_token,
                            max_results_per_platform=(
                                self.settings.apify_all_jobs_max_results_per_platform
                            ),
                            max_items=self.settings.apify_all_jobs_max_items,
                            max_total_charge_usd=(
                                self.settings.apify_all_jobs_max_total_charge_usd
                            ),
                            posted_since=self.settings.apify_all_jobs_posted_since,
                            platforms=self.settings.apify_all_jobs_platforms,
                        ),
                        self.operations,
                        self.provider_budget,
                        estimated_cost_usd=(
                            self.settings.apify_all_jobs_estimated_cost_per_run_usd
                            or self.settings.discovery_estimated_cost_per_search_usd
                            or None
                        ),
                        # Apify bills one actor run; polling and dataset fetches
                        # are control-plane requests for that same paid run.
                        cost_is_per_request=False,
                    )
                )
            primary.append(
                RecordingDiscoveryProvider(
                    ApifyJobsPipeDiscoveryProvider(
                        apify_token,
                        max_results=self.settings.apify_jobspipe_max_results,
                        posted_within_days=(self.settings.apify_jobspipe_posted_within_days),
                    ),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.apify_jobspipe_estimated_cost_per_run_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=True,
                )
            )
        primary.append(
            RecordingDiscoveryProvider(
                ArbeitnowDiscoveryProvider(
                    max_pages=self.settings.arbeitnow_discovery_pages,
                    search_budget_seconds=min(
                        30.0,
                        self.settings.discovery_search_budget_seconds,
                    ),
                ),
                self.operations,
                self.provider_budget,
            )
        )
        # Exa runs beside the direct and structured feeds. Provider identity is
        # not a downstream ranking signal; final evidence quality decides.
        if self.reviewed_processors_available and self.settings.exa_search_api_key:
            primary.append(
                RecordingDiscoveryProvider(
                    ExaFallbackDiscoveryProvider(
                        self.settings.exa_search_api_key,
                        search_budget_seconds=self.settings.exa_search_budget_seconds,
                    ),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.exa_search_estimated_cost_per_call_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=bool(self.settings.exa_search_estimated_cost_per_call_usd),
                )
            )
        fallbacks: list[JobDiscoveryProvider] = []
        broad_web_target = primary if self.settings.discovery_call_all_providers else fallbacks
        if self.reviewed_processors_available and self.settings.brave_search_api_key:
            broad_web_target.append(
                RecordingDiscoveryProvider(
                    BraveWebDiscoveryProvider(self.settings.brave_search_api_key),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.brave_search_estimated_cost_per_call_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=bool(
                        self.settings.brave_search_estimated_cost_per_call_usd
                    ),
                )
            )
        if self.reviewed_processors_available and self.settings.you_search_api_key:
            broad_web_target.append(
                RecordingDiscoveryProvider(
                    YouWebDiscoveryProvider(self.settings.you_search_api_key),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.you_search_estimated_cost_per_call_usd
                        or self.settings.discovery_estimated_cost_per_search_usd
                        or None
                    ),
                    cost_is_per_request=bool(self.settings.you_search_estimated_cost_per_call_usd),
                )
            )
        ats_expander = None
        if self.settings.ats_expansion_enabled:
            ats_expander = AtsDiscoveryExpander(
                greenhouse_boards=parse_configured_boards(self.settings.greenhouse_boards),
                lever_boards=parse_configured_boards(
                    self.settings.lever_sites,
                    allow_eu_prefix=True,
                ),
                ashby_boards=parse_configured_boards(self.settings.ashby_boards),
                max_discovered_boards=self.settings.ats_expansion_max_boards,
            )
        return DiscoverySourceMesh(
            primary,
            ats_expander=ats_expander,
            fallback_providers=fallbacks,
            fallback_min_results=self.settings.discovery_fallback_min_results,
            availability_filter=DiscoveryAvailabilityFilter(
                maximum_checks=self.settings.discovery_availability_max_checks,
                total_timeout_seconds=(self.settings.discovery_availability_budget_seconds),
            ),
            search_budget_seconds=self.settings.discovery_search_budget_seconds,
            preview_limit=self.settings.explore_preview_limit,
        )

    def company_research_provider(self) -> CompanyResearchProvider | None:
        if not self.settings.employer_homepage_research:
            return None
        providers: list[CompanyResearchProvider] = [
            RecordingCompanyResearchProvider(
                WikimediaCompanyResearchProvider(timeout_seconds=3.0),
                self.operations,
                self.provider_budget,
            )
        ]
        if self.reviewed_processors_available and self.settings.brave_search_api_key:
            providers.append(
                RecordingCompanyResearchProvider(
                    BraveCompanyResearchProvider(
                        self.settings.brave_search_api_key,
                        timeout_seconds=4.0,
                    ),
                    self.operations,
                    self.provider_budget,
                    estimated_cost_usd=(
                        self.settings.brave_search_estimated_cost_per_call_usd
                        or self.settings.company_research_estimated_cost_per_call_usd
                        or None
                    ),
                )
            )
        return CompositeCompanyResearchProvider(providers)

    def salary_benchmark_provider(self) -> SalaryBenchmarkProvider | None:
        """Build the explicit opt-in Europe salary researcher."""

        if not self.settings.salary_research_enabled:
            return None
        self._require_reviewed_processors()
        if self.settings.llm_provider.casefold() != "openai":
            raise RuntimeError("Salary research currently requires the OpenAI provider.")
        if not self.settings.openai_api_key_value:
            raise RuntimeError("OPENAI_API_KEY is required when salary research is enabled.")
        from .providers.openai_salary import OpenAISalaryBenchmarkProvider

        return RecordingSalaryBenchmarkProvider(
            OpenAISalaryBenchmarkProvider(
                route=self.policy.route(LLMTask.SALARY_RESEARCH),
                recorder=SqlAlchemyInvocationRecorder(self.database),
                api_key=self.settings.openai_api_key_value,
                max_tool_calls=self.settings.salary_research_max_tool_calls,
                search_content_token_ceiling=(
                    self.settings.salary_research_search_content_token_ceiling
                ),
            ),
            self.operations,
            self.provider_budget,
            estimated_cost_usd=(
                self.settings.salary_research_estimated_cost_per_call_usd
                * self.settings.salary_research_max_tool_calls
                or None
            ),
            tool_cost_per_call_usd=(
                self.settings.salary_research_estimated_cost_per_call_usd or None
            ),
        )

    def travel_time_provider(self) -> TravelTimeProvider:
        provider = self.settings.mobility_provider.casefold()
        privacy_mode = self.settings.mobility_privacy_mode
        google_key = self.settings.google_routes_api_key
        ors_key = self.settings.openrouteservice_api_key
        if provider not in {
            "auto",
            "none",
            "google",
            "openrouteservice",
            "transitous",
            "valhalla",
        }:
            raise RuntimeError(f"Unknown mobility provider: {self.settings.mobility_provider}")
        if not self.reviewed_processors_available:
            return UnavailableTravelTimeProvider()
        if provider == "google" and not google_key:
            raise RuntimeError("GOOGLE_ROUTES_API_KEY is required for the Google mobility provider")
        if provider == "google" and privacy_mode != "balanced":
            raise RuntimeError(
                "Google routing requires BETTEROPTION_MOBILITY_PRIVACY_MODE=balanced"
            )
        if provider == "openrouteservice" and not ors_key:
            raise RuntimeError(
                "OPENROUTESERVICE_API_KEY is required for the openrouteservice provider"
            )
        if provider == "transitous" and not self.settings.transitous_enabled:
            raise RuntimeError("BETTEROPTION_TRANSITOUS_ENABLED must be true for Transitous")
        if provider == "valhalla" and not self.settings.valhalla_enabled:
            raise RuntimeError("BETTEROPTION_VALHALLA_ENABLED must be true for Valhalla")
        if provider == "none":
            return UnavailableTravelTimeProvider()
        providers: list[TravelTimeProvider] = []
        if google_key and provider in {"auto", "google"} and privacy_mode == "balanced":
            providers.append(GoogleRoutesTravelTimeProvider(google_key))
        if self.settings.transitous_enabled and provider in {"auto", "transitous"}:
            providers.append(
                TransitousTravelTimeProvider(
                    base_url=self.settings.transitous_base_url,
                    user_agent=self.settings.transitous_user_agent,
                    timeout_seconds=6.0,
                )
            )
        if ors_key and provider in {"auto", "openrouteservice"}:
            providers.append(OpenRouteServiceTravelTimeProvider(ors_key))
        if self.settings.valhalla_enabled and provider in {"auto", "valhalla"}:
            place_resolver = (
                NominatimPlaceResolver(
                    base_url=self.settings.osm_geocoder_base_url,
                    user_agent=self.settings.osm_geocoder_user_agent,
                    timeout_seconds=5.0,
                )
                if self.settings.osm_geocoder_enabled
                else None
            )
            providers.append(
                ValhallaTravelTimeProvider(
                    base_url=self.settings.valhalla_base_url,
                    client_id=self.settings.valhalla_client_id,
                    user_agent=self.settings.valhalla_user_agent,
                    place_resolver=place_resolver,
                    timeout_seconds=6.0,
                )
            )
        if not providers:
            return UnavailableTravelTimeProvider()
        return providers[0] if len(providers) == 1 else FallbackTravelTimeProvider(providers)

    def mobility_service(
        self,
        provider: TravelTimeProvider | None = None,
    ) -> MobilityService:
        return MobilityService(
            self.commutes,
            provider or self.travel_time_provider(),
            operation_ledger=self.operations,
            operation_budget=self.provider_budget,
            estimated_costs={
                "google-routes": self.settings.google_routes_estimated_cost_per_call_usd
            },
            enforce_provider_permissions=provider is None,
        )

    def provider_availability(self) -> dict[str, tuple[bool, str]]:
        """Describe technical availability separately from account permission."""

        openai = bool(self.settings.openai_api_key_value) and self.reviewed_processors_available
        brave = bool(self.settings.brave_search_api_key) and self.reviewed_processors_available
        exa = bool(self.settings.exa_search_api_key) and self.reviewed_processors_available
        you = bool(self.settings.you_search_api_key) and self.reviewed_processors_available
        jsearch = (
            bool(self.settings.openwebninja_jsearch_api_key_value)
            and self.reviewed_processors_available
        )
        eures = bool(self.settings.apify_api_token_value) and self.reviewed_processors_available
        jobspipe = bool(self.settings.apify_api_token_value) and self.reviewed_processors_available
        all_jobs = bool(
            self.settings.apify_api_token_value
            and self.reviewed_processors_available
            and (
                self.settings.app_environment not in {"staging", "production"}
                or self.settings.apify_all_jobs_hosted_enabled
            )
        )
        ats = bool(
            self.settings.ats_expansion_enabled
            and (
                self.settings.greenhouse_boards
                or self.settings.lever_sites
                or self.settings.ashby_boards
            )
        )
        mobility = self.settings.mobility_provider.casefold()
        return {
            "openai": (openai, "Configured" if openai else "API key or processor review missing"),
            "arbeitnow": (True, "Keyless public feed configured"),
            "brave": (brave, "Configured" if brave else "Search key or processor review missing"),
            "exa": (exa, "Configured" if exa else "API key or processor review missing"),
            "you": (you, "Configured" if you else "Search key or processor review missing"),
            "jsearch": (
                jsearch,
                "Configured" if jsearch else "JSearch key or processor review missing",
            ),
            "eures": (
                eures,
                "Configured" if eures else "Apify token or processor review missing",
            ),
            "jobspipe": (
                jobspipe,
                "Configured" if jobspipe else "Apify token or processor review missing",
            ),
            "all-jobs": (
                all_jobs,
                (
                    "Configured"
                    if all_jobs
                    else "Apify token, processor review, or hosted actor approval missing"
                ),
            ),
            "ats": (ats, "Configured boards" if ats else "No ATS boards configured"),
            "wikimedia": (
                bool(self.settings.employer_homepage_research),
                "Configured"
                if self.settings.employer_homepage_research
                else "Company research disabled",
            ),
            "google-routes": (
                bool(self.settings.google_routes_api_key)
                and mobility in {"auto", "google"}
                and self.settings.mobility_privacy_mode == "balanced",
                "Configured only in balanced mobility mode",
            ),
            "transitous": (
                self.settings.transitous_enabled and mobility in {"auto", "transitous"},
                "Hosted service requires a suitable-use review before commercial use",
            ),
            "openrouteservice": (
                bool(self.settings.openrouteservice_api_key)
                and mobility in {"auto", "openrouteservice"},
                "Configured" if self.settings.openrouteservice_api_key else "API key missing",
            ),
            "valhalla": (
                self.settings.valhalla_enabled and mobility in {"auto", "valhalla"},
                "Configured" if self.settings.valhalla_enabled else "Disabled",
            ),
            "nominatim": (
                self.settings.osm_geocoder_enabled,
                "Configured" if self.settings.osm_geocoder_enabled else "Disabled",
            ),
        }
