"""Add disabled flag to user accounts

Revision ID: e9f4c82b296b
Revises: 5e8a403368be
Create Date: 2026-01-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e9f4c82b296b"
down_revision = "5e8a403368be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("profiles", "disabled", server_default=None)


def downgrade() -> None:
    op.drop_column("profiles", "disabled")
