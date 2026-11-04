"""Add database-backed match results, free access, and opportunity decisions."""

from alembic import op
import sqlalchemy as sa


revision = "0004_match_results"
down_revision = "0003_profile_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("profile_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_match_runs_workspace_id"),
        "match_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_runs_profile_id"),
        "match_runs",
        ["profile_id"],
        unique=False,
    )
    op.create_table(
        "match_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_run_id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("job_snapshot_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_record_id"],
            ["job_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_run_id"],
            ["match_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_run_id", "job_record_id"),
    )
    op.create_index(
        op.f("ix_match_results_match_run_id"),
        "match_results",
        ["match_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_results_job_record_id"),
        "match_results",
        ["job_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_results_disposition"),
        "match_results",
        ["disposition"],
        unique=False,
    )
    op.create_table(
        "result_access_grants",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_record_id"],
            ["job_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "job_record_id"),
    )
    op.create_table(
        "job_interactions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("feedback", sa.String(length=32), nullable=False),
        sa.Column("application_state", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_record_id"],
            ["job_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "job_record_id"),
    )
    op.create_table(
        "job_interaction_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_record_id"],
            ["job_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["profile_workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_job_interaction_events_workspace_id"),
        "job_interaction_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_interaction_events_job_record_id"),
        "job_interaction_events",
        ["job_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_job_interaction_events_job_record_id"),
        table_name="job_interaction_events",
    )
    op.drop_index(
        op.f("ix_job_interaction_events_workspace_id"),
        table_name="job_interaction_events",
    )
    op.drop_table("job_interaction_events")
    op.drop_table("job_interactions")
    op.drop_table("result_access_grants")
    op.drop_index(op.f("ix_match_results_disposition"), table_name="match_results")
    op.drop_index(op.f("ix_match_results_job_record_id"), table_name="match_results")
    op.drop_index(op.f("ix_match_results_match_run_id"), table_name="match_results")
    op.drop_table("match_results")
    op.drop_index(op.f("ix_match_runs_profile_id"), table_name="match_runs")
    op.drop_index(op.f("ix_match_runs_workspace_id"), table_name="match_runs")
    op.drop_table("match_runs")
