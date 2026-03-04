"""expand pod_records.action_type length

Revision ID: 20260304_03
Revises: 20260304_02
Create Date: 2026-03-04 01:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260304_03"
down_revision = "20260304_02"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "pod_records",
        "action_type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "pod_records",
        "action_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
