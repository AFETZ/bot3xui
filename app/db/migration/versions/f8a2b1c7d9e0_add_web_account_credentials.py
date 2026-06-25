"""add web account credentials

Revision ID: f8a2b1c7d9e0
Revises: e4b6f0c2d9a1
Create Date: 2026-05-29 08:08:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f8a2b1c7d9e0"
down_revision: Union[str, None] = "e4b6f0c2d9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("web_login", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("web_password_hash", sa.String(length=255), nullable=True)
        )
        batch_op.create_unique_constraint(
            op.f("uq_users_web_login"),
            ["web_login"],
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("uq_users_web_login"), type_="unique")
        batch_op.drop_column("web_password_hash")
        batch_op.drop_column("web_login")
