"""Add database-backed profile workspaces and messages."""

from alembic import op
import sqlalchemy as sa


revision = "0003_profile_workspaces"
down_revision = "0002_model_invocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_messages_workspace_id"),
        "conversation_messages",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_conversation_messages_workspace_id"),
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_table("profile_workspaces")
