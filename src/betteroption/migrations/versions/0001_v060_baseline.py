"""Create the v0.6.0 persistent job corpus baseline."""

from alembic import op
import sqlalchemy as sa


revision = "0001_v060_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("last_observation_kind", sa.String(length=32), nullable=False),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("current_content_hash", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )
    op.create_table(
        "job_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_record_id"], ["job_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_job_observations_job_record_id"),
        "job_observations",
        ["job_record_id"],
        unique=False,
    )
    op.create_table(
        "job_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("posting_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_record_id"], ["job_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_job_revisions_job_record_id"),
        "job_revisions",
        ["job_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_revisions_posting_id"),
        "job_revisions",
        ["posting_id"],
        unique=False,
    )
    op.create_table(
        "job_url_aliases",
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("job_record_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["job_record_id"], ["job_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("normalized_url"),
    )
    op.create_index(
        op.f("ix_job_url_aliases_job_record_id"),
        "job_url_aliases",
        ["job_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_url_aliases_job_record_id"), table_name="job_url_aliases")
    op.drop_table("job_url_aliases")
    op.drop_index(op.f("ix_job_revisions_posting_id"), table_name="job_revisions")
    op.drop_index(op.f("ix_job_revisions_job_record_id"), table_name="job_revisions")
    op.drop_table("job_revisions")
    op.drop_index(op.f("ix_job_observations_job_record_id"), table_name="job_observations")
    op.drop_table("job_observations")
    op.drop_table("job_records")
