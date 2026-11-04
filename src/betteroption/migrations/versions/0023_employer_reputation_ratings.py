"""Add persona-owned employer reputation ratings.

Revision ID: 0023_employer_reputation_ratings
Revises: 0022_application_draft_slots
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_employer_reputation_ratings"
down_revision = "0022_application_draft_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "persona_employer_reputation_ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "persona_id",
            sa.String(36),
            sa.ForeignKey("account_personas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employer_key", sa.String(300), nullable=False),
        sa.Column("employer_name", sa.String(300), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "persona_id",
            "employer_key",
            name="uq_persona_employer_reputation_ratings_company",
        ),
        sa.CheckConstraint(
            "stars >= 1 AND stars <= 5",
            name="ck_persona_employer_reputation_ratings_stars",
        ),
    )
    op.create_index(
        "ix_persona_employer_reputation_ratings_persona_id",
        "persona_employer_reputation_ratings",
        ["persona_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persona_employer_reputation_ratings_persona_id",
        table_name="persona_employer_reputation_ratings",
    )
    op.drop_table("persona_employer_reputation_ratings")
