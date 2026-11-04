"""Add explicit persona-owned ratings for individual jobs.

Revision ID: 0028_job_ratings
Revises: 0027_context_evidence_overrides
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_job_ratings"
down_revision = "0027_context_evidence_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona_job_ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "persona_id",
            sa.String(36),
            sa.ForeignKey("account_personas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_record_id",
            sa.String(36),
            sa.ForeignKey("job_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "persona_id",
            "job_record_id",
            name="uq_persona_job_ratings_job",
        ),
        sa.CheckConstraint(
            "stars >= 0 AND stars <= 5",
            name="ck_persona_job_ratings_stars",
        ),
    )
    op.create_index(
        "ix_persona_job_ratings_persona_id",
        "persona_job_ratings",
        ["persona_id"],
    )
    op.create_index(
        "ix_persona_job_ratings_job_record_id",
        "persona_job_ratings",
        ["job_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persona_job_ratings_job_record_id",
        table_name="persona_job_ratings",
    )
    op.drop_index(
        "ix_persona_job_ratings_persona_id",
        table_name="persona_job_ratings",
    )
    op.drop_table("persona_job_ratings")
