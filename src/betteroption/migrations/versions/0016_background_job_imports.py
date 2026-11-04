"""Add durable payloads for background Explore imports.

Revision ID: 0016_background_job_imports
Revises: 0015_alpha_readiness
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_background_job_imports"
down_revision = "0015_alpha_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    table_names = set(sa.inspect(connection).get_table_names())
    if "background_job_import_batches" not in table_names:
        op.create_table(
            "background_job_import_batches",
            sa.Column(
                "task_id",
                sa.String(36),
                sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("destination", sa.String(24), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "background_job_import_items" not in table_names:
        op.create_table(
            "background_job_import_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(36),
                sa.ForeignKey("background_job_import_batches.task_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("source_url", sa.String(2_000), nullable=False),
            sa.UniqueConstraint(
                "task_id",
                "position",
                name="uq_background_job_import_position",
            ),
        )
    index_names = {
        index["name"] for index in sa.inspect(connection).get_indexes("background_job_import_items")
    }
    if "ix_background_job_import_items_task_id" not in index_names:
        op.create_index(
            "ix_background_job_import_items_task_id",
            "background_job_import_items",
            ["task_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_background_job_import_items_task_id",
        table_name="background_job_import_items",
    )
    op.drop_table("background_job_import_items")
    op.drop_table("background_job_import_batches")
