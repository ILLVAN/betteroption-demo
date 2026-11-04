"""Add invitation onboarding, recovery tokens, and authentication attempts.

Revision ID: 0017_invitation_onboarding
Revises: 0016_background_job_imports
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_invitation_onboarding"
down_revision = "0016_background_job_imports"
branch_labels = None
depends_on = None


def _index_names(connection, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(connection).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names())

    if "accounts" in table_names:
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        if "email_verified_at" not in account_columns:
            op.add_column(
                "accounts",
                sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
            )
        connection.execute(
            sa.text(
                "UPDATE accounts SET email_verified_at = created_at WHERE email_verified_at IS NULL"
            )
        )

    if "account_invitations" not in table_names:
        op.create_table(
            "account_invitations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column(
                "invited_by_account_id",
                sa.String(36),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_account_invitations_email",
            "account_invitations",
            ["email"],
        )
        op.create_index(
            "ix_account_invitations_token_hash",
            "account_invitations",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            "ix_account_invitations_invited_by_account_id",
            "account_invitations",
            ["invited_by_account_id"],
        )
        op.create_index(
            "ix_account_invitations_expires_at",
            "account_invitations",
            ["expires_at"],
        )

    if "password_reset_tokens" not in table_names:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "account_id",
                sa.String(36),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_password_reset_tokens_account_id",
            "password_reset_tokens",
            ["account_id"],
        )
        op.create_index(
            "ix_password_reset_tokens_token_hash",
            "password_reset_tokens",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            "ix_password_reset_tokens_expires_at",
            "password_reset_tokens",
            ["expires_at"],
        )

    if "auth_attempts" not in table_names:
        op.create_table(
            "auth_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column("subject_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_auth_attempts_action", "auth_attempts", ["action"])
        op.create_index(
            "ix_auth_attempts_subject_hash",
            "auth_attempts",
            ["subject_hash"],
        )
        op.create_index(
            "ix_auth_attempts_created_at",
            "auth_attempts",
            ["created_at"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    table_names = set(sa.inspect(connection).get_table_names())

    if "auth_attempts" in table_names:
        indexes = _index_names(connection, "auth_attempts")
        for name in (
            "ix_auth_attempts_created_at",
            "ix_auth_attempts_subject_hash",
            "ix_auth_attempts_action",
        ):
            if name in indexes:
                op.drop_index(name, table_name="auth_attempts")
        op.drop_table("auth_attempts")

    if "password_reset_tokens" in table_names:
        indexes = _index_names(connection, "password_reset_tokens")
        for name in (
            "ix_password_reset_tokens_expires_at",
            "ix_password_reset_tokens_token_hash",
            "ix_password_reset_tokens_account_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="password_reset_tokens")
        op.drop_table("password_reset_tokens")

    if "account_invitations" in table_names:
        indexes = _index_names(connection, "account_invitations")
        for name in (
            "ix_account_invitations_expires_at",
            "ix_account_invitations_invited_by_account_id",
            "ix_account_invitations_token_hash",
            "ix_account_invitations_email",
        ):
            if name in indexes:
                op.drop_index(name, table_name="account_invitations")
        op.drop_table("account_invitations")

    if "accounts" in table_names:
        account_columns = {
            column["name"] for column in sa.inspect(connection).get_columns("accounts")
        }
        if "email_verified_at" in account_columns:
            op.drop_column("accounts", "email_verified_at")
