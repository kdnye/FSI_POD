"""add mawb_number to load_board

Revision ID: 20260304_02
Revises: 20260304_01
Create Date: 2026-03-04 00:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260304_02"
down_revision = "20260304_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("load_board", sa.Column("mawb_number", sa.String(length=100), nullable=True))
    op.create_index("ix_load_board_mawb_number", "load_board", ["mawb_number"], unique=False)


def downgrade():
    op.drop_index("ix_load_board_mawb_number", table_name="load_board")
    op.drop_column("load_board", "mawb_number")
