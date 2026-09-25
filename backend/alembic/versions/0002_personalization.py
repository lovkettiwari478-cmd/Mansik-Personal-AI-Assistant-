"""personalization: assistant_name + response_style

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(sa.Column("assistant_name", sa.String(length=40), nullable=False, server_default="MANISK"))
        batch.add_column(sa.Column("response_style", sa.String(length=16), nullable=False, server_default="balanced"))


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("response_style")
        batch.drop_column("assistant_name")
