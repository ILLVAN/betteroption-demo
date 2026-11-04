"""Correlate privacy-safe provider work with match-run KPIs."""

from alembic import op
import sqlalchemy as sa


revision = "0010_match_run_operations"
down_revision = "0009_provider_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_operations", sa.Column("workflow_id", sa.String(36), nullable=True))
    op.add_column("provider_operations", sa.Column("workflow_type", sa.String(40), nullable=True))
    op.create_index("ix_provider_operations_workflow_id", "provider_operations", ["workflow_id"])
    op.create_index(
        "ix_provider_operations_workflow_type", "provider_operations", ["workflow_type"]
    )

    columns = (
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("jobs_evaluated", sa.Integer(), nullable=True),
        sa.Column("exact_route_jobs", sa.Integer(), nullable=True),
        sa.Column("included_slots", sa.Integer(), nullable=True),
        sa.Column("top_count", sa.Integer(), nullable=True),
        sa.Column("stretch_count", sa.Integer(), nullable=True),
        sa.Column("blocked_count", sa.Integer(), nullable=True),
        sa.Column("provider_operations", sa.Integer(), nullable=True),
        sa.Column("provider_failures", sa.Integer(), nullable=True),
        sa.Column("provider_results", sa.Integer(), nullable=True),
        sa.Column("provider_costed_operations", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
    )
    for column in columns:
        op.add_column("match_runs", column)


def downgrade() -> None:
    for name in (
        "estimated_cost_usd",
        "provider_costed_operations",
        "provider_results",
        "provider_failures",
        "provider_operations",
        "blocked_count",
        "stretch_count",
        "top_count",
        "included_slots",
        "exact_route_jobs",
        "jobs_evaluated",
        "latency_ms",
        "finished_at",
    ):
        op.drop_column("match_runs", name)
    op.drop_index("ix_provider_operations_workflow_type", table_name="provider_operations")
    op.drop_index("ix_provider_operations_workflow_id", table_name="provider_operations")
    op.drop_column("provider_operations", "workflow_type")
    op.drop_column("provider_operations", "workflow_id")
