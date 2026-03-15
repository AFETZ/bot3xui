"""add plan state to user

Revision ID: c7f9d3e42b1a
Revises: 032f2bef8d8d
Create Date: 2026-03-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f9d3e42b1a"
down_revision: Union[str, None] = "032f2bef8d8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_plan_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("current_period_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("current_period_duration_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("current_period_duration_days")
        batch_op.drop_column("current_period_started_at")
        batch_op.drop_column("current_plan_code")
