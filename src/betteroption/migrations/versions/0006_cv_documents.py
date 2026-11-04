"""Add privacy-aware CV text documents."""

from alembic import op
import sqlalchemy as sa


revision = "0006_cv_documents"
down_revision = "0005_commute_estimates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cv_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("retention", sa.String(length=32), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["profile_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cv_documents_workspace_id"),
        "cv_documents",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cv_documents_workspace_id"), table_name="cv_documents")
    op.drop_table("cv_documents")
