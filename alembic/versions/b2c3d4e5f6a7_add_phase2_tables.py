"""add Phase 2 tables: suppression list + conversation threads/messages/meetings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _common_cols() -> list:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "suppression_list",
        *_common_cols(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="opt_out"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "email", name="uq_suppression_email"),
    )
    op.create_index("ix_suppression_list_account_id", "suppression_list", ["account_id"])
    op.create_index("ix_suppression_list_email", "suppression_list", ["email"])

    op.create_table(
        "conversation_threads",
        *_common_cols(),
        sa.Column("prospect_id", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("last_intent", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_threads_account_id", "conversation_threads", ["account_id"])
    op.create_index("ix_conversation_threads_prospect_id", "conversation_threads", ["prospect_id"])

    op.create_table(
        "messages",
        *_common_cols(),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.String(length=200), nullable=True),
        sa.Column("intent", sa.String(length=30), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_account_id", "messages", ["account_id"])
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])

    op.create_table(
        "meetings",
        *_common_cols(),
        sa.Column("prospect_id", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="link_shared"),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meetings_account_id", "meetings", ["account_id"])
    op.create_index("ix_meetings_prospect_id", "meetings", ["prospect_id"])


def downgrade() -> None:
    op.drop_table("meetings")
    op.drop_table("messages")
    op.drop_table("conversation_threads")
    op.drop_table("suppression_list")
