from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
import alembic.op as alembic_op
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from betteroption.accounts import (
    AccountAccessTier,
    AccountError,
    AccountRepository,
    AccountRole,
    RegistrationMode,
)
from betteroption.container import ApplicationContainer
from betteroption.database import Database, _migration_config, run_schema_migrations
from betteroption.deployment import AccountPreflightState, inspect_preflight
from betteroption.feedback import FeedbackCategory, FeedbackSurface, ProductFeedbackRow
from betteroption.retention import RetentionPolicy, run_retention
from betteroption.settings import Settings
from betteroption.web.app import create_app


PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)


def register(
    repository: AccountRepository,
    email: str,
    name: str,
    *,
    mode: RegistrationMode = RegistrationMode.OPEN,
):
    return repository.create(email, name, PASSWORD, registration_mode=mode)


def account_container(tmp_path: Path, **overrides) -> ApplicationContainer:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'private-alpha.db').as_posix()}",
        "auth_mode": "accounts",
        "registration_mode": "open",
        "background_worker_enabled": False,
        "app_environment": "local",
    }
    values.update(overrides)
    return ApplicationContainer(Settings(**values))


def client_for(container: ApplicationContainer, account, tmp_path: Path) -> TestClient:
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    session = container.accounts.create_session(account, ttl=timedelta(hours=1))
    client.cookies.set("betteroption_session", session.token)
    return client


def hosted_settings(**overrides) -> Settings:
    values = {
        "database_url": (
            "postgresql+psycopg://worklife:0123456789abcdef0123456789abcdef@db/worklife"
        ),
        "app_environment": "staging",
        "public_base_url": "https://alpha.worklifebalance.example",
        "auth_mode": "accounts",
        "registration_mode": "invite_only",
        "auth_secure_cookie": True,
        "auth_rate_limit_secret": "0123456789abcdef" * 4,
        "operator_emails": "owner@example.com",
        "legal_review_completed": True,
        "processor_review_completed": True,
        "incident_plan_ready": True,
        "backup_restore_tested": True,
        "openai_input_cost_per_million_usd": 1,
        "openai_output_cost_per_million_usd": 2,
        "provider_daily_cost_limit_usd": 10,
        "provider_action_cost_limit_usd": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_first_owner_is_atomic_admin_and_role_stays_orthogonal_to_tester() -> None:
    repository = AccountRepository(Database("sqlite:///:memory:"))

    owner = register(repository, "owner@example.com", "Owner", mode=RegistrationMode.FIRST_USER)

    assert owner.role == AccountRole.ADMIN
    assert owner.access_tier == AccountAccessTier.STANDARD
    with pytest.raises(AccountError, match="already has an owner"):
        register(repository, "other@example.com", "Other", mode=RegistrationMode.FIRST_USER)

    member = register(repository, "member@example.com", "Member")
    tester = repository.update_access(
        member.id,
        role=AccountRole.MEMBER,
        access_tier=AccountAccessTier.TESTER,
    )
    assert tester.role == AccountRole.MEMBER
    assert tester.access_tier == AccountAccessTier.TESTER


def test_legacy_allowlist_is_only_a_zero_admin_bootstrap_bridge() -> None:
    repository = AccountRepository(Database("sqlite:///:memory:"))
    owner = register(repository, "old-owner@example.com", "Old owner")
    bridge = register(repository, "bridge@example.com", "Bridge")
    with repository.session_factory.begin() as session:
        session.execute(text("UPDATE accounts SET role = 'member'"))

    allowlist = frozenset({"bridge@example.com", "old-owner@example.com"})
    assert repository.admin_count() == 0
    assert repository.has_operator_access(bridge, legacy_operator_emails=allowlist)

    promoted = repository.update_access(
        bridge.id,
        role=AccountRole.ADMIN,
        access_tier=AccountAccessTier.TESTER,
    )
    assert repository.has_operator_access(promoted, legacy_operator_emails=allowlist)
    assert not repository.has_operator_access(owner, legacy_operator_emails=allowlist)


def test_last_admin_rules_protect_other_accounts_but_allow_empty_reset() -> None:
    repository = AccountRepository(Database("sqlite:///:memory:"))
    owner = register(repository, "owner@example.com", "Owner")
    member = register(repository, "member@example.com", "Member")

    with pytest.raises(AccountError, match="Promote another admin"):
        repository.update_access(
            owner.id,
            role=AccountRole.MEMBER,
            access_tier=AccountAccessTier.STANDARD,
        )
    with pytest.raises(AccountError, match="deleting the last admin"):
        repository.delete_account(owner.id)

    assert repository.delete_account(member.id)
    assert repository.delete_account(owner.id)
    replacement = register(
        repository,
        "replacement@example.com",
        "Replacement",
        mode=RegistrationMode.FIRST_USER,
    )
    assert replacement.is_admin


def test_operations_access_change_requires_admin_password(tmp_path: Path) -> None:
    container = account_container(tmp_path, operator_emails="tester@example.com")
    owner = register(container.accounts, "owner@example.com", "Owner")
    tester = register(container.accounts, "tester@example.com", "Tester")
    owner_client = client_for(container, owner, tmp_path)

    denied = owner_client.post(
        f"/operations/accounts/{tester.id}/access",
        data={"role": "member", "access_tier": "tester", "current_password": "wrong"},
        follow_redirects=False,
    )
    assert denied.status_code == 303
    assert container.accounts.get(tester.id).access_tier == AccountAccessTier.STANDARD

    granted = owner_client.post(
        f"/operations/accounts/{tester.id}/access",
        data={
            "role": "member",
            "access_tier": "tester",
            "current_password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert granted.status_code == 303
    assert container.accounts.get(tester.id).is_tester
    assert not container.accounts.get(tester.id).is_admin

    recovery_denied = owner_client.post(
        f"/operations/accounts/{tester.id}/recovery",
        data={"current_password": "wrong"},
        follow_redirects=False,
    )
    assert recovery_denied.status_code == 303
    assert "error=" in recovery_denied.headers["location"]
    recovery = owner_client.post(
        f"/operations/accounts/{tester.id}/recovery",
        data={"current_password": PASSWORD},
    )
    assert recovery.status_code == 200
    assert "Copy this recovery link now" in recovery.text

    tester_client = client_for(container, tester, tmp_path)
    assert tester_client.get("/operations").status_code == 404
    operations = owner_client.get("/operations")
    assert operations.status_code == 200
    assert "Your current admin password" in operations.text
    assert "Job-poster approval stays separate" in operations.text


def test_hosted_first_user_is_limited_to_normalized_operator_email(tmp_path: Path) -> None:
    container = account_container(
        tmp_path,
        app_environment="staging",
        registration_mode="first_user",
        public_base_url="https://alpha.worklifebalance.example",
        auth_secure_cookie=True,
        operator_emails=" Owner@Example.com ",
    )
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    headers = {"Origin": "https://alpha.worklifebalance.example"}
    form = {
        "display_name": "Owner",
        "password": PASSWORD,
        "next_path": "/",
        "accept_terms": "yes",
        "acknowledge_privacy": "yes",
        "confirm_adult": "yes",
    }

    denied = client.post(
        "/register",
        data={**form, "email": "outsider@example.com"},
        headers=headers,
    )
    assert denied.status_code == 400
    assert "configured private-alpha owner address" in denied.text
    assert "owner@example.com" not in denied.text.casefold()
    assert container.accounts.count() == 0

    accepted = client.post(
        "/register",
        data={**form, "email": "  OWNER@example.com "},
        headers=headers,
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert container.accounts.by_email("owner@example.com").is_admin


def test_preflight_validates_database_admin_and_bootstrap_state() -> None:
    fresh_invite = inspect_preflight(
        hosted_settings(registration_mode="invite_only"),
        openai_api_key_present=True,
        account_state=AccountPreflightState(0, 0, 0),
    )
    assert not fresh_invite.ready
    assert any("database has no owner" in item for item in fresh_invite.errors)

    occupied_first_user = inspect_preflight(
        hosted_settings(registration_mode="first_user"),
        openai_api_key_present=True,
        account_state=AccountPreflightState(1, 1, 1),
    )
    assert not occupied_first_user.ready
    assert any("requires an empty" in item for item in occupied_first_user.errors)

    fresh_first_user = inspect_preflight(
        hosted_settings(registration_mode="first_user"),
        openai_api_key_present=True,
        account_state=AccountPreflightState(0, 0, 0),
    )
    assert fresh_first_user.ready

    legacy_bridge = inspect_preflight(
        hosted_settings(registration_mode="invite_only"),
        openai_api_key_present=True,
        account_state=AccountPreflightState(2, 0, 1),
    )
    assert legacy_bridge.ready
    assert any("legacy" in item.casefold() for item in legacy_bridge.warnings)


def test_0031_upgrades_existing_accounts_without_guessing_an_admin(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    config = _migration_config(url)
    command.upgrade(config, "0030_verified_job_posters")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts "
                "(id, email, display_name, username_normalized, password_hash, "
                "email_verified_at, created_at, updated_at) VALUES "
                "(:id, :email, :display_name, :username, :password_hash, :now, :now, :now)"
            ),
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "legacy@example.com",
                "display_name": "Legacy",
                "username": "legacy",
                "password_hash": "not-used",
                "now": NOW,
            },
        )
    engine.dispose()

    run_schema_migrations(url)
    upgraded = create_engine(url)
    with upgraded.connect() as connection:
        account = connection.execute(text("SELECT role, access_tier FROM accounts")).one()
        bootstrap = connection.execute(
            text("SELECT owner_account_id FROM account_bootstrap WHERE id = 1")
        ).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert account == ("member", "standard")
    assert bootstrap == "11111111-1111-1111-1111-111111111111"
    assert revision == "0033_background_task_leases"
    assert "product_feedback" in inspect(upgraded).get_table_names()
    upgraded.dispose()


def test_0031_widens_postgresql_alembic_revision_storage_before_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = Path(__file__).resolve().parents[1] / "src/betteroption/migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    script = ScriptDirectory.from_config(config)
    output = StringIO()
    context = MigrationContext.configure(
        url="postgresql://placeholder.invalid/betteroption",
        opts={
            "as_sql": True,
            "output_buffer": output,
            "starting_rev": "0030_verified_job_posters",
            "destination_rev": "0031_private_alpha_roles_feedback",
            "fn": lambda heads, _context: script._upgrade_revs(
                "0031_private_alpha_roles_feedback",
                heads,
            ),
            "transaction_per_migration": True,
            "literal_binds": True,
            "dialect_opts": {"paramstyle": "named"},
        },
    )
    real_bind = context.bind

    class _EmptyAccountResult:
        @staticmethod
        def scalar_one_or_none() -> None:
            return None

    class _OfflineBindProxy:
        dialect = real_bind.dialect

        @staticmethod
        def execute(statement, *args, **kwargs):
            if str(statement).lstrip().upper().startswith("SELECT ID FROM ACCOUNTS"):
                return _EmptyAccountResult()
            return real_bind.execute(statement, *args, **kwargs)

    with Operations.context(context):
        monkeypatch.setattr(alembic_op, "get_bind", lambda: _OfflineBindProxy())
        context.run_migrations()

    sql = output.getvalue()
    widen = "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);"
    stamp = "UPDATE alembic_version SET version_num='0031_private_alpha_roles_feedback'"
    assert widen in sql
    assert stamp in sql
    assert sql.index(widen) < sql.index(stamp)


def test_feedback_form_admin_export_account_export_and_retention(tmp_path: Path) -> None:
    container = account_container(tmp_path)
    admin = register(container.accounts, "admin@example.com", "Admin")
    tester = register(container.accounts, "tester@example.com", "Tester")
    tester_client = client_for(container, tester, tmp_path)

    page = tester_client.get("/feedback")
    assert page.status_code == 200
    assert "Do not paste job URLs, Compass or CV content" in page.text
    assert "provider diagnostics" in page.text
    assert "not sent to AI" in page.text
    assert "BetterOption" not in page.text

    submitted = tester_client.post(
        "/feedback",
        data={
            "category": "idea",
            "surface": "matching",
            "rating": "4",
            "message": "=2+2 would make the switch clearer",
            "contact_allowed": "true",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    saved = container.feedback.list_for_account(tester.id)[0]
    assert saved.category == FeedbackCategory.IDEA
    assert saved.surface == FeedbackSurface.MATCHING
    assert saved.rating == 4

    exported_account = json.loads(container.accounts.export_json(tester.id))
    assert exported_account["product_feedback"][0]["message"].startswith("=2+2")

    admin_client = client_for(container, admin, tmp_path)
    operations = admin_client.get("/operations")
    assert "would make the switch clearer" in operations.text
    reviewed = admin_client.post(
        f"/operations/feedback/{saved.id}/review",
        data={"status": "planned", "operator_note": "Good alpha candidate."},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303
    csv_export = admin_client.get("/operations/feedback.csv")
    assert csv_export.status_code == 200
    assert "worklifebalance-private-alpha-feedback.csv" in csv_export.headers["content-disposition"]
    assert "'=2+2 would make the switch clearer" in csv_export.text

    with container.database.session_factory.begin() as session:
        row = session.get(ProductFeedbackRow, str(saved.id))
        assert row is not None
        row.updated_at = NOW - timedelta(days=181)
    report = run_retention(
        container.database,
        RetentionPolicy(product_feedback_days=180),
        now=NOW,
    )
    assert report.product_feedback == 1
    assert container.feedback.list_for_account(tester.id) == []


def test_feedback_privacy_contract_and_draft_identifier_are_current() -> None:
    privacy = Path("src/betteroption/web/templates/legal_privacy.html").read_text(encoding="utf-8")
    ropa = Path(
        "docs/archive/discontinued-product-planning/compliance/02-record-of-processing-activities.md"
    ).read_text(encoding="utf-8")
    lawful = Path(
        "docs/archive/discontinued-product-planning/compliance/03-lawful-basis-assessment.md"
    ).read_text(encoding="utf-8")
    retention = Path(
        "docs/archive/discontinued-product-planning/compliance/07-retention-deletion-schedule.md"
    ).read_text(encoding="utf-8")

    assert Settings.model_fields["legal_privacy_version"].default == ("2026-08-05-feedback-draft")
    for text_value in (privacy, ropa, retention):
        assert "180 days" in text_value or "180d" in text_value
        assert "product feedback" in text_value.casefold()
    assert "Product feedback is never sent to AI" in privacy
    assert "User-submitted private-alpha product feedback" in lawful
