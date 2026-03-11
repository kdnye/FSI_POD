# Legacy Manual SQL Migrations (Deprecated)

The SQL files in this directory are retained as historical references only.

## Policy
- **Do not execute** these SQL files in environments.
- The **only** supported schema rollout path is:

```bash
flask db upgrade --directory alembic
```

## Legacy-to-Alembic Mapping
| Legacy SQL file | Alembic replacement revision |
|---|---|
| `20260303_add_is_ops_to_users.sql` | `alembic/versions/20260306_01_add_users_is_ops_flag.py` |
| `20260303_decouple_pod_records.sql` | `alembic/versions/20260306_02_decouple_pod_records.py` |
| `20260304_add_shipment_tables.sql` | `alembic/versions/20260306_03_add_shipment_tables.py` |
| `20260304_add_pod_record_location_and_leg_fields.sql` | `alembic/versions/20260306_04_add_pod_record_location_and_leg_fields.py` |
| `20260304_add_notification_settings_and_emails.sql` | `alembic/versions/20260306_05_add_notification_settings_and_emails.py` |
| `20260304_add_load_board_mawb_number.sql` | `alembic/versions/20260304_02_add_load_board_mawb_number.py` |
