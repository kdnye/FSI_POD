"""add pod_records shipment linkage and geolocation fields

Revision ID: 20260306_04
Revises: 20260306_03
Create Date: 2026-03-06 00:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_04"
down_revision = "20260306_03"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if not _has_column("pod_records", "latitude"):
        op.add_column("pod_records", sa.Column("latitude", sa.String(length=32), nullable=True))
    if not _has_column("pod_records", "longitude"):
        op.add_column("pod_records", sa.Column("longitude", sa.String(length=32), nullable=True))
    if not _has_column("pod_records", "shipment_id"):
        op.add_column("pod_records", sa.Column("shipment_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            "pod_records_shipment_id_fkey",
            "pod_records",
            "shipments",
            ["shipment_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_column("pod_records", "leg_id"):
        op.add_column("pod_records", sa.Column("leg_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            "pod_records_leg_id_fkey",
            "pod_records",
            "shipment_legs",
            ["leg_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_column("pod_records", "leg_sequence"):
        op.add_column("pod_records", sa.Column("leg_sequence", sa.Integer(), nullable=True))
    if not _has_column("pod_records", "leg_type"):
        op.add_column("pod_records", sa.Column("leg_type", sa.String(length=64), nullable=True))

    op.execute("CREATE INDEX IF NOT EXISTS ix_pod_records_shipment_id ON pod_records (shipment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pod_records_leg_id ON pod_records (leg_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_pod_records_leg_id")
    op.execute("DROP INDEX IF EXISTS ix_pod_records_shipment_id")

    if _has_column("pod_records", "leg_type"):
        op.drop_column("pod_records", "leg_type")
    if _has_column("pod_records", "leg_sequence"):
        op.drop_column("pod_records", "leg_sequence")
    if _has_column("pod_records", "leg_id"):
        op.drop_constraint("pod_records_leg_id_fkey", "pod_records", type_="foreignkey")
        op.drop_column("pod_records", "leg_id")
    if _has_column("pod_records", "shipment_id"):
        op.drop_constraint("pod_records_shipment_id_fkey", "pod_records", type_="foreignkey")
        op.drop_column("pod_records", "shipment_id")
    if _has_column("pod_records", "longitude"):
        op.drop_column("pod_records", "longitude")
    if _has_column("pod_records", "latitude"):
        op.drop_column("pod_records", "latitude")
