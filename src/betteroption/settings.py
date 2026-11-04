"""Validated runtime settings loaded from environment variables."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .database import DEFAULT_DATABASE_URL
from .llm import LLMTask, ModelPolicy, ModelRoute


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "WorkLifeBalance"
    app_environment: str = Field(default="local", alias="BETTEROPTION_APP_ENVIRONMENT")
    public_base_url: str = Field(
        default="",
        alias="BETTEROPTION_PUBLIC_BASE_URL",
    )
    debug: bool = False
    auth_mode: Literal["local", "accounts"] = Field(
        default="local",
        alias="BETTEROPTION_AUTH_MODE",
    )
    local_personas_enabled: bool = Field(
        default=False,
        alias="BETTEROPTION_LOCAL_PERSONAS_ENABLED",
    )
    account_personas_enabled: bool = Field(
        default=True,
        alias="BETTEROPTION_ACCOUNT_PERSONAS_ENABLED",
    )
    persona_limit: int = Field(
        default=5,
        alias="BETTEROPTION_PERSONA_LIMIT",
        ge=1,
        le=5,
    )
    registration_mode: Literal["first_user", "open", "invite_only", "disabled"] = Field(
        default="first_user",
        alias="BETTEROPTION_REGISTRATION_MODE",
    )
    auth_session_days: int = Field(
        default=30,
        alias="BETTEROPTION_AUTH_SESSION_DAYS",
        ge=1,
        le=30,
    )
    auth_secure_cookie: bool = Field(
        default=False,
        alias="BETTEROPTION_AUTH_SECURE_COOKIE",
    )
    operator_emails: str = Field(
        default="",
        alias="BETTEROPTION_OPERATOR_EMAILS",
    )
    auth_invitation_hours: int = Field(
        default=72,
        alias="BETTEROPTION_AUTH_INVITATION_HOURS",
        ge=1,
        le=72,
    )
    auth_recovery_minutes: int = Field(
        default=60,
        alias="BETTEROPTION_AUTH_RECOVERY_MINUTES",
        ge=10,
        le=60,
    )
    auth_rate_limit_attempts: int = Field(
        default=8,
        alias="BETTEROPTION_AUTH_RATE_LIMIT_ATTEMPTS",
        ge=3,
        le=100,
    )
    auth_rate_limit_minutes: int = Field(
        default=15,
        alias="BETTEROPTION_AUTH_RATE_LIMIT_MINUTES",
        ge=1,
        le=1_440,
    )
    auth_rate_limit_secret: str = Field(
        default="",
        alias="BETTEROPTION_AUTH_RATE_LIMIT_SECRET",
    )
    auth_trust_cloudflare_headers: bool = Field(
        default=False,
        alias="BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS",
    )
    retention_worker_interval_hours: int = Field(
        default=24,
        alias="BETTEROPTION_RETENTION_WORKER_INTERVAL_HOURS",
        ge=1,
        le=24,
    )
    retention_token_record_days: int = Field(
        default=7,
        alias="BETTEROPTION_RETENTION_TOKEN_RECORD_DAYS",
        ge=1,
        le=7,
    )
    retention_auth_attempt_days: int = Field(
        default=7,
        alias="BETTEROPTION_RETENTION_AUTH_ATTEMPT_DAYS",
        ge=1,
        le=7,
    )
    retention_raw_compass_days: int = Field(
        default=30,
        alias="BETTEROPTION_RETENTION_RAW_COMPASS_DAYS",
        ge=1,
        le=30,
    )
    retention_pending_fact_days: int = Field(
        default=30,
        alias="BETTEROPTION_RETENTION_PENDING_FACT_DAYS",
        ge=1,
        le=30,
    )
    retention_rejected_fact_days: int = Field(
        default=7,
        alias="BETTEROPTION_RETENTION_REJECTED_FACT_DAYS",
        ge=1,
        le=7,
    )
    retention_legacy_cv_hours: int = Field(
        default=24,
        alias="BETTEROPTION_RETENTION_LEGACY_CV_HOURS",
        ge=1,
        le=24,
    )
    retention_provider_telemetry_days: int = Field(
        default=90,
        alias="BETTEROPTION_RETENTION_PROVIDER_TELEMETRY_DAYS",
        ge=1,
        le=90,
    )
    retention_application_draft_days: int = Field(
        default=180,
        alias="BETTEROPTION_RETENTION_APPLICATION_DRAFT_DAYS",
        ge=1,
        le=365,
    )
    retention_product_feedback_days: int = Field(
        default=180,
        alias="BETTEROPTION_RETENTION_PRODUCT_FEEDBACK_DAYS",
        ge=1,
        le=365,
    )
    legal_operator_name: str = Field(
        default="",
        alias="BETTEROPTION_LEGAL_OPERATOR_NAME",
    )
    legal_operator_address: str = Field(
        default="",
        alias="BETTEROPTION_LEGAL_OPERATOR_ADDRESS",
    )
    legal_contact_email: str = Field(
        default="",
        alias="BETTEROPTION_LEGAL_CONTACT_EMAIL",
    )
    legal_terms_version: str = Field(
        default="2026-08-02-draft",
        alias="BETTEROPTION_LEGAL_TERMS_VERSION",
    )
    legal_privacy_version: str = Field(
        default="2026-08-05-feedback-draft",
        alias="BETTEROPTION_LEGAL_PRIVACY_VERSION",
    )
    legal_review_completed: bool = Field(
        default=False,
        alias="BETTEROPTION_LEGAL_REVIEW_COMPLETED",
    )
    processor_review_completed: bool = Field(
        default=False,
        alias="BETTEROPTION_PROCESSOR_REVIEW_COMPLETED",
    )
    incident_plan_ready: bool = Field(
        default=False,
        alias="BETTEROPTION_INCIDENT_PLAN_READY",
    )
    backup_restore_tested: bool = Field(
        default=False,
        alias="BETTEROPTION_BACKUP_RESTORE_TESTED",
    )
    employer_job_posting_enabled: bool = Field(
        default=False,
        alias="BETTEROPTION_EMPLOYER_JOB_POSTING_ENABLED",
    )
    database_url: str = Field(default=DEFAULT_DATABASE_URL, alias="BETTEROPTION_DATABASE_URL")
    llm_provider: str = Field(default="openai", alias="BETTEROPTION_LLM_PROVIDER")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6-luna", alias="OPENAI_MODEL")
    profile_extraction_model: str | None = Field(
        default=None,
        alias="BETTEROPTION_PROFILE_MODEL",
    )
    job_extraction_model: str | None = Field(
        default=None,
        alias="BETTEROPTION_JOB_MODEL",
    )
    match_explanation_model: str | None = Field(
        default=None,
        alias="BETTEROPTION_MATCH_MODEL",
    )
    application_draft_model: str | None = Field(
        default=None,
        alias="BETTEROPTION_APPLICATION_DRAFT_MODEL",
    )
    salary_research_model: str | None = Field(
        default=None,
        alias="BETTEROPTION_SALARY_RESEARCH_MODEL",
    )
    salary_research_enabled: bool = Field(
        default=False,
        alias="BETTEROPTION_SALARY_RESEARCH_ENABLED",
    )
    salary_research_max_jobs: int = Field(
        default=10,
        alias="BETTEROPTION_SALARY_RESEARCH_MAX_JOBS",
        ge=1,
        le=25,
    )
    salary_research_max_tool_calls: int = Field(
        default=10,
        alias="BETTEROPTION_SALARY_RESEARCH_MAX_TOOL_CALLS",
        ge=1,
        le=25,
    )
    salary_research_search_content_token_ceiling: int = Field(
        default=128_000,
        alias="BETTEROPTION_SALARY_RESEARCH_SEARCH_CONTENT_TOKEN_CEILING",
        ge=128_000,
        le=1_000_000,
    )
    match_evidence_max_jobs: int = Field(
        default=25,
        alias="BETTEROPTION_MATCH_EVIDENCE_MAX_JOBS",
        ge=1,
        le=100,
    )
    application_batch_limit: int = Field(
        default=5,
        alias="BETTEROPTION_APPLICATION_BATCH_LIMIT",
        ge=1,
        le=5,
    )
    application_guidance_enabled: bool = Field(
        default=True,
        alias="BETTEROPTION_APPLICATION_GUIDANCE_ENABLED",
    )
    openai_input_cost_per_million_usd: float | None = Field(
        default=None,
        alias="BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD",
        ge=0,
    )
    openai_output_cost_per_million_usd: float | None = Field(
        default=None,
        alias="BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD",
        ge=0,
    )
    mobility_provider: str = Field(default="auto", alias="BETTEROPTION_MOBILITY_PROVIDER")
    mobility_privacy_mode: Literal["privacy_first", "balanced"] = Field(
        default="privacy_first",
        alias="BETTEROPTION_MOBILITY_PRIVACY_MODE",
    )
    exact_route_match_limit: int = Field(
        default=25,
        alias="BETTEROPTION_EXACT_ROUTE_MATCH_LIMIT",
        ge=1,
        le=25,
    )
    google_routes_api_key: str | None = Field(default=None, alias="GOOGLE_ROUTES_API_KEY")
    openrouteservice_api_key: str | None = Field(
        default=None,
        alias="OPENROUTESERVICE_API_KEY",
    )
    transitous_enabled: bool = Field(default=True, alias="BETTEROPTION_TRANSITOUS_ENABLED")
    transitous_base_url: str = Field(
        default="https://api.transitous.org",
        alias="BETTEROPTION_TRANSITOUS_BASE_URL",
    )
    transitous_user_agent: str = Field(
        default=("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        alias="BETTEROPTION_TRANSITOUS_USER_AGENT",
    )
    valhalla_enabled: bool = Field(default=True, alias="BETTEROPTION_VALHALLA_ENABLED")
    valhalla_base_url: str = Field(
        default="https://valhalla1.openstreetmap.de",
        alias="BETTEROPTION_VALHALLA_BASE_URL",
    )
    valhalla_client_id: str = Field(
        default="betteroption.example",
        alias="BETTEROPTION_VALHALLA_CLIENT_ID",
    )
    valhalla_user_agent: str = Field(
        default=("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        alias="BETTEROPTION_VALHALLA_USER_AGENT",
    )
    osm_geocoder_enabled: bool = Field(
        default=True,
        alias="BETTEROPTION_OSM_GEOCODER_ENABLED",
    )
    osm_geocoder_base_url: str = Field(
        default="https://nominatim.openstreetmap.org",
        alias="BETTEROPTION_OSM_GEOCODER_BASE_URL",
    )
    osm_geocoder_user_agent: str = Field(
        default=("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        alias="BETTEROPTION_OSM_GEOCODER_USER_AGENT",
    )
    arbeitnow_discovery_pages: int = Field(
        default=30,
        alias="BETTEROPTION_ARBEITNOW_PAGES",
        ge=1,
        le=30,
    )
    discovery_search_budget_seconds: float = Field(
        default=390.0,
        alias="BETTEROPTION_DISCOVERY_SEARCH_BUDGET_SECONDS",
        ge=30,
        le=420,
    )
    discovery_availability_budget_seconds: float = Field(
        default=35.0,
        alias="BETTEROPTION_DISCOVERY_AVAILABILITY_BUDGET_SECONDS",
        ge=1,
        le=60,
    )
    discovery_availability_max_checks: int = Field(
        default=120,
        alias="BETTEROPTION_DISCOVERY_AVAILABILITY_MAX_CHECKS",
        ge=0,
        le=300,
    )
    explore_preview_limit: int = Field(
        default=9,
        alias="BETTEROPTION_EXPLORE_PREVIEW_LIMIT",
        ge=3,
        le=12,
    )
    discovery_call_all_providers: bool = Field(
        default=True,
        alias="BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS",
    )
    brave_search_api_key: str | None = Field(default=None, alias="BRAVE_SEARCH_API_KEY")
    exa_search_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    you_search_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "YDC_API_KEY",
            "BETTEROPTION_YOU_SEARCH_API_KEY",
            "YOU_SEARCH_API_KEY",
        ),
    )
    openwebninja_jsearch_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENWEBNINJA_JSEARCH_API_KEY",
            "BETTEROPTION_OPENWEBNINJA_JSEARCH_API_KEY",
        ),
    )
    openwebninja_jsearch_max_requests: int = Field(
        default=3,
        alias="BETTEROPTION_OPENWEBNINJA_JSEARCH_MAX_REQUESTS",
        ge=1,
        le=6,
    )
    openwebninja_jsearch_connect_timeout_seconds: float = Field(
        default=10.0,
        alias="BETTEROPTION_OPENWEBNINJA_JSEARCH_CONNECT_TIMEOUT_SECONDS",
        ge=1,
        le=30,
    )
    openwebninja_jsearch_read_timeout_seconds: float = Field(
        default=90.0,
        alias="BETTEROPTION_OPENWEBNINJA_JSEARCH_READ_TIMEOUT_SECONDS",
        ge=20,
        le=120,
    )
    openwebninja_jsearch_search_budget_seconds: float = Field(
        default=120.0,
        alias="BETTEROPTION_OPENWEBNINJA_JSEARCH_SEARCH_BUDGET_SECONDS",
        ge=30,
        le=240,
    )
    apify_api_token: SecretStr | None = Field(default=None, alias="APIFY_API_TOKEN")
    apify_eures_max_results: int = Field(
        default=30,
        alias="BETTEROPTION_APIFY_EURES_MAX_RESULTS",
        ge=1,
        le=30,
    )
    apify_jobspipe_max_results: int = Field(
        default=300,
        alias="BETTEROPTION_APIFY_JOBSPIPE_MAX_RESULTS",
        ge=1,
        le=300,
    )
    apify_jobspipe_posted_within_days: int = Field(
        default=60,
        alias="BETTEROPTION_APIFY_JOBSPIPE_POSTED_WITHIN_DAYS",
        ge=1,
        le=365,
    )
    apify_all_jobs_max_results_per_platform: int = Field(
        default=20,
        alias="BETTEROPTION_APIFY_ALL_JOBS_MAX_RESULTS_PER_PLATFORM",
        ge=1,
        le=500,
    )
    apify_all_jobs_max_items: int = Field(
        default=120,
        alias="BETTEROPTION_APIFY_ALL_JOBS_MAX_ITEMS",
        ge=1,
        le=300,
    )
    apify_all_jobs_posted_since: str = Field(
        default="30 days",
        alias="BETTEROPTION_APIFY_ALL_JOBS_POSTED_SINCE",
        max_length=40,
    )
    apify_all_jobs_platforms: str = Field(
        default="",
        alias="BETTEROPTION_APIFY_ALL_JOBS_PLATFORMS",
        max_length=500,
    )
    apify_all_jobs_max_total_charge_usd: float = Field(
        default=0.40,
        alias="BETTEROPTION_APIFY_ALL_JOBS_MAX_TOTAL_CHARGE_USD",
        ge=0,
    )
    apify_all_jobs_hosted_enabled: bool = Field(
        default=False,
        alias="BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED",
    )
    exa_search_budget_seconds: float = Field(
        default=140.0,
        alias="BETTEROPTION_EXA_SEARCH_BUDGET_SECONDS",
        ge=10,
        le=180,
    )
    discovery_fallback_min_results: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS",
            "BETTEROPTION_EXA_FALLBACK_MIN_RESULTS",
        ),
        ge=1,
        le=100,
    )
    greenhouse_boards: str = Field(default="", alias="BETTEROPTION_GREENHOUSE_BOARDS")
    lever_sites: str = Field(default="", alias="BETTEROPTION_LEVER_SITES")
    ashby_boards: str = Field(default="", alias="BETTEROPTION_ASHBY_BOARDS")
    ats_expansion_enabled: bool = Field(
        default=True,
        alias="BETTEROPTION_ATS_EXPANSION_ENABLED",
    )
    ats_expansion_max_boards: int = Field(
        default=20,
        alias="BETTEROPTION_ATS_EXPANSION_MAX_BOARDS",
        ge=0,
        le=30,
    )
    employer_homepage_research: bool = Field(
        default=True,
        alias="BETTEROPTION_EMPLOYER_HOMEPAGE_RESEARCH",
    )
    provider_daily_operation_limit: int = Field(
        default=1_000,
        alias="BETTEROPTION_PROVIDER_DAILY_OPERATION_LIMIT",
        ge=0,
    )
    provider_daily_cost_limit_usd: float = Field(
        default=0,
        alias="BETTEROPTION_PROVIDER_DAILY_COST_LIMIT_USD",
        ge=0,
    )
    provider_action_operation_limit: int = Field(
        default=200,
        alias="BETTEROPTION_PROVIDER_ACTION_OPERATION_LIMIT",
        ge=0,
    )
    provider_action_cost_limit_usd: float = Field(
        default=0,
        alias="BETTEROPTION_PROVIDER_ACTION_COST_LIMIT_USD",
        ge=0,
    )
    background_worker_enabled: bool = Field(
        default=True,
        alias="BETTEROPTION_BACKGROUND_WORKER_ENABLED",
    )
    background_worker_external: bool = Field(
        default=False,
        alias="BETTEROPTION_BACKGROUND_WORKER_EXTERNAL",
    )
    background_worker_poll_seconds: float = Field(
        default=0.5,
        alias="BETTEROPTION_BACKGROUND_WORKER_POLL_SECONDS",
        ge=0.05,
        le=10,
    )
    background_task_max_attempts: int = Field(
        default=2,
        alias="BETTEROPTION_BACKGROUND_TASK_MAX_ATTEMPTS",
        ge=1,
        le=5,
    )

    background_task_retry_seconds: float = Field(
        default=2.0,
        alias="BETTEROPTION_BACKGROUND_TASK_RETRY_SECONDS",
        ge=0,
        le=300,
    )
    background_task_lease_ttl_seconds: float = Field(
        default=30.0,
        alias="BETTEROPTION_BACKGROUND_TASK_LEASE_TTL_SECONDS",
        ge=0.1,
        le=3_600,
    )
    background_task_heartbeat_seconds: float = Field(
        default=5.0,
        alias="BETTEROPTION_BACKGROUND_TASK_HEARTBEAT_SECONDS",
        ge=0.05,
        le=300,
    )
    discovery_estimated_cost_per_search_usd: float = Field(
        default=0,
        alias="BETTEROPTION_DISCOVERY_ESTIMATED_COST_PER_SEARCH_USD",
        ge=0,
    )
    brave_search_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    exa_search_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    you_search_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_YOU_SEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    openwebninja_jsearch_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    apify_eures_estimated_cost_per_run_usd: float = Field(
        default=0,
        alias="BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD",
        ge=0,
    )
    apify_jobspipe_estimated_cost_per_run_usd: float = Field(
        default=0,
        alias="BETTEROPTION_APIFY_JOBSPIPE_ESTIMATED_COST_PER_RUN_USD",
        ge=0,
    )
    apify_all_jobs_estimated_cost_per_run_usd: float = Field(
        default=0.40,
        alias="BETTEROPTION_APIFY_ALL_JOBS_ESTIMATED_COST_PER_RUN_USD",
        ge=0,
    )
    company_research_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    salary_research_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_SALARY_RESEARCH_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    google_routes_estimated_cost_per_call_usd: float = Field(
        default=0,
        alias="BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD",
        ge=0,
    )
    web_host: str = Field(default="127.0.0.1", alias="BETTEROPTION_WEB_HOST")
    web_port: int = Field(default=8000, alias="BETTEROPTION_WEB_PORT", ge=1, le=65535)

    @model_validator(mode="after")
    def local_personas_stay_on_loopback(self) -> Self:
        if not self.local_personas_enabled:
            return self
        if self.app_environment != "local" or self.auth_mode != "accounts":
            raise ValueError(
                "Local personas require BETTEROPTION_APP_ENVIRONMENT=local and "
                "BETTEROPTION_AUTH_MODE=accounts."
            )
        if self.web_host.strip().casefold() not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(
                "Local personas may only bind to a loopback web host such as 127.0.0.1."
            )
        return self

    @model_validator(mode="after")
    def background_heartbeat_precedes_lease_expiry(self) -> Self:
        if self.background_worker_enabled and self.background_worker_external:
            raise ValueError(
                "BETTEROPTION_BACKGROUND_WORKER_ENABLED and "
                "BETTEROPTION_BACKGROUND_WORKER_EXTERNAL cannot both be true."
            )
        if self.background_task_heartbeat_seconds >= self.background_task_lease_ttl_seconds:
            raise ValueError(
                "BETTEROPTION_BACKGROUND_TASK_HEARTBEAT_SECONDS must be shorter than "
                "BETTEROPTION_BACKGROUND_TASK_LEASE_TTL_SECONDS."
            )
        return self

    @property
    def operator_email_set(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold() for item in self.operator_emails.split(",") if item.strip()
        )

    @property
    def personas_enabled(self) -> bool:
        """Support the v0.7.1d local flag while using account-owned personas."""

        return self.account_personas_enabled or self.local_personas_enabled

    @property
    def openai_api_key_value(self) -> str | None:
        """Return the configured key only at the provider-construction boundary."""

        if self.openai_api_key is None:
            return None
        value = self.openai_api_key.get_secret_value().strip()
        return value or None

    @property
    def openwebninja_jsearch_api_key_value(self) -> str | None:
        """Return the JSearch key only at the provider-construction boundary."""

        if self.openwebninja_jsearch_api_key is None:
            return None
        value = self.openwebninja_jsearch_api_key.get_secret_value().strip()
        return value or None

    @property
    def apify_api_token_value(self) -> str | None:
        """Return the Apify token only at the provider-construction boundary."""

        if self.apify_api_token is None:
            return None
        value = self.apify_api_token.get_secret_value().strip()
        return value or None

    @property
    def application_guidance_available(self) -> bool:
        """Keep local use available and make every hosted environment fail closed."""

        if not self.application_guidance_enabled:
            return False
        if self.app_environment == "local":
            return True
        return self.legal_review_completed and self.processor_review_completed

    @property
    def employer_job_posting_available(self) -> bool:
        """Allow local preparation while every hosted environment fails closed."""

        if self.app_environment == "local":
            return True
        return bool(
            self.employer_job_posting_enabled
            and self.legal_review_completed
            and self.processor_review_completed
            and self.incident_plan_ready
            and self.operator_email_set
        )

    def model_policy(self) -> ModelPolicy:
        return ModelPolicy(
            [
                ModelRoute(
                    task=LLMTask.PROFILE_EXTRACTION,
                    provider=self.llm_provider,
                    model=self.profile_extraction_model or self.openai_model,
                    prompt_version="profile-v0.6.9",
                    input_cost_per_million_usd=self.openai_input_cost_per_million_usd,
                    output_cost_per_million_usd=self.openai_output_cost_per_million_usd,
                ),
                ModelRoute(
                    task=LLMTask.JOB_EXTRACTION,
                    provider=self.llm_provider,
                    model=self.job_extraction_model or self.openai_model,
                    prompt_version="job-v0.7.1o",
                    input_cost_per_million_usd=self.openai_input_cost_per_million_usd,
                    output_cost_per_million_usd=self.openai_output_cost_per_million_usd,
                ),
                ModelRoute(
                    task=LLMTask.MATCH_EXPLANATION,
                    provider=self.llm_provider,
                    model=self.match_explanation_model or self.openai_model,
                    prompt_version="match-evidence-v0.7.2i",
                    input_cost_per_million_usd=self.openai_input_cost_per_million_usd,
                    output_cost_per_million_usd=self.openai_output_cost_per_million_usd,
                ),
                ModelRoute(
                    task=LLMTask.APPLICATION_DRAFT,
                    provider=self.llm_provider,
                    model=self.application_draft_model or self.openai_model,
                    prompt_version="application-draft-v0.7.1o",
                    input_cost_per_million_usd=self.openai_input_cost_per_million_usd,
                    output_cost_per_million_usd=self.openai_output_cost_per_million_usd,
                ),
                ModelRoute(
                    task=LLMTask.SALARY_RESEARCH,
                    provider=self.llm_provider,
                    model=self.salary_research_model or self.openai_model,
                    prompt_version="salary-research-v0.7.1o",
                    input_cost_per_million_usd=self.openai_input_cost_per_million_usd,
                    output_cost_per_million_usd=self.openai_output_cost_per_million_usd,
                ),
            ]
        )
