"""Add verified poster access and first-party employer job postings.

Revision ID: 0030_verified_job_posters
Revises: 0029_job_detail_preferences
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_verified_job_posters"
down_revision = "0029_job_detail_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_poster_access",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("company_name", sa.String(length=300), nullable=False),
        sa.Column("company_website", sa.String(length=2_000), nullable=False),
        sa.Column("work_email", sa.String(length=320), nullable=False),
        sa.Column("requester_note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_account_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_account_id"],
            ["accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index(
        "ix_job_poster_access_status",
        "job_poster_access",
        ["status"],
        unique=False,
    )
    op.create_table(
        "employer_job_postings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_account_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("employer_name", sa.String(length=500), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=False),
        sa.Column("work_model", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("application_url", sa.String(length=2_000), nullable=False),
        sa.Column("application_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employer_job_postings_owner_account_id",
        "employer_job_postings",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_employer_job_postings_status",
        "employer_job_postings",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_employer_job_postings_published_at",
        "employer_job_postings",
        ["published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employer_job_postings_published_at",
        table_name="employer_job_postings",
    )
    op.drop_index(
        "ix_employer_job_postings_status",
        table_name="employer_job_postings",
    )
    op.drop_index(
        "ix_employer_job_postings_owner_account_id",
        table_name="employer_job_postings",
    )
    op.drop_table("employer_job_postings")
    op.drop_index("ix_job_poster_access_status", table_name="job_poster_access")
    op.drop_table("job_poster_access")
