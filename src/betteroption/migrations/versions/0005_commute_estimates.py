"""Add private, profile-scoped commute estimate caching."""

from alembic import op
import sqlalchemy as sa


revision = "0005_commute_estimates"
down_revision = "0004_match_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_runs",
        sa.Column(
            "algorithm_version",
            sa.String(length=32),
            nullable=False,
            server_default="matching-v0.6.5",
        ),
    )
    op.create_table(
        "commute_estimates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=500), nullable=False),
        sa.Column("destination", sa.String(length=500), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_record_id"],
            ["job_records.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "job_record_id",
            "query_fingerprint",
            name="uq_commute_estimate_query",
        ),
    )
    op.create_index(
        op.f("ix_commute_estimates_workspace_id"),
        "commute_estimates",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_commute_estimates_job_record_id"),
        "commute_estimates",
        ["job_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_commute_estimates_job_record_id"),
        table_name="commute_estimates",
    )
    op.drop_index(
        op.f("ix_commute_estimates_workspace_id"),
        table_name="commute_estimates",
    )
    op.drop_table("commute_estimates")
    op.drop_column("match_runs", "algorithm_version")
