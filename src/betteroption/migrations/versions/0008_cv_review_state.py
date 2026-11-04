"""Record when retained CV text was reviewed for Compass evidence."""

from alembic import op
import sqlalchemy as sa


revision = "0008_cv_review_state"
down_revision = "0007_route_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv_documents", sa.Column("reviewed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("cv_documents", "reviewed_at")
