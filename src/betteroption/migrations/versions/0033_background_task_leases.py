"""Add cancellation state and fenced worker leases to background tasks.

Revision ID: 0033_background_task_leases
Revises: 0032_explore_import_origin
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_background_task_leases"
down_revision = "0032_explore_import_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_runs",
        sa.Column("provider_unpriced_operations", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("background_tasks") as batch:
        batch.add_column(sa.Column("claim_token", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("claim_owner", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_background_tasks_lease_expires_at",
        "background_tasks",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_background_tasks_lease_expires_at", table_name="background_tasks")
    with op.batch_alter_table("background_tasks") as batch:
        batch.drop_column("cancelled_at")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("claim_owner")
        batch.drop_column("claim_token")
    op.drop_column("match_runs", "provider_unpriced_operations")
