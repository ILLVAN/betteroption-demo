"""Add privacy-conscious model invocation telemetry."""

from alembic import op
import sqlalchemy as sa


revision = "0002_model_invocations"
down_revision = "0001_v060_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_invocations_outcome"),
        "model_invocations",
        ["outcome"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_invocations_provider"),
        "model_invocations",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_invocations_task"),
        "model_invocations",
        ["task"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_invocations_task"), table_name="model_invocations")
    op.drop_index(op.f("ix_model_invocations_provider"), table_name="model_invocations")
    op.drop_index(op.f("ix_model_invocations_outcome"), table_name="model_invocations")
    op.drop_table("model_invocations")
