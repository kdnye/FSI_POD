import logging

from app import DEFAULT_TRACE_ID


def _request_completed_records(caplog):
    return [record for record in caplog.records if record.getMessage() == "request.completed"]


def test_trace_header_present_includes_trace_id(app, client, caplog):
    caplog.set_level(logging.INFO, logger=app.logger.name)

    response = client.get(
        "/",
        headers={"X-Cloud-Trace-Context": "105445aa7843bc8bf206b120001000/1;o=1"},
    )

    assert response.status_code == 302
    records = _request_completed_records(caplog)
    assert records
    assert records[-1].trace_id == "105445aa7843bc8bf206b120001000"


def test_trace_header_absent_uses_default_trace_id(app, client, caplog):
    caplog.set_level(logging.INFO, logger=app.logger.name)

    response = client.get("/")

    assert response.status_code == 302
    records = _request_completed_records(caplog)
    assert records
    assert records[-1].trace_id == DEFAULT_TRACE_ID
