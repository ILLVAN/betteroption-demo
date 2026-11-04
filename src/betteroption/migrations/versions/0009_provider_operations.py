"""Add privacy-safe provider operation accounting."""

from alembic import op
import sqlalchemy as sa


revision = "0009_provider_operations"
down_revision = "0008_cv_review_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_operations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("budget_decision", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False),
        sa.Column("unit_name", sa.String(length=40), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(length=160), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column in ("provider", "purpose", "outcome", "budget_decision"):
        op.create_index(f"ix_provider_operations_{column}", "provider_operations", [column])


def downgrade() -> None:
    op.drop_table("provider_operations")
