"""add provider_chat_id + provider_thread_ref to conversation_threads

Lets LEIA match an inbound LinkedIn reply back to the right thread/prospect by the
Unipile chat id, and reconcile a connection-request to its chat once accepted.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_threads",
        sa.Column("provider_chat_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "conversation_threads",
        sa.Column("provider_thread_ref", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_conversation_threads_provider_chat_id",
        "conversation_threads",
        ["provider_chat_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_threads_provider_chat_id", table_name="conversation_threads"
    )
    op.drop_column("conversation_threads", "provider_thread_ref")
    op.drop_column("conversation_threads", "provider_chat_id")
