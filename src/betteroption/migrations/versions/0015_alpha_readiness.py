"""Add legal acknowledgements and provider billing calibration.

Revision ID: 0015_alpha_readiness
Revises: 0014_account_security
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_alpha_readiness"
down_revision = "0014_account_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("document_kind", sa.String(length=40), nullable=False),
        sa.Column("document_version", sa.String(length=80), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "document_kind",
            "document_version",
            name="uq_legal_acceptance_account_document_version",
        ),
    )
    op.create_index(
        "ix_legal_acceptances_account_id",
        "legal_acceptances",
        ["account_id"],
    )
    op.create_table(
        "provider_billing_periods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billed_amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source_label", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_billing_periods_provider",
        "provider_billing_periods",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_billing_periods_provider",
        table_name="provider_billing_periods",
    )
    op.drop_table("provider_billing_periods")
    op.drop_index("ix_legal_acceptances_account_id", table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
