from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from betteroption.container import ApplicationContainer
from betteroption.cost_calibration import ProviderBillingPeriod
from betteroption.operations import ProviderOperation, ProviderOperationOutcome
from betteroption.settings import Settings
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"
NOW = datetime.now(timezone.utc)


def _container(
    tmp_path: Path,
    *,
    auth_mode: str = "accounts",
    operator_emails: str = "",
) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v070b-readiness.db').as_posix()}",
            auth_mode=auth_mode,
            registration_mode="open",
            operator_emails=operator_emails,
            background_worker_enabled=False,
            employer_homepage_research=False,
            legal_terms_version="terms-test-v1",
            legal_privacy_version="privacy-test-v1",
        )
    )


def test_legal_pages_are_public_and_registration_records_current_versions(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        for path in ("/privacy", "/terms", "/imprint"):
            response = client.get(path)
            assert response.status_code == 200

        rejected = client.post(
            "/register",
            data={
                "email": "owner@example.com",
                "display_name": "Owner",
                "password": PASSWORD,
            },
        )
        created = client.post(
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

    assert rejected.status_code == 400
    assert "Confirm you are at least 18" in rejected.text
    assert created.status_code == 303
    account = container.accounts.by_email("owner@example.com")
    assert account is not None
    status = container.legal.status(account.id)
    assert status.current
    assert status.terms_version == "terms-test-v1"
    assert status.privacy_version == "privacy-test-v1"

    container.legal.record_current(account.id)
    assert len(container.legal.list_for_account(account.id)) == 2


def test_account_export_contains_document_versions_without_operational_secrets(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode="open",
    )
    container.legal.record_current(account.id)

    exported = json.loads(container.accounts.export_json(account.id))

    assert {
        (item["document_kind"], item["document_version"]) for item in exported["legal_acceptances"]
    } == {
        ("terms", "terms-test-v1"),
        ("privacy_notice", "privacy-test-v1"),
    }
    serialized = json.dumps(exported)
    assert PASSWORD not in serialized
    assert "password_hash" not in serialized
    assert "session" not in serialized


def test_billing_calibration_correlates_provider_metadata_only(tmp_path: Path) -> None:
    container = _container(tmp_path, auth_mode="local")
    container.operations.record(
        ProviderOperation(
            provider="brave-web",
            purpose="discovery",
            outcome=ProviderOperationOutcome.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=35),
            latency_ms=35,
            unit_count=2,
            unit_name="request",
            result_count=12,
        )
    )
    period = container.billing_periods.add(
        ProviderBillingPeriod(
            provider="brave-web",
            period_start=NOW - timedelta(hours=1),
            period_end=NOW + timedelta(hours=1),
            billed_amount=1.20,
            currency="EUR",
            source_label="Provider dashboard",
        )
    )

    report = container.billing_periods.list_reports()[0]

    assert report.period.id == period.id
    assert report.usage.total_operations == 1
    assert report.usage.unit_count == 2
    assert report.usage.result_count == 12
    assert report.effective_cost_per_operation == 1.20
    assert report.effective_cost_per_unit == 0.60


def test_operations_histories_are_bounded_keyboard_scroll_regions() -> None:
    template = Path("src/betteroption/web/templates/operations.html").read_text(encoding="utf-8")
    css = Path("src/betteroption/web/static/app.css").read_text(encoding="utf-8")
    app = Path("src/betteroption/web/app.py").read_text(encoding="utf-8")

    assert template.count("operations-history-scroll") >= 3
    assert 'aria-label="Background activity history, latest 100 workflows"' in template
    assert 'aria-label="Match run consumption history, latest 100 runs"' in template
    assert 'tabindex="0"' in template
    assert "Latest 100 · scroll for history" in template
    assert ".operations-history-scroll { max-height:28rem; overflow:auto;" in css
    assert ".operations-history-scroll .operations-table thead th { position:sticky;" in css
    assert "container.background_tasks.list_recent(limit=100)" in app
    assert "container.results.recent_run_metrics(limit=100)" in app


def test_alpha_readiness_schema_is_present(tmp_path: Path) -> None:
    container = _container(tmp_path)
    tables = set(inspect(container.database.engine).get_table_names())

    assert "legal_acceptances" in tables
    assert "provider_billing_periods" in tables
