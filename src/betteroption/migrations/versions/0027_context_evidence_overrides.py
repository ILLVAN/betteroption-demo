"""Add generic private corrections for contextual machine evidence.

Revision ID: 0027_context_evidence_overrides
Revises: 0026_application_guidance
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_context_evidence_overrides"
down_revision = "0026_application_guidance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_evidence_overrides") as batch_op:
        batch_op.add_column(sa.Column("text_value", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_evidence_overrides") as batch_op:
        batch_op.drop_column("text_value")
