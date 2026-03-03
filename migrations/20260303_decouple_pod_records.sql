-- Decouple POD records from strict load-board FK so manual/off-sheet entries can be stored.
ALTER TABLE pod_records
DROP CONSTRAINT IF EXISTS pod_records_hwb_number_fkey;

-- Align POD fields to support manual entries while preserving existing data.
ALTER TABLE pod_records
ALTER COLUMN hwb_number TYPE VARCHAR(255),
ALTER COLUMN shipper DROP NOT NULL,
ALTER COLUMN consignee DROP NOT NULL,
ALTER COLUMN contact_name DROP NOT NULL,
ALTER COLUMN phone DROP NOT NULL;

-- Keep HWB lookups fast for reconciliation and matching workflows.
CREATE INDEX IF NOT EXISTS idx_pod_records_hwb ON pod_records (hwb_number);

-- Reconciliation view: includes both matched system rows and manual PODs.
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
