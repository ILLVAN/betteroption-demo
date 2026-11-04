"""Add persona-scoped typed job evidence overrides.

Revision ID: 0021_job_evidence_overrides
Revises: 0020_g_user_controls
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_job_evidence_overrides"
down_revision = "0020_g_user_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_evidence_overrides",
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
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("target_key", sa.String(500), nullable=False),
        sa.Column("target_label", sa.String(500), nullable=False),
        sa.Column("reason_value", sa.String(16), nullable=True),
        sa.Column("skill_value", sa.String(16), nullable=True),
        sa.Column("commute_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "job_record_id",
            "kind",
            "target_key",
            name="uq_job_evidence_overrides_target",
        ),
    )
    op.create_index(
        "ix_job_evidence_overrides_workspace_id",
        "job_evidence_overrides",
        ["workspace_id"],
    )
    op.create_index(
        "ix_job_evidence_overrides_job_record_id",
        "job_evidence_overrides",
        ["job_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_evidence_overrides_job_record_id",
        table_name="job_evidence_overrides",
    )
    op.drop_index(
        "ix_job_evidence_overrides_workspace_id",
        table_name="job_evidence_overrides",
    )
    op.drop_table("job_evidence_overrides")
