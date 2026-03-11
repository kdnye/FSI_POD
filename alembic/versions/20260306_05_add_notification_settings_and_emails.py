"""add notification settings table and email columns

Revision ID: 20260306_05
Revises: 20260306_04
Create Date: 2026-03-06 01:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_05"
down_revision = "20260306_04"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in set(inspector.get_table_names())


def upgrade():
    if not _has_column("load_board", "shipper_email"):
        op.add_column("load_board", sa.Column("shipper_email", sa.String(length=255), nullable=True))
    if not _has_column("load_board", "consignee_email"):
        op.add_column("load_board", sa.Column("consignee_email", sa.String(length=255), nullable=True))

    if _has_table("shipments") and not _has_column("shipments", "shipper_email"):
        op.add_column("shipments", sa.Column("shipper_email", sa.String(length=255), nullable=True))
    if _has_table("shipments") and not _has_column("shipments", "consignee_email"):
        op.add_column("shipments", sa.Column("consignee_email", sa.String(length=255), nullable=True))

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_settings (
            id INTEGER PRIMARY KEY,
            notify_shipper_pickup BOOLEAN NOT NULL DEFAULT FALSE,
            notify_origin_drop BOOLEAN NOT NULL DEFAULT FALSE,
            notify_dest_pickup BOOLEAN NOT NULL DEFAULT FALSE,
            notify_consignee_drop BOOLEAN NOT NULL DEFAULT FALSE,
            custom_cc_emails TEXT
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS notification_settings")

    if _has_table("shipments") and _has_column("shipments", "consignee_email"):
        op.drop_column("shipments", "consignee_email")
    if _has_table("shipments") and _has_column("shipments", "shipper_email"):
        op.drop_column("shipments", "shipper_email")

    if _has_column("load_board", "consignee_email"):
        op.drop_column("load_board", "consignee_email")
    if _has_column("load_board", "shipper_email"):
        op.drop_column("load_board", "shipper_email")
