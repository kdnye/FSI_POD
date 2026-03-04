BEGIN;

ALTER TABLE load_board
ADD COLUMN IF NOT EXISTS mawb_number VARCHAR(100);

CREATE INDEX IF NOT EXISTS ix_load_board_mawb_number ON load_board (mawb_number);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'shipments'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'shipment_groups'
    ) THEN
        UPDATE load_board AS lb
        SET mawb_number = sg.mawb_number
        FROM shipments AS s
        JOIN shipment_groups AS sg ON sg.id = s.shipment_group_id
        WHERE s.hwb_number = lb.hwb_number
          AND sg.mawb_number IS NOT NULL
          AND (lb.mawb_number IS NULL OR lb.mawb_number = '');
    END IF;
END $$;

COMMIT;
