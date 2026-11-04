"""Score explicit employer ratings and queue single-job rematches.

Revision ID: 0025_employer_reputation_scoring
Revises: 0024_posting_date_evidence
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_employer_reputation_scoring"
down_revision = "0024_posting_date_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("persona_employer_reputation_ratings") as batch_op:
        batch_op.drop_constraint(
            "ck_persona_employer_reputation_ratings_stars",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_persona_employer_reputation_ratings_stars",
            "stars >= 0 AND stars <= 5",
        )

    op.create_table(
        "background_single_job_matches",
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_record_id",
            sa.String(36),
            sa.ForeignKey("job_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_background_single_job_matches_job_record_id",
        "background_single_job_matches",
        ["job_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_background_single_job_matches_job_record_id",
        table_name="background_single_job_matches",
    )
    op.drop_table("background_single_job_matches")
    op.execute("DELETE FROM persona_employer_reputation_ratings WHERE stars = 0")
    with op.batch_alter_table("persona_employer_reputation_ratings") as batch_op:
        batch_op.drop_constraint(
            "ck_persona_employer_reputation_ratings_stars",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_persona_employer_reputation_ratings_stars",
            "stars >= 1 AND stars <= 5",
        )
