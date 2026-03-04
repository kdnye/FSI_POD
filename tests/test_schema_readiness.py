from app.schema_checks import get_required_schema_report


def test_get_required_schema_report_passes_when_column_exists(app):
    with app.app_context():
        report = get_required_schema_report()

    assert report["ok"] is True
    assert report["missing_columns"] == []
    assert report["error"] is None


def test_readyz_returns_503_with_actionable_error_when_schema_missing(client, monkeypatch):
    monkeypatch.setattr(
        "app.schema_checks.get_required_schema_report",
        lambda: {
            "ok": False,
            "missing_columns": ["load_board.mawb_number"],
            "error": "Database schema is missing required columns: load_board.mawb_number. Run migrations/20260304_add_load_board_mawb_number.sql.",
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "load_board.mawb_number" in payload["missing_columns"]
    assert "20260304_add_load_board_mawb_number.sql" in payload["error"]
