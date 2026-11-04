"""Add unique bounded usernames.

Revision ID: 0014_account_security
Revises: 0013_accounts_tenants
"""

from __future__ import annotations

import unicodedata

from alembic import op
import sqlalchemy as sa


revision = "0014_account_security"
down_revision = "0013_accounts_tenants"
branch_labels = None
depends_on = None


def _clean_username(value: str) -> str:
    display = " ".join(unicodedata.normalize("NFKC", value or "").split())
    return display[:32] or "user"


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("username_normalized", sa.String(length=128), nullable=True),
    )
    connection = op.get_bind()
    rows = (
        connection.execute(sa.text("SELECT id, display_name FROM accounts ORDER BY created_at, id"))
        .mappings()
        .all()
    )
    used: set[str] = set()
    for row in rows:
        base = _clean_username(row["display_name"])
        candidate = base
        suffix = 2
        while candidate.casefold() in used:
            marker = f"-{suffix}"
            candidate = f"{base[: 32 - len(marker)]}{marker}"
            suffix += 1
        used.add(candidate.casefold())
        connection.execute(
            sa.text(
                "UPDATE accounts "
                "SET display_name = :display_name, username_normalized = :normalized "
                "WHERE id = :account_id"
            ),
            {
                "display_name": candidate,
                "normalized": candidate.casefold(),
                "account_id": row["id"],
            },
        )
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column(
            "display_name",
            existing_type=sa.String(length=120),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
        batch.alter_column(
            "username_normalized",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        batch.create_index(
            "ix_accounts_username_normalized",
            ["username_normalized"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_username_normalized")
        batch.alter_column(
            "display_name",
            existing_type=sa.String(length=32),
            type_=sa.String(length=120),
            existing_nullable=False,
        )
        batch.drop_column("username_normalized")
