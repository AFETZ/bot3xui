"""add multi-use promocodes

Revision ID: a1b2c3d4e5f6
Revises: c7f9d3e42b1a
Create Date: 2026-03-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c7f9d3e42b1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("promocodes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("max_activations", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_table(
        "promocode_activations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("promocode_id", sa.Integer(), nullable=False),
        sa.Column("user_tg_id", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promocode_id"],
            ["promocodes.id"],
            name="fk_promocode_activations_promocode_id_promocodes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_tg_id"],
            ["users.tg_id"],
            name="fk_promocode_activations_user_tg_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_promocode_activations"),
        sa.UniqueConstraint("promocode_id", "user_tg_id", name="uq_promocode_activation_user"),
    )


def downgrade() -> None:
    op.drop_table("promocode_activations")

    with op.batch_alter_table("promocodes", schema=None) as batch_op:
        batch_op.drop_column("max_activations")
