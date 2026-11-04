"""Add account-owned personas above historical Compass workspaces.

Revision ID: 0018_account_owned_personas
Revises: 0017_invitation_onboarding
"""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0018_account_owned_personas"
down_revision = "0017_invitation_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_personas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("name_normalized", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "account_id",
            "name_normalized",
            name="uq_account_personas_account_name",
        ),
    )
    op.create_index("ix_account_personas_account_id", "account_personas", ["account_id"])

    with op.batch_alter_table("profile_workspaces") as batch:
        batch.add_column(sa.Column("persona_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_profile_workspaces_persona_id",
            "account_personas",
            ["persona_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_profile_workspaces_persona_id", ["persona_id"])

    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("active_persona_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_auth_sessions_active_persona_id",
            "account_personas",
            ["active_persona_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_auth_sessions_active_persona_id", ["active_persona_id"])

    connection = op.get_bind()
    accounts = connection.execute(
        sa.text("SELECT id, created_at FROM accounts ORDER BY created_at ASC")
    ).mappings()
    now = datetime.now(timezone.utc)
    for account in accounts:
        persona_id = str(uuid4())
        created_at = account["created_at"] or now
        connection.execute(
            sa.text(
                "INSERT INTO account_personas "
                "(id, account_id, name, name_normalized, created_at, updated_at) "
                "VALUES (:id, :account_id, 'Main', 'main', :created_at, :updated_at)"
            ),
            {
                "id": persona_id,
                "account_id": account["id"],
                "created_at": created_at,
                "updated_at": now,
            },
        )
        connection.execute(
            sa.text(
                "UPDATE profile_workspaces SET persona_id = :persona_id "
                "WHERE account_id = :account_id"
            ),
            {"persona_id": persona_id, "account_id": account["id"]},
        )
        connection.execute(
            sa.text(
                "UPDATE auth_sessions SET active_persona_id = :persona_id "
                "WHERE account_id = :account_id"
            ),
            {"persona_id": persona_id, "account_id": account["id"]},
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_index("ix_auth_sessions_active_persona_id")
        batch.drop_constraint("fk_auth_sessions_active_persona_id", type_="foreignkey")
        batch.drop_column("active_persona_id")
    with op.batch_alter_table("profile_workspaces") as batch:
        batch.drop_index("ix_profile_workspaces_persona_id")
        batch.drop_constraint("fk_profile_workspaces_persona_id", type_="foreignkey")
        batch.drop_column("persona_id")
    op.drop_index("ix_account_personas_account_id", table_name="account_personas")
    op.drop_table("account_personas")
