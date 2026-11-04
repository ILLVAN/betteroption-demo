"""Small deployment commands that do not print secrets."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from . import __version__
from .accounts import AccountRepository
from .database import Database, resolve_database_url, run_schema_migrations
from .settings import Settings


@dataclass(frozen=True)
class PreflightReport:
    """Secret-free deployment validation result."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    passed: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class AccountPreflightState:
    """Content-free account state needed to validate bootstrap registration."""

    account_count: int
    admin_count: int
    allowlisted_account_count: int


def inspect_account_state(settings: Settings) -> AccountPreflightState:
    """Read only aggregate account state without exposing account identifiers."""

    database = Database(settings.database_url)
    try:
        repository = AccountRepository(database)
        accounts = repository.list_accounts()
        return AccountPreflightState(
            account_count=len(accounts),
            admin_count=sum(1 for account in accounts if account.is_admin),
            allowlisted_account_count=sum(
                1 for account in accounts if account.email.casefold() in settings.operator_email_set
            ),
        )
    finally:
        database.engine.dispose()


def _database_password_is_safe(database_url: str) -> bool:
    password = make_url(database_url).password or ""
    normalized = password.casefold()
    placeholder_markers = (
        "change-me",
        "changeme",
        "example",
        "password",
        "replace",
        "secret",
    )
    return len(password) >= 32 and not any(marker in normalized for marker in placeholder_markers)


def _secret_is_safe(value: str) -> bool:
    normalized = value.casefold()
    placeholder_markers = (
        "change-me",
        "changeme",
        "example",
        "replace",
        "secret",
    )
    return len(value) >= 32 and not any(marker in normalized for marker in placeholder_markers)


def inspect_preflight(
    settings: Settings | None = None,
    *,
    openai_api_key_present: bool | None = None,
    account_state: AccountPreflightState | None = None,
) -> PreflightReport:
    """Validate the online staging boundary without making network calls."""

    configured = settings or Settings()
    errors: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    database_url = resolve_database_url(configured.database_url)
    backend = make_url(database_url).get_backend_name()
    if backend != "postgresql":
        errors.append("BETTEROPTION_DATABASE_URL must use PostgreSQL for online staging.")
    else:
        passed.append("PostgreSQL is configured.")

    if not _database_password_is_safe(database_url):
        errors.append(
            "The database password must be at least 32 characters and not be a placeholder."
        )
    else:
        passed.append("The database password passes the non-placeholder length check.")

    if configured.app_environment not in {"staging", "production"}:
        errors.append("BETTEROPTION_APP_ENVIRONMENT must be staging or production.")
    else:
        passed.append(f"Application environment is {configured.app_environment}.")

    if configured.auth_mode != "accounts":
        errors.append("BETTEROPTION_AUTH_MODE must be accounts.")
    else:
        passed.append("Account isolation is enabled.")

    if not configured.auth_secure_cookie:
        errors.append("BETTEROPTION_AUTH_SECURE_COOKIE must be true.")
    else:
        passed.append("Secure browser cookies are enabled.")

    public_url = urlparse(configured.public_base_url)
    if (
        public_url.scheme != "https"
        or not public_url.netloc
        or public_url.username
        or public_url.password
    ):
        errors.append("BETTEROPTION_PUBLIC_BASE_URL must be a credential-free absolute HTTPS URL.")
    else:
        passed.append(f"Public HTTPS origin is {public_url.netloc}.")

    if not configured.operator_email_set:
        errors.append("BETTEROPTION_OPERATOR_EMAILS must name at least one operator account.")
    else:
        passed.append("At least one operator email is configured.")

    if configured.registration_mode == "open":
        warnings.append(
            "Registration is open. Use first_user only for owner bootstrap, then disable it."
        )
    elif configured.registration_mode == "first_user":
        warnings.append(
            "Registration is in first-user bootstrap mode. Disable it immediately after "
            "creating the owner account."
        )
    elif configured.registration_mode == "invite_only":
        passed.append("Registration is restricted to operator-created invitations.")
    else:
        passed.append("Public registration is disabled.")

    if account_state is not None:
        if account_state.admin_count > account_state.account_count:
            errors.append("The database account-role state is inconsistent.")
        elif configured.registration_mode == "first_user":
            if account_state.account_count != 0:
                errors.append(
                    "first_user registration requires an empty account database. Use an "
                    "existing database admin or the legacy allowlisted-account bridge instead."
                )
            else:
                passed.append(
                    "The empty database is ready for one exact-allowlisted owner bootstrap."
                )
        elif account_state.account_count == 0:
            errors.append(
                "The database has no owner. Use first_user behind the exact-email access "
                "policy before switching to invite_only or disabled registration."
            )
        elif account_state.admin_count > 0:
            passed.append("At least one persisted database admin exists.")
        elif account_state.allowlisted_account_count > 0:
            warnings.append(
                "The legacy bootstrap bridge is active because this upgraded database has no "
                "persisted admin yet. An existing allowlisted account may enter Operations "
                "once to grant the first database admin."
            )
        else:
            errors.append(
                "The existing database has no admin and no matching legacy allowlisted account."
            )

    if not _secret_is_safe(configured.auth_rate_limit_secret):
        errors.append(
            "BETTEROPTION_AUTH_RATE_LIMIT_SECRET must be a unique non-placeholder value "
            "of at least 32 characters."
        )
    else:
        passed.append("Authentication attempt identifiers use a deployment-specific HMAC secret.")

    if configured.auth_trust_cloudflare_headers:
        passed.append(
            "Cloudflare visitor addresses are trusted for authentication rate limits; "
            "direct origin access must remain restricted."
        )
    else:
        passed.append(
            "Authentication rate limits use the direct peer address; Cloudflare visitor "
            "headers remain untrusted."
        )

    if openai_api_key_present is None:
        openai_api_key_present = bool(configured.openai_api_key_value)
    if not openai_api_key_present:
        warnings.append(
            "OPENAI_API_KEY is absent; AI structuring is unavailable. Ordinary Compass text "
            "will still be saved locally as a direct editable statement."
        )

    if configured.provider_daily_cost_limit_usd == 0:
        warnings.append(
            "The daily monetary provider limit is disabled; configure it after entering "
            "current provider prices."
        )
    if configured.provider_action_cost_limit_usd == 0:
        warnings.append(
            "The per-action monetary provider limit is disabled; configure it after entering "
            "current provider prices."
        )
    if (
        configured.openai_input_cost_per_million_usd is None
        or configured.openai_output_cost_per_million_usd is None
        or configured.openai_input_cost_per_million_usd <= 0
        or configured.openai_output_cost_per_million_usd <= 0
    ):
        warnings.append(
            "OpenAI token pricing is unpriced. Numeric zero is accepted as the explicit "
            "unknown-price sentinel; it never means free."
        )

    passed.append(
        "Automatic retention is bounded to "
        f"{configured.retention_raw_compass_days} days for raw Compass content, "
        f"{configured.retention_rejected_fact_days} days for rejected facts, "
        f"{configured.retention_provider_telemetry_days} days for provider telemetry, and "
        f"{configured.retention_product_feedback_days} days for product feedback."
    )
    if (
        configured.app_environment in {"staging", "production"}
        and not configured.processor_review_completed
    ):
        warnings.append(
            "External AI, search, geocoding, and routing integrations remain runtime-blocked "
            "until the processor review is complete."
        )

    readiness_flags = (
        ("legal review", configured.legal_review_completed),
        ("processor review", configured.processor_review_completed),
        ("incident plan", configured.incident_plan_ready),
        ("backup restore drill", configured.backup_restore_tested),
    )
    missing_flags = [label for label, complete in readiness_flags if not complete]
    if missing_flags:
        warnings.append(
            "External invitations remain blocked by incomplete readiness items: "
            + ", ".join(missing_flags)
            + "."
        )
    else:
        passed.append("All operator-managed readiness flags are complete.")
        if configured.registration_mode == "invite_only" and (
            account_state is None or account_state.admin_count > 0
        ):
            passed.append("External invitation creation is unlocked.")

    return PreflightReport(
        errors=tuple(errors),
        warnings=tuple(warnings),
        passed=tuple(passed),
    )


def preflight(
    settings: Settings | None = None,
    *,
    account_state: AccountPreflightState | None = None,
) -> bool:
    """Print a secret-free staging report and return whether hard checks pass."""

    configured = settings or Settings()
    account_state_error = False
    if account_state is None and _database_password_is_safe(configured.database_url):
        try:
            account_state = inspect_account_state(configured)
        except Exception:
            account_state_error = True
    report = inspect_preflight(configured, account_state=account_state)
    if account_state_error:
        report = PreflightReport(
            errors=(
                *report.errors,
                "The migrated database account state could not be inspected safely.",
            ),
            warnings=report.warnings,
            passed=report.passed,
        )
    print(f"BetterOption {__version__} deployment preflight")
    for item in report.passed:
        print(f"PASS: {item}")
    for item in report.warnings:
        print(f"WARN: {item}")
    for item in report.errors:
        print(f"FAIL: {item}")
    print(
        f"Result: {'READY FOR STAGING' if report.ready else 'BLOCKED'} "
        f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))."
    )
    return report.ready


def migrate(database_url: str | None = None) -> None:
    """Upgrade the configured database to the packaged Alembic head."""

    resolved = resolve_database_url(database_url)
    run_schema_migrations(resolved)
    print(f"BetterOption {__version__}: database schema is current.")


def describe(database_url: str | None = None) -> None:
    """Describe the deployment target without exposing credentials."""

    url = make_url(resolve_database_url(database_url))
    host = url.host or "local file"
    print(f"BetterOption {__version__}")
    print(f"Database backend: {url.get_backend_name()}")
    print(f"Database host: {host}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BetterOption deployment utilities")
    parser.add_argument("command", choices=("migrate", "describe", "preflight"))
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "describe":
        describe()
    else:
        return 0 if preflight() else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
