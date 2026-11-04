from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from betteroption.accounts import RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.discovery import (
    BraveWebDiscoveryProvider,
    DiscoveredJob,
    DiscoveryAvailabilityFilter,
    DiscoveryError,
    DiscoveryQuery,
    _portal_search_texts,
    web_discovery_matches_portal,
)
from betteroption.discovery_sources import ExaFallbackDiscoveryProvider
from betteroption.explore_repository import ExploreSearchRepository
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
)
from betteroption.portal_sources import (
    PortalSourceError,
    PortalSourceRepository,
    normalize_portal_url,
    portal_search_scope,
)
from betteroption.provider_permissions import (
    DEFAULT_PROVIDER_KEYS,
    ProviderPermissionError,
    provider_permission_scope,
)
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"
PUBLIC_IP = "93.184.216.34"


def settings(tmp_path: Path) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'providers.db').as_posix()}",
        app_environment="local",
        auth_mode="accounts",
        registration_mode="open",
        account_personas_enabled=True,
        background_worker_enabled=False,
        employer_homepage_research=False,
        transitous_enabled=False,
        valhalla_enabled=False,
        osm_geocoder_enabled=False,
    )


def create_account(container: ApplicationContainer, email: str, name: str):
    account = container.accounts.create(
        email,
        name,
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    persona = container.personas.ensure_main(
        account.id,
        maximum_personas=5,
    )
    return account, persona


class CountingDiscoveryProvider:
    name = "arbeitnow"
    attribution = "Counting public feed"
    attribution_url = "https://example.com/feed"

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.calls += 1
        return []


class CapturingDiscoveryProvider:
    name = "test-discovery"
    attribution = "Test discovery"
    attribution_url = "https://example.com"

    def __init__(self) -> None:
        self.queries: list[DiscoveryQuery] = []

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.queries.append(query)
        return []


def register(client: TestClient) -> None:
    response = client.post(
        "/register",
        data={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": PASSWORD,
            "accept_terms": "yes",
            "acknowledge_privacy": "yes",
            "confirm_adult": "yes",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_account_provider_preferences_keep_explicit_opt_in_account_wide(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    alice, _ = create_account(container, "alice@example.com", "Alice")
    bob, _ = create_account(container, "bob@example.com", "Bob")

    assert container.provider_permissions.enabled_keys(alice.id) == DEFAULT_PROVIDER_KEYS
    saved = container.provider_permissions.replace(
        alice.id,
        {"arbeitnow"},
        available_keys={"arbeitnow"},
    )
    assert saved == DEFAULT_PROVIDER_KEYS
    assert container.provider_permissions.enabled_keys(alice.id) == DEFAULT_PROVIDER_KEYS
    assert container.provider_permissions.enabled_keys(bob.id) == DEFAULT_PROVIDER_KEYS
    with pytest.raises(ProviderPermissionError, match="not available"):
        container.provider_permissions.replace(
            alice.id,
            {"openai"},
            available_keys={"arbeitnow"},
        )


def test_disabled_provider_is_not_called_or_costed_and_unpriced_usage_stays_unknown(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account, _ = create_account(container, "owner@example.com", "Owner")
    ledger = ProviderOperationLedger(container.database)
    raw = CountingDiscoveryProvider()
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0.75,
    )
    query = DiscoveryQuery(text="quality engineer")

    with provider_permission_scope(frozenset(), account_id=account.id):
        with pytest.raises(DiscoveryError, match="provider choices"):
            provider.search(query)
    assert raw.calls == 0

    with provider_permission_scope(frozenset({"arbeitnow"}), account_id=account.id):
        unpriced = RecordingDiscoveryProvider(
            raw,
            ledger,
            ProviderBudgetPolicy(ledger),
            estimated_cost_usd=None,
        )
        assert unpriced.search(query) == []
    assert raw.calls == 1

    with container.database.session_factory() as session:
        rows = session.scalars(
            select(ProviderOperationRow).order_by(ProviderOperationRow.started_at.asc())
        ).all()
    assert len(rows) == 2
    assert rows[0].account_id == str(account.id)
    assert rows[0].outcome == "blocked"
    assert rows[0].error_type == "AccountProviderDisabled"
    assert rows[0].estimated_cost_usd is None
    assert rows[1].account_id == str(account.id)
    assert rows[1].estimated_cost_usd is None
    summary = ledger.summary_since(account_id=account.id)
    assert summary.blocked_operations == 1
    assert summary.costed_operations == 0
    assert summary.unpriced_operations == 1


def test_portals_are_https_ssrf_safe_limited_and_persona_isolated(tmp_path: Path) -> None:
    container = ApplicationContainer(settings(tmp_path))
    alice, alice_persona = create_account(container, "alice@example.com", "Alice")
    bob, bob_persona = create_account(container, "bob@example.com", "Bob")
    portals = PortalSourceRepository(
        container.database,
        resolver=lambda _host: [PUBLIC_IP],
    )

    source = portals.create(
        alice_persona.id,
        account_id=alice.id,
        url="https://jobs.example.com/careers/?tracking=discarded#openings",
        label="Example employer",
        maximum_sources=1,
    )
    assert source.portal_url == "https://jobs.example.com/careers"
    assert portals.enabled_hostnames(
        alice_persona.id,
        account_id=alice.id,
    ) == ["jobs.example.com"]
    assert portals.list_for_persona(bob_persona.id, account_id=bob.id) == []
    with pytest.raises(PortalSourceError, match="Persona not found"):
        portals.list_for_persona(alice_persona.id, account_id=bob.id)
    with pytest.raises(PortalSourceError, match="up to 1"):
        portals.create(
            alice_persona.id,
            account_id=alice.id,
            url="https://careers.second.example/jobs",
            maximum_sources=1,
        )

    with pytest.raises(PortalSourceError, match="must use HTTPS"):
        normalize_portal_url("http://jobs.example.com", resolver=lambda _host: [PUBLIC_IP])
    with pytest.raises(PortalSourceError, match="Private, local"):
        normalize_portal_url("https://localhost/jobs", resolver=lambda _host: ["127.0.0.1"])


def test_account_page_controls_permissions_and_portal_domains_reach_explore_query(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        settings(tmp_path).model_copy(update={"brave_search_api_key": "test-brave-key"})
    )
    container.portal_sources = PortalSourceRepository(
        container.database,
        resolver=lambda _host: [PUBLIC_IP],
    )
    discovery = CapturingDiscoveryProvider()
    app = create_app(
        container,
        data_directory=tmp_path / "data",
        discovery_provider=discovery,
    )

    with TestClient(app) as client:
        register(client)
        account_page = client.get("/account")
        assert account_page.status_code == 200
        assert "Choose which external services may run" in account_page.text
        assert "Every locally available provider starts enabled" in account_page.text

        enabled = client.post(
            "/account/providers",
            data={"enabled_provider": ["arbeitnow", "brave"]},
            follow_redirects=False,
        )
        assert enabled.status_code == 303
        (account,) = container.accounts.list_accounts()
        assert container.provider_permissions.enabled_keys(account.id) == DEFAULT_PROVIDER_KEYS

        portal = client.post(
            "/add/portals",
            data={
                "url": "https://careers.example.com/openings",
                "label": "Example careers",
            },
            follow_redirects=False,
        )
        assert portal.status_code == 303
        explored = client.post(
            "/explore/search",
            data={
                "q": "quality engineer",
                "location": "Frankfurt",
                "include_custom_portals": "true",
            },
            follow_redirects=False,
        )
        assert explored.status_code == 303

    assert discovery.queries
    assert discovery.queries[-1].preferred_domains == []
    assert discovery.queries[-1].preferred_portals == ["https://careers.example.com/openings"]


def test_provider_opt_out_is_explicit_and_unavailable_rows_are_preserved(tmp_path: Path) -> None:
    container = ApplicationContainer(settings(tmp_path))
    account, _ = create_account(container, "owner@example.com", "Owner")

    container.provider_permissions.replace(
        account.id,
        set(),
        available_keys={"openai"},
    )
    assert "openai" not in container.provider_permissions.enabled_keys(account.id)
    assert "arbeitnow" in container.provider_permissions.enabled_keys(account.id)

    container.provider_permissions.replace(
        account.id,
        {"arbeitnow"},
        available_keys={"arbeitnow"},
    )
    enabled = container.provider_permissions.enabled_keys(account.id)
    assert "arbeitnow" in enabled
    assert "openai" not in enabled


def test_siemens_portal_scope_keeps_locale_branch_but_not_search_landing() -> None:
    saved = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs"
    scope = portal_search_scope(saved)
    query = DiscoveryQuery(
        text="automation engineer",
        preferred_portals=[scope],
    )

    assert scope == "https://jobs.siemens.com/en_US/externaljobs"
    assert "site:jobs.siemens.com/en_US/externaljobs" in _portal_search_texts(query)[0]
    assert web_discovery_matches_portal(
        "https://jobs.siemens.com/en_US/externaljobs/JobDetail/Engineer/1234",
        query,
    )
    assert not web_discovery_matches_portal(
        "https://jobs.siemens.com/cs_CZ/externaljobs/JobDetail/Engineer/1234",
        query,
    )
    assert _portal_search_texts(query.model_copy(update={"include_custom_portals": False})) == []


@pytest.mark.parametrize(
    ("url", "title"),
    (
        ("https://jobs.siemens.com/en_US/externaljobs/Error", "Engineer"),
        ("https://jobs.siemens.com/en_US/externaljobs/SearchJobs", "Search jobs"),
        ("https://jobs.siemens.com/en_US/externaljobs/JobDetail/1234", "Error | Siemens"),
    ),
)
def test_web_providers_reject_deterministic_error_and_landing_results(
    url: str,
    title: str,
) -> None:
    row = {"url": url, "title": title}
    assert not BraveWebDiscoveryProvider._usable(object(), row)
    assert not ExaFallbackDiscoveryProvider._usable(row)


def test_valid_siemens_deep_job_survives_web_policy_and_old_snapshots() -> None:
    job = DiscoveredJob(
        provider="brave-web",
        external_id="siemens-1234",
        title="Automation Engineer",
        company="Siemens",
        location="Erlangen, Germany",
        source_url=(
            "https://jobs.siemens.com/en_US/externaljobs/JobDetail/Automation-Engineer/1234"
        ),
    )
    assert BraveWebDiscoveryProvider._usable(
        object(),
        {"url": str(job.source_url), "title": job.title},
    )

    bad = DiscoveredJob.model_validate(
        {
            **job.model_dump(mode="json"),
            "external_id": "bad",
            "title": "Error | Siemens",
            "source_url": "https://jobs.siemens.com/cs_CZ/externaljobs/Error",
        }
    )
    restored = ExploreSearchRepository._results(
        json.dumps([bad.model_dump(mode="json"), job.model_dump(mode="json")])
    )
    assert restored == [job]


def test_availability_filter_rejects_redirect_to_search_landing() -> None:
    class RedirectingFetcher:
        def fetch(self, url: str) -> FetchedDocument:
            return FetchedDocument(
                requested_url=url,
                final_url="https://jobs.siemens.com/en_US/externaljobs/SearchJobs",
                status_code=200,
                content_type="text/html",
                text="Search jobs",
                fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

    policy = DiscoveryAvailabilityFilter(fetcher=RedirectingFetcher())
    assert policy._is_definitively_closed(
        "https://jobs.siemens.com/en_US/externaljobs/JobDetail/Engineer/1234"
    )
