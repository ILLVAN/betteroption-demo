"""Add account provider permissions and persona employer portals.

Revision ID: 0020_g_user_controls
Revises: 0019_application_drafts
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_g_user_controls"
down_revision = "0019_application_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_operations") as batch:
        batch.add_column(sa.Column("account_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_provider_operations_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_provider_operations_account_id", ["account_id"])
    op.create_table(
        "account_provider_preferences",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider_key", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "persona_portal_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "persona_id",
            sa.String(36),
            sa.ForeignKey("account_personas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("portal_url", sa.String(2_000), nullable=False),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "persona_id",
            "portal_url",
            name="uq_persona_portal_sources_persona_url",
        ),
    )
    op.create_index(
        "ix_persona_portal_sources_persona_id",
        "persona_portal_sources",
        ["persona_id"],
    )
    op.create_index(
        "ix_persona_portal_sources_hostname",
        "persona_portal_sources",
        ["hostname"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persona_portal_sources_hostname",
        table_name="persona_portal_sources",
    )
    op.drop_index(
        "ix_persona_portal_sources_persona_id",
        table_name="persona_portal_sources",
    )
    op.drop_table("persona_portal_sources")
    op.drop_table("account_provider_preferences")
    with op.batch_alter_table("provider_operations") as batch:
        batch.drop_index("ix_provider_operations_account_id")
        batch.drop_constraint(
            "fk_provider_operations_account_id_accounts",
            type_="foreignkey",
        )
        batch.drop_column("account_id")
