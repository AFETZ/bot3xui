"""add pending tariff and promo restrictions

Revision ID: b9f4e2a7c6d1
Revises: 6d4f51e27a9b
Create Date: 2026-06-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9f4e2a7c6d1"
down_revision: Union[str, None] = "6d4f51e27a9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pending_plan_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("pending_period_duration_days", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pending_plan_starts_at", sa.BigInteger(), nullable=True))
    with op.batch_alter_table("promocodes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("valid_until", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "deny_trial",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("allowed_plan_code", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("promocodes", schema=None) as batch_op:
        batch_op.drop_column("allowed_plan_code")
        batch_op.drop_column("deny_trial")
        batch_op.drop_column("valid_until")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("pending_plan_starts_at")
        batch_op.drop_column("pending_period_duration_days")
        batch_op.drop_column("pending_plan_code")
