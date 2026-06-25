"""add local subscription snapshot

Revision ID: 6d4f51e27a9b
Revises: f8a2b1c7d9e0
Create Date: 2026-06-19 12:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "6d4f51e27a9b"
down_revision: Union[str, None] = "f8a2b1c7d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subscription_max_devices", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("subscription_traffic_total", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("subscription_traffic_remaining", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(sa.Column("subscription_traffic_used", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("subscription_traffic_up", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("subscription_traffic_down", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("subscription_expiry_time", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("subscription_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("subscription_last_synced_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("subscription_sync_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("subscription_sync_status")
        batch_op.drop_column("subscription_last_synced_at")
        batch_op.drop_column("subscription_enabled")
        batch_op.drop_column("subscription_expiry_time")
        batch_op.drop_column("subscription_traffic_down")
        batch_op.drop_column("subscription_traffic_up")
        batch_op.drop_column("subscription_traffic_used")
        batch_op.drop_column("subscription_traffic_remaining")
        batch_op.drop_column("subscription_traffic_total")
        batch_op.drop_column("subscription_max_devices")
