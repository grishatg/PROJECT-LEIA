"""add prompt-cache token columns to scored_leads and draft_messages

Records Anthropic prompt-cache usage (read/write tokens) per scoring and
drafting call, so cache hits are observable and costable once the cached
prefix grows past the model's minimum.

Revision ID: 9f3a1c7b2d40
Revises: 47a44131a3fc
Create Date: 2026-06-22 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9f3a1c7b2d40'
down_revision: Union[str, Sequence[str], None] = '47a44131a3fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ("scored_leads", "draft_messages"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.add_column(
                sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0")
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("scored_leads", "draft_messages"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("cache_write_tokens")
            batch_op.drop_column("cache_read_tokens")
