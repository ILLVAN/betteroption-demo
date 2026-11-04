"""Database engine, session factory, and schema-migration bootstrap."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


DEFAULT_DATABASE_URL = "sqlite:///local-data/betteroption.db"
V060_BASELINE_REVISION = "0001_v060_baseline"
V060_TABLES = {
    "job_records",
    "job_observations",
    "job_revisions",
    "job_url_aliases",
}


class Base(DeclarativeBase):
    pass


def resolve_database_url(database_url: str | None = None) -> str:
    return database_url or os.getenv("BETTEROPTION_DATABASE_URL", DEFAULT_DATABASE_URL)


def _ensure_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    if url.database and url.database != ":memory:":
        Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _engine_options(database_url: str) -> dict:
    url = make_url(database_url)
    options: dict = {"future": True}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if url.database in {None, "", ":memory:"}:
            options["poolclass"] = StaticPool
    return options


def _migration_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parent / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_schema_migrations(database_url: str) -> None:
    """Upgrade a new database or adopt and upgrade an existing v0.6.0 corpus."""

    _ensure_sqlite_directory(database_url)
    probe = create_engine(database_url, **_engine_options(database_url))
    try:
        table_names = set(inspect(probe).get_table_names())
    finally:
        probe.dispose()

    config = _migration_config(database_url)
    if "job_records" in table_names and "alembic_version" not in table_names:
        if not V060_TABLES.issubset(table_names):
            raise RuntimeError(
                "The database resembles a pre-migration corpus but is missing v0.6.0 tables. "
                "Restore a complete database backup before upgrading."
            )
        command.stamp(config, V060_BASELINE_REVISION)
    command.upgrade(config, "head")


class Database:
    """Shared engine and sessions for repositories and application adapters."""

    def __init__(self, database_url: str | None = None) -> None:
        self.url = resolve_database_url(database_url)
        _ensure_sqlite_directory(self.url)
        parsed = make_url(self.url)
        if parsed.get_backend_name() == "sqlite" and parsed.database in {
            None,
            "",
            ":memory:",
        }:
            self.engine = create_engine(self.url, **_engine_options(self.url))
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
            _register_all_tables()
            Base.metadata.create_all(self.engine)
        else:
            run_schema_migrations(self.url)
            self.engine = create_engine(self.url, **_engine_options(self.url))
            if parsed.get_backend_name() == "sqlite":
                event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Make declared cascade behavior effective in local SQLite databases."""

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _register_all_tables() -> None:
    # Imports register declarative rows on Base for in-memory test databases.
    from . import (  # noqa: F401
        accounts,
        application_guidance,
        applications,
        background,
        cost_calibration,
        cv,
        employer_reputation,
        explore_repository,
        feedback,
        job_overrides,
        job_posters,
        job_ratings,
        job_repository,
        legal,
        mobility,
        operations,
        personas,
        portal_sources,
        profile_repository,
        provider_permissions,
        result_repository,
        telemetry,
    )
