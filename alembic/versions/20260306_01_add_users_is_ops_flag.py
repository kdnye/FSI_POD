"""add users.is_ops flag

Revision ID: 20260306_01
Revises: 20260305_01
Create Date: 2026-03-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_01"
down_revision = "20260305_01"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if not _has_column("users", "is_ops"):
        op.add_column("users", sa.Column("is_ops", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.alter_column("users", "is_ops", server_default=None)


def downgrade():
    if _has_column("users", "is_ops"):
        op.drop_column("users", "is_ops")
