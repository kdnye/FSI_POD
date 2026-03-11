import os
from collections.abc import Iterable

from sqlalchemy import inspect, text

from app import db


REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("load_board", "mawb_number"),
)


def get_required_schema_report(required_columns: Iterable[tuple[str, str]] = REQUIRED_COLUMNS) -> dict:
    inspector = inspect(db.engine)
    missing_columns: list[str] = []

    for table_name, column_name in required_columns:
        if not inspector.has_table(table_name):
            missing_columns.append(f"{table_name}.{column_name} (table missing)")
            continue

        table_columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name not in table_columns:
            missing_columns.append(f"{table_name}.{column_name}")

    if not missing_columns:
        return {"ok": True, "missing_columns": [], "error": None}

    missing_columns_text = ", ".join(missing_columns)
    return {
        "ok": False,
        "missing_columns": missing_columns,
        "error": (
            "Database schema is missing required columns: "
            f"{missing_columns_text}. Run migrations/20260304_add_load_board_mawb_number.sql "
            "(or Alembic upgrade) before serving code that uses LoadBoard.mawb_number."
        ),
    }


def _check_database_liveness() -> dict:
    try:
        db.session.execute(text("SELECT 1"))
        return {"ok": True, "error": None}
    except Exception as exc:
        return {
            "ok": False,
            "error": (
                "Database liveness check failed while running SELECT 1. "
                "Verify database connectivity/credentials and that the SQL service is reachable. "
                f"Details: {exc}"
            ),
        }


def _check_gcs_bucket_metadata() -> dict:
    bucket_name = os.getenv("GCS_BUCKET_NAME", "").strip()
    try:
        from flask import current_app

        bucket_name = current_app.config.get("GCS_BUCKET_NAME", "").strip() or bucket_name
    except Exception:
        pass

    if not bucket_name:
        return {
            "ok": False,
            "error": (
                "GCS readiness check failed: GCS_BUCKET_NAME is not configured. "
                "Set GCS_BUCKET_NAME to the target bucket and ensure the runtime identity has storage.buckets.get access."
            ),
        }

    try:
        from google.cloud import storage

        client = storage.Client()
        client.get_bucket(bucket_name)
        return {"ok": True, "error": None, "bucket": bucket_name}
    except Exception as exc:
        return {
            "ok": False,
            "error": (
                f"GCS readiness check failed for bucket '{bucket_name}'. "
                "Verify bucket name, ADC/IAM permissions, and GCP project configuration. "
                f"Details: {exc}"
            ),
            "bucket": bucket_name,
        }


def get_readiness_report(required_columns: Iterable[tuple[str, str]] = REQUIRED_COLUMNS) -> dict:
    schema_report = get_required_schema_report(required_columns)
    database_report = _check_database_liveness()
    gcs_report = _check_gcs_bucket_metadata()

    components = {
        "schema": schema_report,
        "database": database_report,
        "gcs": gcs_report,
    }
    ok = all(component.get("ok") for component in components.values())
    errors = {name: component["error"] for name, component in components.items() if not component.get("ok")}

    return {
        "ok": ok,
        "components": components,
        "errors": errors,
    }


def assert_required_schema() -> None:
    report = get_required_schema_report()
    if report["ok"]:
        return
    raise RuntimeError(report["error"])
