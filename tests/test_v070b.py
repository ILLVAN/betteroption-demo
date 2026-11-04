from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from betteroption.accounts import (
    USERNAME_MAX_LENGTH,
    AccountError,
    RegistrationMode,
)
from betteroption.container import ApplicationContainer
from betteroption.settings import Settings
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "another correct horse battery staple"


def _container(
    tmp_path: Path,
    *,
    operator_emails: str = "",
) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v070b.db').as_posix()}",
            auth_mode="accounts",
            registration_mode="open",
            operator_emails=operator_emails,
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )


def _account(container: ApplicationContainer, email: str, username: str):
    return container.accounts.create(
        email,
        username,
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )


def _client(app, container: ApplicationContainer, account) -> TestClient:
    client = TestClient(app)
    session = container.accounts.create_session(account, ttl=timedelta(days=1))
    client.cookies.set("betteroption_session", session.token)
    return client


def test_usernames_are_bounded_and_unique_case_insensitively(tmp_path: Path) -> None:
    container = _container(tmp_path)
    first = _account(container, "first@example.com", "Calm Builder")

    assert container.accounts.by_username("  calm builder  ").id == first.id
    with pytest.raises(AccountError, match="already in use"):
        _account(container, "second@example.com", "CALM BUILDER")
    with pytest.raises(AccountError, match=str(USERNAME_MAX_LENGTH)):
        _account(container, "third@example.com", "x" * (USERNAME_MAX_LENGTH + 1))


def test_username_change_requires_password_and_preserves_unique_email(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    first = _account(container, "first@example.com", "First")
    _account(container, "second@example.com", "Second")

    with pytest.raises(AccountError, match="current password"):
        container.accounts.update_username(
            first.id,
            "Changed",
            current_password="incorrect password",
        )
    with pytest.raises(AccountError, match="already in use"):
        container.accounts.update_username(
            first.id,
            "second",
            current_password=PASSWORD,
        )

    changed = container.accounts.update_username(
        first.id,
        "Changed",
        current_password=PASSWORD,
    )
    assert changed.display_name == "Changed"
    assert changed.email == "first@example.com"


def test_password_change_revokes_every_existing_session(tmp_path: Path) -> None:
    container = _container(tmp_path)
    account = _account(container, "secure@example.com", "Secure")
    first = container.accounts.create_session(account, ttl=timedelta(days=1))
    second = container.accounts.create_session(account, ttl=timedelta(days=1))

    container.accounts.change_password(
        account.id,
        current_password=PASSWORD,
        new_password=NEW_PASSWORD,
    )

    assert container.accounts.resolve_session(first.token) is None
    assert container.accounts.resolve_session(second.token) is None
    assert container.accounts.authenticate(account.email, PASSWORD) is None
    assert container.accounts.authenticate(account.email, NEW_PASSWORD) is not None


def test_account_page_has_quiet_deletion_and_secure_change_forms(tmp_path: Path) -> None:
    container = _container(tmp_path)
    account = _account(container, "owner@example.com", "Owner")
    container.workspaces.create(account_id=account.id)
    app = create_app(container, data_directory=tmp_path / "data")

    with _client(app, container, account) as client:
        page = client.get("/account")
        renamed = client.post(
            "/account/username",
            data={"username": "New Owner", "current_password": PASSWORD},
            follow_redirects=False,
        )

    assert page.status_code == 200
    assert 'action="http://testserver/account/username"' in page.text
    assert 'action="http://testserver/account/password"' in page.text
    assert '<details class="panel danger-zone account-delete-zone">' in page.text
    assert renamed.status_code == 303
    assert container.accounts.get(account.id).display_name == "New Owner"


def test_operations_is_unlinked_and_requires_the_server_allowlist(tmp_path: Path) -> None:
    container = _container(tmp_path, operator_emails="operator@example.com")
    operator = _account(container, "operator@example.com", "Operator")
    member = _account(container, "member@example.com", "Member")
    container.workspaces.create(account_id=operator.id)
    container.workspaces.create(account_id=member.id)
    app = create_app(container, data_directory=tmp_path / "data")

    with (
        _client(app, container, operator) as operator_client,
        _client(app, container, member) as member_client,
    ):
        home = operator_client.get("/")
        allowed = operator_client.get("/operations")
        denied = member_client.get("/operations")

    assert "/operations" not in home.text
    assert "Provider use today" not in home.text
    assert allowed.status_code == 200
    assert allowed.headers["x-robots-tag"] == "noindex, nofollow"
    assert allowed.headers["cache-control"] == "no-store"
    assert denied.status_code == 404


def test_account_security_schema_is_present(tmp_path: Path) -> None:
    container = _container(tmp_path)

    columns = {
        column["name"] for column in inspect(container.database.engine).get_columns("accounts")
    }
    indexes = inspect(container.database.engine).get_indexes("accounts")

    assert "username_normalized" in columns
    assert any(
        index["name"] == "ix_accounts_username_normalized" and index["unique"] for index in indexes
    )
