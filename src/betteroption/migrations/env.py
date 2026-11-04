"""Alembic migration environment for BetterOption."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from betteroption.database import Base
from betteroption import (  # noqa: F401
    accounts,
    application_guidance,
    applications,
    background,
    cost_calibration,
    cv,
    employer_reputation,
    explore_repository,
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


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
