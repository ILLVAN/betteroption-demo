"""Tie an Explore import batch to the snapshot that created it.

Revision ID: 0032_explore_import_origin
Revises: 0031_private_alpha_roles_feedback
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_explore_import_origin"
down_revision = "0031_private_alpha_roles_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("background_job_import_batches") as batch:
        batch.add_column(sa.Column("source_explore_task_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_background_import_source_explore_task",
            "explore_searches",
            ["source_explore_task_id"],
            ["task_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("background_job_import_batches") as batch:
        batch.drop_constraint(
            "fk_background_import_source_explore_task",
            type_="foreignkey",
        )
        batch.drop_column("source_explore_task_id")
