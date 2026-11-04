"""Allow up to three named application drafts per persona and job.

Revision ID: 0022_application_draft_slots
Revises: 0021_job_evidence_overrides
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_application_draft_slots"
down_revision = "0021_job_evidence_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("application_drafts", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "name",
                sa.String(120),
                nullable=False,
                server_default="Draft 1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "slot",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.drop_constraint(
            "uq_application_drafts_workspace_job",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_application_drafts_workspace_job_slot",
            ["workspace_id", "job_record_id", "slot"],
        )
        batch_op.create_check_constraint(
            "ck_application_drafts_slot_range",
            "slot >= 1 AND slot <= 3",
        )


def downgrade() -> None:
    # A v0.7.1f database allowed one row per job. Keep the newest local draft
    # when downgrading a database that used the three-slot v0.7.1g model.
    op.execute(
        sa.text(
            """
            DELETE FROM application_drafts
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY workspace_id, job_record_id
                            ORDER BY updated_at DESC, id DESC
                        ) AS row_number
                    FROM application_drafts
                ) ranked
                WHERE row_number > 1
            )
            """
        )
    )
    with op.batch_alter_table("application_drafts", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_application_drafts_slot_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_application_drafts_workspace_job_slot",
            type_="unique",
        )
        batch_op.drop_column("slot")
        batch_op.drop_column("name")
        batch_op.create_unique_constraint(
            "uq_application_drafts_workspace_job",
            ["workspace_id", "job_record_id"],
        )
