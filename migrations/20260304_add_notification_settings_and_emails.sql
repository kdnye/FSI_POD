ALTER TABLE load_board
    ADD COLUMN IF NOT EXISTS shipper_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS consignee_email VARCHAR(255);

ALTER TABLE shipments
    ADD COLUMN IF NOT EXISTS shipper_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS consignee_email VARCHAR(255);

CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER PRIMARY KEY,
    notify_shipper_pickup BOOLEAN NOT NULL DEFAULT FALSE,
    notify_origin_drop BOOLEAN NOT NULL DEFAULT FALSE,
    notify_dest_pickup BOOLEAN NOT NULL DEFAULT FALSE,
    notify_consignee_drop BOOLEAN NOT NULL DEFAULT FALSE,
    custom_cc_emails TEXT
);
