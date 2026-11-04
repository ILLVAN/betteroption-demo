"""Persist resumable Explore requests and result snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0012_background_explore"
down_revision = "0013_background_job_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "explore_searches",
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_json", sa.Text(), nullable=False),
        sa.Column("query_text", sa.String(400), nullable=False),
        sa.Column("location", sa.String(200), nullable=False, server_default=""),
        sa.Column("work_arrangement", sa.String(160), nullable=False),
        sa.Column("compass_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hide_remote_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("results_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("regional_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_explore_searches_workspace_id",
        "explore_searches",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_explore_searches_workspace_id", table_name="explore_searches")
    op.drop_table("explore_searches")
