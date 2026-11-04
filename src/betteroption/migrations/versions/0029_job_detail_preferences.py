"""Persist persona-owned Job Detail editing preferences.

Revision ID: 0029_job_detail_preferences
Revises: 0028_job_ratings
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_job_detail_preferences"
down_revision = "0028_job_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_personas") as batch_op:
        batch_op.add_column(
            sa.Column(
                "also_update_compass_skills",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("account_personas") as batch_op:
        batch_op.drop_column("also_update_compass_skills")
