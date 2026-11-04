"""Compatibility marker for the superseded v0.7.0a import branch.

Revision ID: 0013_background_job_imports
Revises: 0012_accounts_and_tenants

The supported import tables are created by revision
``0016_background_job_imports``.  Keeping this no-op marker makes an existing
v0.7.0a database upgradeable while preventing a second Alembic head.
"""

revision = "0013_background_job_imports"
down_revision = "0012_accounts_and_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
