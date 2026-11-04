"""Secret-safe diagnostics for BetterOption's effective local configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

from .settings import Settings


_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_YOU_SEARCH_KEY_NAMES = (
    "YDC_API_KEY",
    "BETTEROPTION_YOU_SEARCH_API_KEY",
    "YOU_SEARCH_API_KEY",
)
_SUPERSEDED_PRIVACY_DRAFT_VERSIONS = {
    "2026-08-01-draft",
    "2026-08-02-draft",
    "2026-08-04-draft",
    "2026-08-04b-draft",
    "2026-08-05-draft",
}


def duplicate_environment_keys(path: Path) -> dict[str, list[int]]:
    """Return duplicate assignment line numbers without reading values into output."""

    if not path.is_file():
        return {}
    occurrences: dict[str, list[int]] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        match = _ASSIGNMENT.match(raw_line.strip())
        if match is not None:
            occurrences.setdefault(match.group(1), []).append(line_number)
    return {key: line_numbers for key, line_numbers in occurrences.items() if len(line_numbers) > 1}


def secret_is_configured(environment: Mapping[str, str], key: str) -> bool:
    """Identify a non-placeholder credential without returning its value."""

    value = environment.get(key, "").strip()
    normalized = value.casefold()
    placeholders = ("replace-with", "placeholder", "your-api-key", "<your")
    return bool(value and not any(marker in normalized for marker in placeholders))


def _configured(environment: Mapping[str, str], key: str) -> str:
    return "configured" if secret_is_configured(environment, key) else "not configured"


def _effective_environment(
    environment: Mapping[str, str],
    env_path: Path,
) -> dict[str, str]:
    """Return file-backed presence plus process overrides without exposing values."""

    effective = {
        key: value or "" for key, value in dotenv_values(env_path).items() if key is not None
    }
    effective.update(environment)
    return effective


def secret_safe_configuration_report(
    settings: Settings,
    *,
    environment: Mapping[str, str] | None = None,
    env_path: Path = Path(".env"),
) -> str:
    """Describe effective settings while never returning keys, tokens, or credentials."""

    environment = _effective_environment(
        os.environ if environment is None else environment,
        env_path,
    )
    duplicates = duplicate_environment_keys(env_path)
    brave_search_configured = secret_is_configured(environment, "BRAVE_SEARCH_API_KEY")
    brave_answers_configured = secret_is_configured(environment, "BRAVE_ANSWERS_API_KEY")
    configured_you_key = next(
        (key for key in _YOU_SEARCH_KEY_NAMES if secret_is_configured(environment, key)),
        None,
    )
    you_configuration = (
        "configured via YDC_API_KEY"
        if configured_you_key == "YDC_API_KEY"
        else "configured via supported alias"
        if configured_you_key is not None
        else "not configured"
    )
    lines = [
        "BetterOption effective configuration",
        f"- Authentication: {settings.auth_mode}",
        f"- Registration: {settings.registration_mode}",
        f"- Secure session cookie: {str(settings.auth_secure_cookie).lower()}",
        f"- Database backend: {settings.database_url.split(':', 1)[0]}",
        (
            "- Providers: "
            f"OpenAI {_configured(environment, 'OPENAI_API_KEY')}; "
            f"Exa {_configured(environment, 'EXA_API_KEY')}; "
            f"Google Routes {_configured(environment, 'GOOGLE_ROUTES_API_KEY')}; "
            f"openrouteservice {_configured(environment, 'OPENROUTESERVICE_API_KEY')}"
        ),
        (
            "- Brave Search (BRAVE_SEARCH_API_KEY): "
            f"{'configured' if brave_search_configured else 'not configured'}; "
            "this Search-plan key powers Explore Web Search and employer research"
        ),
        (
            "- Brave Answers (BRAVE_ANSWERS_API_KEY): "
            f"{'configured but unused' if brave_answers_configured else 'not configured and unused'}; "
            "BetterOption does not call the separate Answers product"
        ),
        (
            "- You.com Search (YDC_API_KEY; aliases BETTEROPTION_YOU_SEARCH_API_KEY, "
            f"YOU_SEARCH_API_KEY): {you_configuration}"
        ),
        (
            "- OpenWebNinja JSearch (OPENWEBNINJA_JSEARCH_API_KEY): "
            f"{_configured(environment, 'OPENWEBNINJA_JSEARCH_API_KEY')}; "
            f"max focused requests={settings.openwebninja_jsearch_max_requests}; "
            f"connect/read/provider budget={settings.openwebninja_jsearch_connect_timeout_seconds:g}/"
            f"{settings.openwebninja_jsearch_read_timeout_seconds:g}/"
            f"{settings.openwebninja_jsearch_search_budget_seconds:g}s; "
            "account-controlled and costed per actual request"
        ),
        (
            "- EURES via Apify (APIFY_API_TOKEN): "
            f"{_configured(environment, 'APIFY_API_TOKEN')}; "
            f"max results={settings.apify_eures_max_results}; "
            "account-controlled and costed per actor run"
        ),
        (
            "- JobsPipe via Apify (APIFY_API_TOKEN): "
            f"{_configured(environment, 'APIFY_API_TOKEN')}; "
            f"max results={settings.apify_jobspipe_max_results}; "
            f"posted within={settings.apify_jobspipe_posted_within_days} days; "
            "up to 4 independent one-keyword actor runs, account-controlled and "
            "costed per actual run"
        ),
        (
            "- All Jobs Scraper via Apify (APIFY_API_TOKEN): "
            f"{_configured(environment, 'APIFY_API_TOKEN')}; "
            f"results per platform={settings.apify_all_jobs_max_results_per_platform}; "
            f"readback/presentation max items={settings.apify_all_jobs_max_items}; "
            "pay-per-event charge ceiling USD="
            f"{settings.apify_all_jobs_max_total_charge_usd:.2f}; "
            "estimated cost/run USD="
            f"{settings.apify_all_jobs_estimated_cost_per_run_usd:.2f}; "
            f"hosted enabled={str(settings.apify_all_jobs_hosted_enabled).lower()}; "
            "one paid actor run with bounded polling and dataset fetch; separate permission "
            "and cost estimate"
        ),
        (
            "- Explore source policy: "
            f"call all configured providers={str(settings.discovery_call_all_providers).lower()}; "
            f"shared budget={settings.discovery_search_budget_seconds:g}s; "
            f"final result limit=300"
        ),
        (
            "- Mobility: "
            f"provider={settings.mobility_provider}; "
            f"privacy={settings.mobility_privacy_mode}; "
            f"exact-route jobs={settings.exact_route_match_limit}"
        ),
        (
            "- Salary research: "
            f"enabled={str(settings.salary_research_enabled).lower()}; "
            f"provider={settings.llm_provider}; "
            f"max jobs={settings.salary_research_max_jobs}; "
            f"max Web Search calls={settings.salary_research_max_tool_calls}; "
            "public job evidence only"
        ),
        (
            "- Semantic match evidence: "
            f"provider={settings.llm_provider}; "
            f"OpenAI key={_configured(environment, 'OPENAI_API_KEY')}; "
            f"max jobs={settings.match_evidence_max_jobs}; "
            "fixed batches of 5; unresolved confirmed criteria + public job facts only"
        ),
        (
            "- Provider guards: "
            f"daily operations={settings.provider_daily_operation_limit}; "
            f"workflow operations={settings.provider_action_operation_limit}; "
            f"daily cost USD={settings.provider_daily_cost_limit_usd:g}; "
            f"workflow cost USD={settings.provider_action_cost_limit_usd:g}"
        ),
        (
            "- Background worker: "
            f"enabled={str(settings.background_worker_enabled).lower()}; "
            f"external={str(settings.background_worker_external).lower()}; "
            f"poll={settings.background_worker_poll_seconds:g}s; "
            f"attempts={settings.background_task_max_attempts}; "
            f"lease={settings.background_task_lease_ttl_seconds:g}s; "
            f"heartbeat={settings.background_task_heartbeat_seconds:g}s"
        ),
    ]
    if duplicates:
        lines.append("- Duplicate .env assignments detected (the last assignment wins):")
        for key, line_numbers in sorted(duplicates.items()):
            joined = ", ".join(str(line_number) for line_number in line_numbers)
            lines.append(f"  - {key}: lines {joined}")
    else:
        lines.append("- Duplicate .env assignments: none")
    if settings.auth_mode == "accounts" and not settings.auth_secure_cookie:
        lines.append(
            "- HTTPS reminder: set BETTEROPTION_AUTH_SECURE_COOKIE=true before online use."
        )
    if settings.app_environment == "local" and settings.registration_mode == "open":
        lines.append(
            "- Local registration note: open permits new test accounts until you change "
            "BETTEROPTION_REGISTRATION_MODE to disabled and restart."
        )
    if (
        "BETTEROPTION_EXA_FALLBACK_MIN_RESULTS" in environment
        and "BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS" not in environment
    ):
        lines.append(
            "- Environment cleanup: BETTEROPTION_EXA_FALLBACK_MIN_RESULTS is a supported "
            "legacy alias; rename it to BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS. "
            "It is inactive while call-all-providers is true."
        )
    if settings.provider_daily_cost_limit_usd == 0 or settings.provider_action_cost_limit_usd == 0:
        lines.append(
            "- Cost guard warning: a zero USD ceiling disables that monetary guard; enter "
            "measured provider prices and non-zero ceilings before inviting testers."
        )
    if settings.legal_privacy_version in _SUPERSEDED_PRIVACY_DRAFT_VERSIONS:
        lines.append(
            "- Privacy notice warning: the configured draft predates account-owned product "
            "feedback; review the updated notice, set "
            "BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-feedback-draft, and restart."
        )
    if settings.app_environment != "local":
        if not settings.public_base_url.casefold().startswith("https://"):
            lines.append(
                "- Hosted warning: BETTEROPTION_PUBLIC_BASE_URL must be the public HTTPS URL."
            )
        if not settings.auth_secure_cookie:
            lines.append("- Hosted warning: BETTEROPTION_AUTH_SECURE_COOKIE must be true.")
        if settings.registration_mode not in {"invite_only", "disabled"}:
            lines.append(
                "- Hosted warning: use invite_only or disabled registration for the private alpha."
            )
        if settings.database_url.casefold().startswith("sqlite"):
            lines.append("- Hosted warning: use PostgreSQL instead of SQLite.")
        if not settings.auth_rate_limit_secret.strip():
            lines.append(
                "- Hosted warning: configure a deployment-specific AUTH_RATE_LIMIT_SECRET."
            )
        if not settings.operator_emails.strip():
            lines.append(
                "- Hosted warning: configure BETTEROPTION_OPERATOR_EMAILS for Operations access."
            )
    if brave_answers_configured:
        lines.append(
            "- Brave reminder: an Answers-only key cannot authorize Explore. Keep it separate "
            "and configure BRAVE_SEARCH_API_KEY from an active Search plan."
        )
    if settings.salary_research_enabled and not secret_is_configured(
        environment,
        "OPENAI_API_KEY",
    ):
        lines.append(
            "- Salary research warning: disable it or configure OPENAI_API_KEY before startup."
        )
    return "\n".join(lines)
