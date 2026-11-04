"""Add persona-scoped editable application drafts.

Revision ID: 0019_application_drafts
Revises: 0018_account_owned_personas
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_application_drafts"
down_revision = "0018_account_owned_personas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_record_id",
            sa.String(36),
            sa.ForeignKey("job_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generator_model", sa.String(200), nullable=True),
        sa.Column("generated_action", sa.String(16), nullable=True),
        sa.Column("manually_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "job_record_id",
            name="uq_application_drafts_workspace_job",
        ),
    )
    op.create_index(
        "ix_application_drafts_workspace_id",
        "application_drafts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_application_drafts_job_record_id",
        "application_drafts",
        ["job_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_drafts_job_record_id", table_name="application_drafts")
    op.drop_index("ix_application_drafts_workspace_id", table_name="application_drafts")
    op.drop_table("application_drafts")
