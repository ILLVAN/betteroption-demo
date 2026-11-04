"""Add persona-owned application contact and submission guidance corrections.

Revision ID: 0026_application_guidance
Revises: 0025_employer_reputation_scoring
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_application_guidance"
down_revision = "0025_employer_reputation_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_application_guidance_overrides",
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
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("edited_fields_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "job_record_id",
            name="uq_job_application_guidance_workspace_job",
        ),
    )
    op.create_index(
        "ix_job_application_guidance_overrides_workspace_id",
        "job_application_guidance_overrides",
        ["workspace_id"],
    )
    op.create_index(
        "ix_job_application_guidance_overrides_job_record_id",
        "job_application_guidance_overrides",
        ["job_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_application_guidance_overrides_job_record_id",
        table_name="job_application_guidance_overrides",
    )
    op.drop_index(
        "ix_job_application_guidance_overrides_workspace_id",
        table_name="job_application_guidance_overrides",
    )
    op.drop_table("job_application_guidance_overrides")
