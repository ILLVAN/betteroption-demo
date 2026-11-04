from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from betteroption.container import ApplicationContainer
from betteroption.database import Database
from betteroption.discovery import DiscoveryError, DiscoveryQuery
from betteroption.discovery import rank_discovered_jobs
from betteroption.geography import (
    OfflineNutsRegionIndex,
    OfflineNutsRepresentativePointIndex,
    OfflinePlaceIndex,
    ResolvedNutsRepresentativePoint,
)
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingDiscoveryProvider,
)
from betteroption.provider_permissions import permission_key_for_provider
from betteroption.providers.apify_eures import ApifyEuresDiscoveryProvider
from betteroption.settings import Settings


def _eures_row() -> dict[str, object]:
    return {
        "source": "EURES",
        "id": "eures-de-midwife-123",
        "title": "Midwife / Hebamme (m/w/d)",
        "employer_name": "München Klinik",
        "country_codes": ["DE"],
        "location_codes": ["DE212"],
        "locations": [{"city": "München", "region": "Bayern", "country": "Germany"}],
        "working_time_codes": ["FULL_TIME"],
        "contract_type_code": "PERMANENT",
        "available_languages": ["de", "en"],
        "created_at": "2026-08-02T08:30:00Z",
        "description": "<p>Support families during childbirth.</p>",
        "application_url": "https://jobs.muenchen-klinik.example/apply/123",
        "contact_email": "recruiting@muenchen-klinik.example",
        "contact_phone": "+49 (89) 123 456",
        "url": "https://eures.europa.eu/job/eures-de-midwife-123",
    }


def test_eures_uses_one_bounded_actor_run_and_maps_only_public_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[_eures_row()])

    provider = ApifyEuresDiscoveryProvider(
        "private-apify-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_results=30,
    )
    jobs = provider.search(
        DiscoveryQuery(
            text="midwife · midwifery · supporting childbirth",
            desired_terms=["midwife", "midwifery"],
            location="München",
            limit=150,
        )
    )

    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert request.url == httpx.URL(ApifyEuresDiscoveryProvider.endpoint)
    assert request.headers["Authorization"] == "Bearer private-apify-token"
    assert request.headers["User-Agent"].startswith("BetterOption/0.7.2k")
    assert "private-apify-token" not in str(request.url)
    assert "private-apify-token" not in request.content.decode()
    assert body == {
        "keywords": ["midwife", "midwifery", "supporting childbirth"],
        "countryCodes": ["DE"],
        "workingTimeCodes": [],
        "contractTypeCodes": [],
        "maxResults": 30,
    }
    assert provider.last_request_count == 1

    assert len(jobs) == 1
    job = jobs[0]
    assert job.provider == "apify-eures"
    assert job.external_id == "eures-de-midwife-123"
    assert job.title == "Midwife / Hebamme (m/w/d)"
    assert job.company == "München Klinik"
    assert job.location == "München, Bayern, Germany"
    assert str(job.source_url) == "https://eures.europa.eu/job/eures-de-midwife-123"
    assert "Support families during childbirth." in job.summary
    assert "https://jobs.muenchen-klinik.example/apply/123" in job.summary
    assert "recruiting@muenchen-klinik.example" in job.summary
    assert "+49 (89) 123 456" in job.summary
    assert "private-apify-token" not in job.model_dump_json()
    assert job.published_at == datetime(2026, 8, 2, 8, 30, tzinfo=timezone.utc)


def test_eures_skips_malformed_rows_and_never_echoes_provider_errors() -> None:
    responses = iter(
        [
            httpx.Response(200, json=[{"id": "missing-source", "title": "Broken"}, _eures_row()]),
            httpx.Response(401, text="rejected private-apify-token"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    provider = ApifyEuresDiscoveryProvider(
        "private-apify-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    jobs = provider.search(DiscoveryQuery(text="midwife", location="München"))
    assert [job.external_id for job in jobs] == ["eures-de-midwife-123"]

    with pytest.raises(DiscoveryError) as raised:
        provider.search(DiscoveryQuery(text="midwife", location="München"))
    assert str(raised.value) == "EURES discovery through Apify was unavailable."
    assert "private-apify-token" not in str(raised.value)


def test_eures_nuts_codes_render_as_regions_and_support_distance_ranking() -> None:
    row = _eures_row()
    row.pop("locations")
    row["location_codes"] = ["DE7", "DE72", "DE724"]

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[row])

    provider = ApifyEuresDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    query = DiscoveryQuery(
        text="midwife",
        desired_terms=["midwife"],
        location="Frankfurt am Main",
    )
    jobs = provider.search(query)
    ranked = rank_discovered_jobs(query, jobs)

    assert jobs[0].location == "Marburg-Biedenkopf, Germany"
    assert ranked[0].distance_km is not None
    assert 60 < ranked[0].distance_km < 110
    assert ranked[0].distance_relevance is not None


def test_offline_nuts_index_resolves_current_european_codes_and_names() -> None:
    nuts = OfflineNutsRegionIndex()
    place_index = OfflinePlaceIndex()

    marburg = nuts.resolve_code("de724")
    assert marburg is not None
    assert marburg.code == "DE724"
    assert marburg.label == "Marburg-Biedenkopf"
    assert marburg.country_code == "DE"

    resolved_marburg = place_index.resolve_for_explore("DE724")
    assert resolved_marburg is not None
    assert resolved_marburg.label.startswith("Marburg")
    assert resolved_marburg.country_code == "DE"
    assert isinstance(resolved_marburg, ResolvedNutsRepresentativePoint)
    assert resolved_marburg.precision == "regional_representative"
    named_region = nuts.resolve_name("Oberbayern, Germany", "DE")
    assert named_region is not None
    assert named_region.code == "DE21"
    assert place_index.resolve_for_explore("Marburg-Biedenkopf, Germany") is not None
    prague = nuts.resolve_code("CZ010")
    assert prague is not None
    assert prague.label == "Hlavní město Praha"
    assert nuts.resolve_code("not-a-region") is None


@pytest.mark.parametrize(
    ("nuts_code", "region_label", "representative_place", "origin"),
    [
        ("DE724", "Marburg-Biedenkopf", "Marburg an der Lahn", "Frankfurt am Main"),
        ("DE24C", "Lichtenfels", "Lichtenfels", "Frankfurt am Main"),
        ("DE93B", "Verden", "Verden", "Frankfurt am Main"),
        ("DE600", "Hamburg", "Hamburg", "Frankfurt am Main"),
        (
            "DEB32",
            "Kaiserslautern, Kreisfreie Stadt",
            "Kaiserslautern",
            "Frankfurt am Main",
        ),
        ("SE224", "Skåne län", "Malmö", "Stockholm"),
        ("SE232", "Västra Götalands län", "Gothenburg", "Stockholm"),
    ],
)
def test_reviewed_nuts_regions_have_explicit_explore_only_representative_points(
    nuts_code: str,
    region_label: str,
    representative_place: str,
    origin: str,
) -> None:
    points = OfflineNutsRepresentativePointIndex()
    place_index = OfflinePlaceIndex()

    point = points.resolve_code(nuts_code)
    assert point is not None
    assert point.region_label == region_label
    assert point.label == representative_place
    assert point.precision == "regional_representative"
    assert point.geoname_id > 0

    # Exact place/routing resolution cannot consume a regional code. Explore
    # must opt in to the approximate crosswalk explicitly.
    assert place_index.resolve(nuts_code) is None
    assert place_index.resolve_for_explore(nuts_code) == point

    row = _eures_row()
    row.pop("locations")
    row["country_codes"] = [nuts_code[:2]]
    row["location_codes"] = [nuts_code]

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[row])

    provider = ApifyEuresDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    query = DiscoveryQuery(
        text="midwife",
        desired_terms=["midwife"],
        location=origin,
    )
    jobs = provider.search(query)
    ranked = rank_discovered_jobs(query, jobs)

    assert region_label in jobs[0].location
    assert ranked[0].distance_km is not None
    assert ranked[0].distance_km >= 0
    assert ranked[0].distance_relevance is not None
    assert ranked[0].search_score is not None


def test_bundled_nuts_table_is_the_geometry_free_eu_2024_classification() -> None:
    table = Path(__file__).resolve().parents[1] / "src/betteroption/data/nuts-2024.csv"
    with table.open(encoding="utf-8", newline="") as table_file:
        reader = csv.DictReader(table_file)
        rows = list(reader)

    assert reader.fieldnames == ["nuts_id", "country_code", "name"]
    assert len(rows) == 1_528
    assert len({row["nuts_id"] for row in rows}) == len(rows)
    assert next(row for row in rows if row["nuts_id"] == "DE724") == {
        "nuts_id": "DE724",
        "country_code": "DE",
        "name": "Marburg-Biedenkopf",
    }

    crosswalk = table.with_name("nuts-representative-points-2024.csv")
    with crosswalk.open(encoding="utf-8", newline="") as crosswalk_file:
        point_rows = list(csv.DictReader(crosswalk_file))
    assert {row["nuts_id"] for row in point_rows} == {
        "DE24C",
        "DE600",
        "DE724",
        "DE93B",
        "DEB32",
        "SE224",
        "SE232",
    }
    assert {row["precision"] for row in point_rows} == {"regional_representative"}


def test_eures_actor_run_records_actual_request_results_and_configured_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[_eures_row()])

    database = Database("sqlite:///:memory:")
    ledger = ProviderOperationLedger(database)
    raw = ApifyEuresDiscoveryProvider(
        "token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider = RecordingDiscoveryProvider(
        raw,
        ledger,
        ProviderBudgetPolicy(ledger),
        estimated_cost_usd=0.04,
        cost_is_per_request=True,
    )

    provider.search(DiscoveryQuery(text="midwife", location="München"))

    with database.session_factory() as session:
        row = session.scalar(select(ProviderOperationRow))
    assert row is not None
    assert row.provider == "apify-eures"
    assert row.unit_count == 1
    assert row.result_count == 1
    assert row.estimated_cost_usd == pytest.approx(0.04)


def test_eures_settings_permission_availability_and_container_wiring(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'eures.db').as_posix()}",
        APIFY_API_TOKEN="secret",
        BETTEROPTION_APIFY_EURES_MAX_RESULTS=25,
        BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD=0,
        _env_file=None,
    )
    assert settings.apify_api_token_value == "secret"
    assert settings.apify_eures_max_results == 25
    assert settings.apify_eures_estimated_cost_per_run_usd == 0
    assert permission_key_for_provider("apify-eures") == "eures"

    container = ApplicationContainer(settings)
    mesh = container.job_discovery_provider()
    assert "apify-eures" in [provider.name for provider in mesh.primary_providers]
    assert container.provider_availability()["eures"] == (True, "Configured")


def test_hosted_eures_remains_closed_until_processor_review(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'hosted-eures.db').as_posix()}",
        app_environment="staging",
        APIFY_API_TOKEN="secret",
        processor_review_completed=False,
        _env_file=None,
    )
    container = ApplicationContainer(settings)

    assert container.provider_availability()["eures"][0] is False
    assert "apify-eures" not in [
        provider.name for provider in container.job_discovery_provider().primary_providers
    ]


def test_eures_examples_keep_secrets_blank_and_numeric_cost_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (".env.example", "deploy/.env.staging.example"):
        example = (root / relative).read_text(encoding="utf-8")
        assert "APIFY_API_TOKEN=" in example
        assert "BETTEROPTION_APIFY_EURES_MAX_RESULTS=30" in example
        assert "BETTEROPTION_APIFY_EURES_ESTIMATED_COST_PER_RUN_USD=0" in example
