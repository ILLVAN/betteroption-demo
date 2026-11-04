"""Account-owned authorization for optional external providers.

Deployment configuration decides which adapters are technically available.
These preferences form a second, narrower gate: an authenticated account can
allow only the providers it wants BetterOption to call.  Personas deliberately
cannot widen or narrow this account boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID

from pydantic import Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .profile import StrictModel


class ProviderPermissionError(ValueError):
    """Raised when an account submits an invalid provider choice."""


class ProviderPermissionDenied(RuntimeError):
    """Raised before a provider call which the active account did not allow."""


class AccountProviderPreferenceRow(Base):
    __tablename__ = "account_provider_preferences"

    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderChoice(StrictModel):
    key: str
    label: str
    purpose: str
    enabled: bool = False
    available: bool = False
    availability_note: str = ""


class ProviderDefinition(StrictModel):
    key: str
    label: str
    purpose: str
    default_enabled: bool = True
    aliases: tuple[str, ...] = Field(default_factory=tuple)


# Locally available adapters start enabled for the current evaluation cycle;
# the account owner may still narrow them at any time. An unavailable adapter
# can never make a call regardless of its saved choice, and hosted deployment
# gates remain independent of this preference default.
PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        key="openai",
        label="OpenAI",
        purpose="Compass and job extraction, salary orientation, and cover-letter drafts.",
        aliases=("openai-salary", "openai-salary-web-search"),
    ),
    ProviderDefinition(
        key="arbeitnow",
        label="Arbeitnow",
        purpose="Keyless public job-feed discovery in Explore.",
    ),
    ProviderDefinition(
        key="brave",
        label="Brave Search",
        purpose="Broader employer-source discovery and optional company research.",
        aliases=("brave-web", "brave-search", "brave-company"),
    ),
    ProviderDefinition(
        key="exa",
        label="Exa",
        purpose="Focused semantic role and employer-page discovery in Explore.",
        aliases=("exa-fallback",),
    ),
    ProviderDefinition(
        key="you",
        label="You.com Search",
        purpose="Optional semantic Explore source returning public web-search candidates.",
        aliases=("you-web",),
    ),
    ProviderDefinition(
        key="jsearch",
        label="OpenWebNinja JSearch",
        purpose="Structured job discovery across public job sites and aggregators.",
        aliases=("openwebninja-jsearch", "openwebninja"),
    ),
    ProviderDefinition(
        key="eures",
        label="EURES via Apify",
        purpose="Structured European public-vacancy discovery through the EURES actor.",
        aliases=("apify-eures", "eures-apify"),
    ),
    ProviderDefinition(
        key="jobspipe",
        label="JobsPipe via Apify",
        purpose="Structured multi-source job discovery through the separate JobsPipe actor.",
        aliases=("apify-jobspipe", "jobspipe-apify"),
    ),
    ProviderDefinition(
        key="all-jobs",
        label="All Jobs Scraper via Apify",
        purpose=("Structured local and multi-board discovery through the separate AgentX actor."),
        aliases=("apify-all-jobs", "all-jobs-scraper", "agentx-all-jobs"),
    ),
    ProviderDefinition(
        key="ats",
        label="Employer ATS boards",
        purpose="Public Greenhouse, Lever, and Ashby job-board APIs.",
        aliases=("greenhouse", "lever", "ashby"),
    ),
    ProviderDefinition(
        key="wikimedia",
        label="Wikimedia",
        purpose="Public company context used as optional matching evidence.",
        aliases=("wikimedia-company",),
    ),
    ProviderDefinition(
        key="google-routes",
        label="Google Routes",
        purpose="Exact commute estimates when balanced mobility mode is configured.",
    ),
    ProviderDefinition(
        key="transitous",
        label="Transitous",
        purpose="Public-transport commute estimates.",
    ),
    ProviderDefinition(
        key="openrouteservice",
        label="openrouteservice",
        purpose="Driving, cycling, and walking route estimates.",
    ),
    ProviderDefinition(
        key="valhalla",
        label="Valhalla / FOSSGIS",
        purpose="OpenStreetMap-based driving, cycling, and walking routes.",
        aliases=("valhalla-osm",),
    ),
    ProviderDefinition(
        key="nominatim",
        label="OpenStreetMap Nominatim",
        purpose="Fallback place resolution for otherwise unresolved route endpoints.",
        aliases=("osm-geocoder",),
    ),
)

KNOWN_PROVIDER_KEYS = frozenset(definition.key for definition in PROVIDER_DEFINITIONS)
DEFAULT_PROVIDER_KEYS = frozenset(
    definition.key for definition in PROVIDER_DEFINITIONS if definition.default_enabled
)
_PROVIDER_ALIASES = {
    alias.casefold(): definition.key
    for definition in PROVIDER_DEFINITIONS
    for alias in (definition.key, *definition.aliases)
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def permission_key_for_provider(provider: str) -> str:
    normalized = provider.strip().casefold()
    return _PROVIDER_ALIASES.get(normalized, normalized)


class ProviderPermissionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    def enabled_keys(self, account_id: UUID) -> frozenset[str]:
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    AccountProviderPreferenceRow.provider_key,
                    AccountProviderPreferenceRow.enabled,
                ).where(AccountProviderPreferenceRow.account_id == str(account_id))
            ).all()
        explicit = {str(key): bool(enabled) for key, enabled in rows}
        return frozenset(
            key for key in KNOWN_PROVIDER_KEYS if explicit.get(key, key in DEFAULT_PROVIDER_KEYS)
        )

    def choices(
        self,
        account_id: UUID,
        *,
        availability: dict[str, tuple[bool, str]],
    ) -> list[ProviderChoice]:
        enabled = self.enabled_keys(account_id)
        return [
            ProviderChoice(
                key=definition.key,
                label=definition.label,
                purpose=definition.purpose,
                enabled=(
                    definition.key in enabled
                    and availability.get(definition.key, (False, "Not configured"))[0]
                ),
                available=availability.get(definition.key, (False, "Not configured"))[0],
                availability_note=availability.get(
                    definition.key,
                    (False, "Not configured"),
                )[1],
            )
            for definition in PROVIDER_DEFINITIONS
        ]

    def replace(
        self,
        account_id: UUID,
        enabled_keys: set[str],
        *,
        available_keys: set[str],
    ) -> frozenset[str]:
        unknown = enabled_keys - KNOWN_PROVIDER_KEYS
        if unknown:
            raise ProviderPermissionError("Unknown provider selection.")
        unavailable = enabled_keys - available_keys
        if unavailable:
            raise ProviderPermissionError(
                "A selected provider is not available in this installation."
            )
        now = utc_now()
        with self.session_factory.begin() as session:
            if available_keys:
                session.execute(
                    delete(AccountProviderPreferenceRow).where(
                        AccountProviderPreferenceRow.account_id == str(account_id),
                        AccountProviderPreferenceRow.provider_key.in_(sorted(available_keys)),
                    )
                )
            session.add_all(
                AccountProviderPreferenceRow(
                    account_id=str(account_id),
                    provider_key=key,
                    enabled=key in enabled_keys,
                    updated_at=now,
                )
                for key in sorted(available_keys)
            )
        return self.enabled_keys(account_id)


_ACTIVE_PROVIDER_KEYS: ContextVar[frozenset[str] | None] = ContextVar(
    "betteroption_active_provider_keys",
    default=None,
)
_ACTIVE_PROVIDER_ACCOUNT_ID: ContextVar[UUID | None] = ContextVar(
    "betteroption_active_provider_account_id",
    default=None,
)


def provider_permission_allowed(provider: str) -> bool:
    """Return true when the local runtime or active account permits a provider.

    ``None`` means that there is no authenticated account boundary (CLI/local
    service construction and migration tooling).  Account requests and their
    background tasks always set an explicit set, including an empty set.
    """

    enabled = _ACTIVE_PROVIDER_KEYS.get()
    if enabled is None:
        return True
    return permission_key_for_provider(provider) in enabled


def current_provider_account_id() -> UUID | None:
    """Return only the opaque account identifier for operation attribution."""

    return _ACTIVE_PROVIDER_ACCOUNT_ID.get()


def require_provider_permission(provider: str) -> None:
    if provider_permission_allowed(provider):
        return
    key = permission_key_for_provider(provider)
    definition = next(
        (item for item in PROVIDER_DEFINITIONS if item.key == key),
        None,
    )
    label = definition.label if definition is not None else provider
    raise ProviderPermissionDenied(
        f"{label} is disabled for this account. Enable it under Account → Provider choices."
    )


@contextmanager
def provider_permission_scope(
    enabled_keys: frozenset[str] | set[str] | None,
    *,
    account_id: UUID | None = None,
):
    token = _ACTIVE_PROVIDER_KEYS.set(None if enabled_keys is None else frozenset(enabled_keys))
    account_token = _ACTIVE_PROVIDER_ACCOUNT_ID.set(account_id)
    try:
        yield
    finally:
        _ACTIVE_PROVIDER_ACCOUNT_ID.reset(account_token)
        _ACTIVE_PROVIDER_KEYS.reset(token)


@contextmanager
def account_provider_permission_scope(
    repository: ProviderPermissionRepository,
    account_id: UUID | None,
):
    with provider_permission_scope(
        repository.enabled_keys(account_id) if account_id is not None else None,
        account_id=account_id,
    ):
        yield
