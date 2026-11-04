"""Compatibility regressions retained at the former v0.7.0a test path.

The release overlay intentionally includes this file so an obsolete local
``tests/test_v070a.py`` cannot keep importing the superseded tenant API.
"""

from datetime import timedelta
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import select

from betteroption.accounts import AccountRow, AuthSessionRow, RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.database import _migration_config
from betteroption.settings import Settings


PASSWORD = "correct horse battery staple"


def test_migration_history_has_one_head() -> None:
    script = ScriptDirectory.from_config(_migration_config("sqlite:///:memory:"))

    assert script.get_heads() == ["0033_background_task_leases"]


def test_current_account_and_session_contract_replaces_v070a_api(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v070c.db').as_posix()}",
            auth_mode="accounts",
            registration_mode="open",
            background_worker_enabled=False,
        )
    )
    account = container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )
    issued = container.accounts.create_session(account, ttl=timedelta(days=1))

    with container.database.session_factory() as database_session:
        account_row = database_session.scalar(select(AccountRow))
        session_row = database_session.scalar(select(AuthSessionRow))

    assert account_row is not None
    assert account_row.password_hash != PASSWORD
    assert container.accounts.verify_password(account.id, PASSWORD)
    assert session_row is not None
    assert session_row.token_hash != issued.token
    assert container.accounts.resolve_session(issued.token) == account
