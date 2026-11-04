"""Persist transparent route ranges, endpoints, and confidence."""

from alembic import op
import sqlalchemy as sa


revision = "0007_route_evidence"
down_revision = "0006_cv_documents"
branch_labels = None
depends_on = None


ROUTE_COLUMNS = (
    sa.Column("duration_low_minutes", sa.Integer(), nullable=True),
    sa.Column("duration_high_minutes", sa.Integer(), nullable=True),
    sa.Column("sample_minutes_json", sa.Text(), nullable=True),
    sa.Column("precision", sa.String(length=32), nullable=True),
    sa.Column("confidence", sa.String(length=16), nullable=True),
    sa.Column("origin_resolved", sa.String(length=500), nullable=True),
    sa.Column("destination_resolved", sa.String(length=500), nullable=True),
    sa.Column("origin_precision", sa.String(length=32), nullable=True),
    sa.Column("destination_precision", sa.String(length=32), nullable=True),
    sa.Column("route_scope", sa.String(length=100), nullable=True),
)


def upgrade() -> None:
    for column in ROUTE_COLUMNS:
        op.add_column("commute_estimates", column)


def downgrade() -> None:
    for column in reversed(ROUTE_COLUMNS):
        op.drop_column("commute_estimates", column.name)
