"""decouple pod_records from strict load_board linkage

Revision ID: 20260306_02
Revises: 20260306_01
Create Date: 2026-03-06 00:15:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_02"
down_revision = "20260306_01"
branch_labels = None
depends_on = None


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    op.drop_constraint("pod_records_hwb_number_fkey", "pod_records", type_="foreignkey")

    op.alter_column("pod_records", "hwb_number", existing_type=sa.String(length=100), type_=sa.String(length=255), nullable=True)
    op.alter_column("pod_records", "shipper", existing_type=sa.String(length=150), nullable=True)
    op.alter_column("pod_records", "consignee", existing_type=sa.String(length=150), nullable=True)
    op.alter_column("pod_records", "contact_name", existing_type=sa.String(length=120), nullable=True)
    op.alter_column("pod_records", "phone", existing_type=sa.String(length=40), nullable=True)

    if not _has_index("pod_records", "idx_pod_records_hwb"):
        op.create_index("idx_pod_records_hwb", "pod_records", ["hwb_number"], unique=False)

    op.execute(
        """
        CREATE OR REPLACE VIEW v_shipping_reconciliation AS
        SELECT
            pr.id AS pod_record_id,
            pr.hwb_number,
            pr.timestamp AS pod_timestamp,
            pr.action_type,
            pr.driver_id,
            COALESCE(pr.shipper, lb.shipper) AS shipper,
            COALESCE(pr.consignee, lb.consignee) AS consignee,
            COALESCE(pr.contact_name, lb.contact_name) AS contact_name,
            COALESCE(pr.phone, lb.phone) AS phone,
            lb.assigned_driver,
            lb.status AS load_board_status,
            CASE
                WHEN pr.hwb_number IS NULL OR lb.hwb_number IS NULL THEN 'Manual POD'
                ELSE 'System Match'
            END AS record_type
        FROM pod_records AS pr
        LEFT JOIN load_board AS lb ON lb.hwb_number = pr.hwb_number;
        """
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS v_shipping_reconciliation")
    if _has_index("pod_records", "idx_pod_records_hwb"):
        op.drop_index("idx_pod_records_hwb", table_name="pod_records")

    op.alter_column("pod_records", "phone", existing_type=sa.String(length=40), nullable=False)
    op.alter_column("pod_records", "contact_name", existing_type=sa.String(length=120), nullable=False)
    op.alter_column("pod_records", "consignee", existing_type=sa.String(length=150), nullable=False)
    op.alter_column("pod_records", "shipper", existing_type=sa.String(length=150), nullable=False)
    op.alter_column("pod_records", "hwb_number", existing_type=sa.String(length=255), type_=sa.String(length=100), nullable=True)

    op.create_foreign_key("pod_records_hwb_number_fkey", "pod_records", "load_board", ["hwb_number"], ["hwb_number"])
