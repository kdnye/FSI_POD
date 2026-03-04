from collections.abc import Iterable

from sqlalchemy import inspect

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


def assert_required_schema() -> None:
    report = get_required_schema_report()
    if report["ok"]:
        return
    raise RuntimeError(report["error"])
