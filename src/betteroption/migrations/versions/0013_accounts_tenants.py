"""Add accounts, opaque sessions, and workspace ownership.

Revision ID: 0013_accounts_tenants
Revises: 0012_background_explore
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_accounts_tenants"
down_revision = "0012_background_explore"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    account_columns = (
        {column["name"] for column in inspector.get_columns("accounts")}
        if "accounts" in inspector.get_table_names()
        else set()
    )
    if "tenant_id" in account_columns:
        _upgrade_experimental_tenant_schema(connection)
        return

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    with op.batch_alter_table("profile_workspaces") as batch:
        batch.add_column(sa.Column("account_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_profile_workspaces_account_id",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_profile_workspaces_account_id", ["account_id"])


def _upgrade_experimental_tenant_schema(connection) -> None:
    """Convert the short-lived v0.7.0a tenant schema without losing local data."""

    if connection.dialect.name != "sqlite":
        raise RuntimeError(
            "The experimental v0.7.0a tenant schema can only be adopted "
            "automatically from its supported local SQLite database."
        )

    connection.execute(
        sa.text(
            "CREATE TEMPORARY TABLE v070c_workspace_owners "
            "(workspace_id VARCHAR(36) PRIMARY KEY, account_id VARCHAR(36))"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO v070c_workspace_owners (workspace_id, account_id) "
            "SELECT workspace.id, ("
            "  SELECT account.id FROM accounts AS account "
            "  WHERE account.tenant_id = workspace.tenant_id "
            "  ORDER BY account.is_admin DESC, account.created_at, account.id LIMIT 1"
            ") "
            "FROM profile_workspaces AS workspace"
        )
    )

    table_names = set(sa.inspect(connection).get_table_names())
    if "tenant_job_records" in table_names and "result_access_grants" in table_names:
        connection.execute(
            sa.text(
                "INSERT OR IGNORE INTO result_access_grants "
                "(workspace_id, job_record_id, granted_at) "
                "SELECT workspace.id, saved.job_record_id, saved.saved_at "
                "FROM profile_workspaces AS workspace "
                "JOIN tenant_job_records AS saved "
                "ON saved.tenant_id = workspace.tenant_id"
            )
        )

    # SQLite keeps index names when a table is renamed. Drop the two legacy
    # indexes first so the canonical account table can reuse their names.
    legacy_account_indexes = {
        index["name"] for index in sa.inspect(connection).get_indexes("accounts")
    }
    if "ix_accounts_email" in legacy_account_indexes:
        op.drop_index("ix_accounts_email", table_name="accounts")
    if "ix_accounts_tenant_id" in legacy_account_indexes:
        op.drop_index("ix_accounts_tenant_id", table_name="accounts")
    op.rename_table("accounts", "accounts_v070a")
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO accounts "
            "(id, email, display_name, password_hash, created_at, updated_at) "
            "SELECT id, email, display_name, password_hash, created_at, updated_at "
            "FROM accounts_v070a"
        )
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    if "account_sessions" in table_names:
        connection.execute(
            sa.text(
                "INSERT INTO auth_sessions "
                "(id, account_id, token_hash, created_at, last_seen_at, expires_at) "
                "SELECT id, account_id, token_hash, created_at, last_seen_at, expires_at "
                "FROM account_sessions"
            )
        )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    with op.batch_alter_table("profile_workspaces") as batch:
        batch.add_column(sa.Column("account_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_profile_workspaces_account_id",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_profile_workspaces_account_id", ["account_id"])
    connection.execute(
        sa.text(
            "UPDATE profile_workspaces "
            "SET account_id = ("
            "  SELECT owner.account_id FROM v070c_workspace_owners AS owner "
            "  WHERE owner.workspace_id = profile_workspaces.id"
            ")"
        )
    )
    with op.batch_alter_table("profile_workspaces") as batch:
        batch.drop_index("ix_profile_workspaces_tenant_id")
        batch.drop_constraint("fk_profile_workspaces_tenant_id", type_="foreignkey")
        batch.drop_column("tenant_id")

    if "account_sessions" in table_names:
        op.drop_table("account_sessions")
    if "tenant_job_records" in table_names:
        op.drop_table("tenant_job_records")
    op.drop_table("accounts_v070a")
    if "tenants" in table_names:
        op.drop_table("tenants")
    connection.execute(sa.text("DROP TABLE v070c_workspace_owners"))


def downgrade() -> None:
    with op.batch_alter_table("profile_workspaces") as batch:
        batch.drop_index("ix_profile_workspaces_account_id")
        batch.drop_constraint("fk_profile_workspaces_account_id", type_="foreignkey")
        batch.drop_column("account_id")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_account_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_accounts_email", table_name="accounts")
    op.drop_table("accounts")
