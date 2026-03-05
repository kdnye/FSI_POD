"""add users.is_driver flag

Revision ID: 20260305_01
Revises: 20260304_03
Create Date: 2026-03-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_01"
down_revision = "20260304_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_driver", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("users", "is_driver", server_default=None)


def downgrade():
    op.drop_column("users", "is_driver")
