"""Add private-alpha account roles, access tiers, and product feedback.

Revision ID: 0031_private_alpha_roles_feedback
Revises: 0030_verified_job_posters
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_private_alpha_roles_feedback"
down_revision = "0030_verified_job_posters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Alembic's version table is VARCHAR(32) by default, while this revision id
    # is 33 characters. SQLite does not enforce that declared width, which hid
    # the issue locally; PostgreSQL would reject Alembic's revision update after
    # this function returned. Widen before applying any part of the revision so
    # both fresh and existing PostgreSQL deployments can reach 0031 and later.
    if connection.dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    with op.batch_alter_table("accounts") as batch:
        batch.add_column(
            sa.Column(
                "role",
                sa.String(length=24),
                nullable=False,
                server_default="member",
            )
        )
        batch.add_column(
            sa.Column(
                "access_tier",
                sa.String(length=24),
                nullable=False,
                server_default="standard",
            )
        )

    op.create_table(
        "account_bootstrap",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_account_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["accounts.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("id = 1", name="ck_account_bootstrap_singleton"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_account_id"),
    )
    first_account_id = connection.execute(
        sa.text("SELECT id FROM accounts ORDER BY created_at, id LIMIT 1")
    ).scalar_one_or_none()
    connection.execute(
        sa.text(
            "INSERT INTO account_bootstrap (id, owner_account_id) VALUES (:id, :owner_account_id)"
        ),
        {"id": 1, "owner_account_id": first_account_id},
    )

    op.create_table(
        "product_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("contact_allowed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("operator_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_account_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_product_feedback_rating",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_account_id"],
            ["accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_feedback_account_id",
        "product_feedback",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_feedback_category",
        "product_feedback",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_product_feedback_status",
        "product_feedback",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_product_feedback_created_at",
        "product_feedback",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_feedback_created_at", table_name="product_feedback")
    op.drop_index("ix_product_feedback_status", table_name="product_feedback")
    op.drop_index("ix_product_feedback_category", table_name="product_feedback")
    op.drop_index("ix_product_feedback_account_id", table_name="product_feedback")
    op.drop_table("product_feedback")
    op.drop_table("account_bootstrap")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("access_tier")
        batch.drop_column("role")
