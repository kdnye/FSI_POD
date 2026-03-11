import inspect

import models
from app.schema_checks import get_readiness_report, get_required_schema_report


def test_get_required_schema_report_passes_when_column_exists(app):
    with app.app_context():
        report = get_required_schema_report()

    assert report["ok"] is True
    assert report["missing_columns"] == []
    assert report["error"] is None


def test_get_readiness_report_all_components_pass(app, monkeypatch):
    monkeypatch.setattr("app.schema_checks._check_database_liveness", lambda: {"ok": True, "error": None})
    monkeypatch.setattr(
        "app.schema_checks._check_gcs_bucket_metadata",
        lambda: {"ok": True, "error": None, "bucket": "test-bucket"},
    )

    with app.app_context():
        report = get_readiness_report()

    assert report["ok"] is True
    assert report["errors"] == {}
    assert report["components"]["schema"]["ok"] is True
    assert report["components"]["database"]["ok"] is True
    assert report["components"]["gcs"]["ok"] is True


def test_readyz_returns_503_when_schema_fails(client, monkeypatch):
    monkeypatch.setattr(
        "app.schema_checks.get_readiness_report",
        lambda: {
            "ok": False,
            "components": {
                "schema": {
                    "ok": False,
                    "missing_columns": ["load_board.mawb_number"],
                    "error": "Database schema is missing required columns.",
                },
                "database": {"ok": True, "error": None},
                "gcs": {"ok": True, "error": None, "bucket": "test-bucket"},
            },
            "errors": {"schema": "Database schema is missing required columns."},
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "schema" in payload["errors"]


def test_readyz_returns_503_when_database_fails(client, monkeypatch):
    monkeypatch.setattr(
        "app.schema_checks.get_readiness_report",
        lambda: {
            "ok": False,
            "components": {
                "schema": {"ok": True, "missing_columns": [], "error": None},
                "database": {
                    "ok": False,
                    "error": "Database liveness check failed while running SELECT 1.",
                },
                "gcs": {"ok": True, "error": None, "bucket": "test-bucket"},
            },
            "errors": {"database": "Database liveness check failed while running SELECT 1."},
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "database" in payload["errors"]


def test_readyz_returns_503_when_gcs_fails(client, monkeypatch):
    monkeypatch.setattr(
        "app.schema_checks.get_readiness_report",
        lambda: {
            "ok": False,
            "components": {
                "schema": {"ok": True, "missing_columns": [], "error": None},
                "database": {"ok": True, "error": None},
                "gcs": {
                    "ok": False,
                    "error": "GCS readiness check failed for bucket 'missing-bucket'.",
                    "bucket": "missing-bucket",
                },
            },
            "errors": {"gcs": "GCS readiness check failed for bucket 'missing-bucket'."},
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "gcs" in payload["errors"]


def test_all_model_table_names_have_module_level_table_constants():
    module_constants = {
        name: value
        for name, value in vars(models).items()
        if name.endswith("_TABLE") and isinstance(value, str)
    }

    model_table_pairs = []
    for _, candidate in inspect.getmembers(models, inspect.isclass):
        if not issubclass(candidate, models.db.Model) or candidate is models.db.Model:
            continue
        table_name = getattr(candidate, "__tablename__", None)
        if table_name:
            model_table_pairs.append((candidate.__name__, table_name))

    missing_constants = []
    for model_name, table_name in sorted(model_table_pairs, key=lambda item: item[0]):
        expected_constant_name = f"{table_name.upper()}_TABLE"
        if module_constants.get(expected_constant_name) != table_name:
            missing_constants.append(
                {
                    "model": model_name,
                    "table": table_name,
                    "expected_constant": expected_constant_name,
                }
            )

    assert not missing_constants, (
        "Missing/incorrect table constants for SQLAlchemy models. "
        "Expected module-level constants in models.py named <TABLE_NAME_UPPER>_TABLE that match __tablename__. "
        f"Missing mappings: {missing_constants}"
    )
