"""add research_notes: cached per-prospect opener hooks

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_notes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prospect_id", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=False, server_default="medium"),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_notes_account_id", "research_notes", ["account_id"])
    op.create_index("ix_research_notes_prospect_id", "research_notes", ["prospect_id"])


def downgrade() -> None:
    op.drop_index("ix_research_notes_prospect_id", table_name="research_notes")
    op.drop_index("ix_research_notes_account_id", table_name="research_notes")
    op.drop_table("research_notes")
