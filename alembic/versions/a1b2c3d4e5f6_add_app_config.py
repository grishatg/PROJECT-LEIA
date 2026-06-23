"""add app_config key/value table

Stores editable config that must survive redeploys on an ephemeral hosted
filesystem (the web Settings editor persists the ICP YAML here).

Revision ID: a1b2c3d4e5f6
Revises: 9f3a1c7b2d40
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f3a1c7b2d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_app_config_account_id", "app_config", ["account_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_app_config_account_id", table_name="app_config")
    op.drop_table("app_config")
