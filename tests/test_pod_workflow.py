from io import BytesIO

import pytest
from sqlalchemy import inspect, text

from app import db
from models import LoadBoard, PODRecord, Role, User


def _create_user(email: str, role: Role = Role.EMPLOYEE, employee_approved: bool = True) -> int:
    user = User(
        email=email,
        password_hash="test-hash",
        role=role,
        employee_approved=employee_approved,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id


def _pod_form_payload(hwb_number: str, **overrides):
    payload = {
        "hwb_number": hwb_number,
        "action_type": "Delivery",
        "recipient_name": "Dock Receiver",
        "signature_base64": "data:image/png;base64,aGVsbG8=",
        "pod_photo": (BytesIO(b"pod-image"), "pod.jpg"),
    }
    payload.update(overrides)
    return payload


def test_submit_pod_matched_path_inherits_load_board_fields_and_marks_delivered(client, monkeypatch):
    driver_id = _create_user("pod-matched@example.com")
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-MATCH-001",
            shipper="Acme Shipper",
            consignee="Matched Consignee",
            contact_name="Matched Contact",
            phone="555-1111",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    monkeypatch.setattr("app.services.gcs.GCSService.upload_file", lambda *_args, **_kwargs: "gs://test/path")

    response = client.post(
        "/pod/event",
        data=_pod_form_payload("HWB-MATCH-001"),
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200

    pod_record = PODRecord.query.filter_by(hwb_number="HWB-MATCH-001").one()
    assert pod_record.shipper == "Acme Shipper"
    assert pod_record.consignee == "Matched Consignee"
    assert pod_record.contact_name == "Matched Contact"
    assert pod_record.phone == "555-1111"

    load = db.session.get(LoadBoard, "HWB-MATCH-001")
    assert load.status.upper() == "DELIVERED"


def test_submit_pod_manual_path_persists_record_without_mutating_load_board(client, monkeypatch):
    driver_id = _create_user("pod-manual@example.com")
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-EXISTING-UNCHANGED",
            shipper="Existing Shipper",
            consignee="Existing Consignee",
            contact_name="Existing Contact",
            phone="555-2222",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    before_count = LoadBoard.query.count()
    monkeypatch.setattr("app.services.gcs.GCSService.upload_file", lambda *_args, **_kwargs: "gs://test/path")

    response = client.post(
        "/pod/event",
        data=_pod_form_payload(
            "HWB-MANUAL-404",
            shipper="Manual Shipper",
            consignee="Manual Consignee",
            contact_name="Manual Contact",
            phone="555-3333",
        ),
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200

    pod_record = PODRecord.query.filter_by(hwb_number="HWB-MANUAL-404").one()
    assert pod_record.shipper == "Manual Shipper"
    assert pod_record.consignee == "Manual Consignee"
    assert pod_record.contact_name == "Manual Contact"
    assert pod_record.phone == "555-3333"

    assert LoadBoard.query.count() == before_count
    unchanged = db.session.get(LoadBoard, "HWB-EXISTING-UNCHANGED")
    assert unchanged.status == "Pending"


def test_pod_scan_returns_enhanced_for_match_and_base_for_unmatched(client):
    driver_id = _create_user("pod-scan@example.com")
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-SCAN-HIT",
            shipper="Scan Shipper",
            consignee="Scan Consignee",
            contact_name="Scan Contact",
            phone="555-4444",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    matched_response = client.post("/pod/scan", json={"hwb_number": "HWB-SCAN-HIT"})
    unmatched_response = client.post("/pod/scan", json={"hwb_number": "HWB-SCAN-MISS"})

    assert matched_response.status_code == 200
    assert matched_response.get_json()["mode"] == "enhanced"

    assert unmatched_response.status_code == 200
    assert unmatched_response.get_json()["mode"] == "base"


def test_pod_history_includes_links_to_photo_and_signature(client):
    driver_id = _create_user("pod-history-links@example.com")
    _login(client, driver_id)

    db.session.add(
        PODRecord(
            hwb_number="HWB-HISTORY-LINKS",
            delivery_photo="https://storage.googleapis.com/bucket/pod.jpg",
            signature_image="https://storage.googleapis.com/bucket/signature.png",
            recipient_name="History Receiver",
            driver_id=driver_id,
            action_type="Delivery",
        )
    )
    db.session.commit()

    response = client.get("/pod/history")

    assert response.status_code == 200
    assert b'href="https://storage.googleapis.com/bucket/pod.jpg"' in response.data
    assert b'href="https://storage.googleapis.com/bucket/signature.png"' in response.data


def test_shipping_reconciliation_view_classifies_manual_vs_system_match_when_available(app):
    inspector = inspect(db.engine)
    if "v_shipping_reconciliation" not in inspector.get_view_names():
        pytest.skip("v_shipping_reconciliation view is not available in this test database")

    driver_id = _create_user("pod-recon@example.com")
    db.session.add(
        LoadBoard(
            hwb_number="HWB-RECON-MATCH",
            shipper="Recon Shipper",
            consignee="Recon Consignee",
            contact_name="Recon Contact",
            phone="555-5555",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.add_all(
        [
            PODRecord(
                hwb_number="HWB-RECON-MATCH",
                delivery_photo="gs://test/match-photo",
                signature_image="gs://test/match-signature",
                recipient_name="Matched Receiver",
                driver_id=driver_id,
                action_type="Delivery",
            ),
            PODRecord(
                hwb_number="HWB-RECON-MANUAL",
                delivery_photo="gs://test/manual-photo",
                signature_image="gs://test/manual-signature",
                recipient_name="Manual Receiver",
                driver_id=driver_id,
                action_type="Delivery",
            ),
        ]
    )
    db.session.commit()

    result = db.session.execute(
        text(
            """
            SELECT hwb_number, match_status
            FROM v_shipping_reconciliation
            WHERE hwb_number IN ('HWB-RECON-MATCH', 'HWB-RECON-MANUAL')
            """
        )
    ).all()

    statuses = {row.hwb_number: row.match_status for row in result}
    assert statuses["HWB-RECON-MATCH"] == "System Match"
    assert statuses["HWB-RECON-MANUAL"] == "Manual POD"
