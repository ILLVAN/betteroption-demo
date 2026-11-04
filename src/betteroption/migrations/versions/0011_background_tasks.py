"""Persist privacy-safe background task state and progress."""

from alembic import op
import sqlalchemy as sa


revision = "0011_background_tasks"
down_revision = "0010_match_run_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("phase", sa.String(64), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_url", sa.String(500), nullable=True),
        sa.Column("error_type", sa.String(160), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_background_tasks_workspace_id", "background_tasks", ["workspace_id"])
    op.create_index("ix_background_tasks_kind", "background_tasks", ["kind"])
    op.create_index("ix_background_tasks_status", "background_tasks", ["status"])
    op.create_index(
        "ix_background_tasks_next_attempt_at",
        "background_tasks",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_background_tasks_next_attempt_at", table_name="background_tasks")
    op.drop_index("ix_background_tasks_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_kind", table_name="background_tasks")
    op.drop_index("ix_background_tasks_workspace_id", table_name="background_tasks")
    op.drop_table("background_tasks")
