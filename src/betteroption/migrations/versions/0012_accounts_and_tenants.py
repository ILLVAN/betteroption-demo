"""Compatibility marker for the superseded v0.7.0a account branch.

Revision ID: 0012_accounts_and_tenants
Revises: 0011_background_tasks

The original migration created an experimental tenant schema.  v0.7.0c keeps
the revision identifier so databases that already recorded it can move onto
the supported account chain.  Fresh databases intentionally perform no work
at this marker.
"""

revision = "0012_accounts_and_tenants"
down_revision = "0011_background_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
