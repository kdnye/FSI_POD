"""add shipment_groups, shipments, and shipment_legs tables

Revision ID: 20260306_03
Revises: 20260306_02
Create Date: 2026-03-06 00:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260306_03"
down_revision = "20260306_02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_groups (
            id BIGSERIAL PRIMARY KEY,
            mawb_number VARCHAR(100) NOT NULL UNIQUE,
            carrier VARCHAR(120),
            origin_airport VARCHAR(10),
            destination_airport VARCHAR(10),
            booked_at_utc TIMESTAMPTZ,
            created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id BIGSERIAL PRIMARY KEY,
            hwb_number VARCHAR(100) NOT NULL UNIQUE,
            shipment_group_id BIGINT NOT NULL REFERENCES shipment_groups(id) ON DELETE CASCADE,
            shipper_address VARCHAR(255),
            consignee_address VARCHAR(255),
            current_leg_index INTEGER NOT NULL DEFAULT 1 CHECK (current_leg_index > 0),
            overall_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
            created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_shipments_overall_status CHECK (overall_status IN ('PENDING', 'IN_PROGRESS', 'PICKED_UP', 'DELIVERED', 'CANCELLED'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_legs (
            id BIGSERIAL PRIMARY KEY,
            shipment_id BIGINT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
            leg_sequence INTEGER NOT NULL CHECK (leg_sequence > 0),
            leg_type VARCHAR(50) NOT NULL,
            from_location_type VARCHAR(30),
            to_location_type VARCHAR(30),
            from_address VARCHAR(255),
            to_address VARCHAR(255),
            from_airport VARCHAR(10),
            to_airport VARCHAR(10),
            assigned_driver_id INTEGER REFERENCES users(id),
            status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
            started_at_utc TIMESTAMPTZ,
            completed_at_utc TIMESTAMPTZ,
            created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_shipment_legs_shipment_id_leg_sequence UNIQUE (shipment_id, leg_sequence),
            CONSTRAINT ck_shipment_legs_leg_type CHECK (leg_type IN ('PICKUP_TO_ORIGIN_AIRPORT', 'AIRPORT_TO_AIRPORT', 'DEST_AIRPORT_TO_CONSIGNEE')),
            CONSTRAINT ck_shipment_legs_status CHECK (status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'FAILED'))
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_shipments_hwb_number ON shipments(hwb_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_shipment_groups_mawb_number ON shipment_groups(mawb_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_shipment_legs_shipment_id_leg_sequence ON shipment_legs(shipment_id, leg_sequence)")

    op.execute(
        """
        WITH seed_group AS (
            INSERT INTO shipment_groups (
                mawb_number,
                carrier,
                origin_airport,
                destination_airport,
                booked_at_utc
            )
            VALUES (
                'LEGACY-LOAD-BOARD',
                'LEGACY',
                NULL,
                NULL,
                NOW()
            )
            ON CONFLICT (mawb_number)
            DO UPDATE SET mawb_number = EXCLUDED.mawb_number
            RETURNING id
        ), resolved_group AS (
            SELECT id FROM seed_group
            UNION ALL
            SELECT id FROM shipment_groups WHERE mawb_number = 'LEGACY-LOAD-BOARD'
            LIMIT 1
        )
        INSERT INTO shipments (
            hwb_number,
            shipment_group_id,
            shipper_address,
            consignee_address,
            current_leg_index,
            overall_status,
            created_at_utc,
            updated_at_utc
        )
        SELECT
            lb.hwb_number,
            rg.id,
            lb.shipper,
            lb.consignee,
            CASE WHEN lb.status = 'Delivered' THEN 2 ELSE 1 END,
            CASE
                WHEN lb.status = 'Delivered' THEN 'DELIVERED'
                WHEN lb.status = 'Picked Up' THEN 'PICKED_UP'
                WHEN lb.status = 'In Progress' THEN 'IN_PROGRESS'
                ELSE 'PENDING'
            END,
            NOW(),
            NOW()
        FROM load_board lb
        CROSS JOIN resolved_group rg
        ON CONFLICT (hwb_number) DO UPDATE
        SET
            shipment_group_id = EXCLUDED.shipment_group_id,
            shipper_address = EXCLUDED.shipper_address,
            consignee_address = EXCLUDED.consignee_address,
            current_leg_index = EXCLUDED.current_leg_index,
            overall_status = EXCLUDED.overall_status,
            updated_at_utc = NOW();
        """
    )

    op.execute(
        """
        INSERT INTO shipment_legs (
            shipment_id,
            leg_sequence,
            leg_type,
            from_location_type,
            to_location_type,
            from_address,
            to_address,
            from_airport,
            to_airport,
            assigned_driver_id,
            status,
            started_at_utc,
            completed_at_utc,
            created_at_utc,
            updated_at_utc
        )
        SELECT
            s.id,
            1,
            'PICKUP_TO_ORIGIN_AIRPORT',
            'SHIPPER',
            'ORIGIN_AIRPORT',
            lb.shipper,
            NULL,
            NULL,
            NULL,
            lb.assigned_driver,
            CASE
                WHEN lb.status IN ('Picked Up', 'In Progress', 'Delivered') THEN 'COMPLETED'
                ELSE 'ASSIGNED'
            END,
            CASE WHEN lb.status IN ('Picked Up', 'In Progress', 'Delivered') THEN NOW() ELSE NULL END,
            CASE WHEN lb.status IN ('Picked Up', 'In Progress', 'Delivered') THEN NOW() ELSE NULL END,
            NOW(),
            NOW()
        FROM shipments s
        JOIN load_board lb ON lb.hwb_number = s.hwb_number
        ON CONFLICT (shipment_id, leg_sequence) DO UPDATE
        SET
            assigned_driver_id = EXCLUDED.assigned_driver_id,
            status = EXCLUDED.status,
            updated_at_utc = NOW();
        """
    )

    op.execute(
        """
        INSERT INTO shipment_legs (
            shipment_id,
            leg_sequence,
            leg_type,
            from_location_type,
            to_location_type,
            from_address,
            to_address,
            from_airport,
            to_airport,
            assigned_driver_id,
            status,
            started_at_utc,
            completed_at_utc,
            created_at_utc,
            updated_at_utc
        )
        SELECT
            s.id,
            2,
            'DEST_AIRPORT_TO_CONSIGNEE',
            'DESTINATION_AIRPORT',
            'CONSIGNEE',
            NULL,
            lb.consignee,
            NULL,
            NULL,
            lb.assigned_driver,
            CASE
                WHEN lb.status = 'Delivered' THEN 'COMPLETED'
                WHEN lb.status IN ('Picked Up', 'In Progress') THEN 'ASSIGNED'
                ELSE 'PENDING'
            END,
            CASE WHEN lb.status = 'Delivered' THEN NOW() ELSE NULL END,
            CASE WHEN lb.status = 'Delivered' THEN NOW() ELSE NULL END,
            NOW(),
            NOW()
        FROM shipments s
        JOIN load_board lb ON lb.hwb_number = s.hwb_number
        ON CONFLICT (shipment_id, leg_sequence) DO UPDATE
        SET
            assigned_driver_id = EXCLUDED.assigned_driver_id,
            status = EXCLUDED.status,
            updated_at_utc = NOW();
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS shipment_legs")
    op.execute("DROP TABLE IF EXISTS shipments")
    op.execute("DROP TABLE IF EXISTS shipment_groups")
