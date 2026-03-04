"""baseline schema

Revision ID: 20260304_01
Revises:
Create Date: 2026-03-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260304_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Baseline migration for existing databases.
    # This revision intentionally performs no DDL and establishes Alembic state tracking.
    pass


def downgrade():
    pass
