"""Add typed posting-date evidence overrides.

Revision ID: 0024_posting_date_evidence
Revises: 0023_employer_reputation_ratings
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_posting_date_evidence"
down_revision = "0023_employer_reputation_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_evidence_overrides") as batch_op:
        batch_op.add_column(sa.Column("posting_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_evidence_overrides") as batch_op:
        batch_op.drop_column("posting_date")
