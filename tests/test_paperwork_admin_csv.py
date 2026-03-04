from datetime import datetime, timezone
from io import BytesIO

from app import db
from models import LoadBoard, PODRecord, Role, Shipment, ShipmentGroup, ShipmentLeg, User


def _create_user(email: str, role: Role, employee_approved: bool = True) -> int:
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


def test_admin_can_upload_load_board_csv(client):
    admin_id = _create_user("admin-loads@example.com", role=Role.ADMIN)
    _login(client, admin_id)

    csv_payload = (
        "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,status\n"
        "MAWB-100,HWB-100,Acme,Receiver One,PHX,LAX,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    entry = db.session.get(LoadBoard, "HWB-100")
    assert entry is not None
    assert entry.shipper == "Acme"
    assert entry.status == "Pending"




def test_administrator_can_upload_load_board_csv(client):
    admin_id = _create_user("administrator-loads@example.com", role=Role.ADMINISTRATOR)
    _login(client, admin_id)

    csv_payload = (
        "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,status\n"
        "MAWB-102,HWB-102,Acme,Receiver Three,PHX,LAX,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    entry = db.session.get(LoadBoard, "HWB-102")
    assert entry is not None
    assert entry.shipper == "Acme"

def test_non_admin_cannot_upload_load_board_csv(client):
    user_id = _create_user("driver-loads@example.com", role=Role.EMPLOYEE)
    _login(client, user_id)

    csv_payload = (
        "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,status\n"
        "MAWB-101,HWB-101,Acme,Receiver Two,PHX,LAX,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert db.session.get(LoadBoard, "HWB-101") is None




def test_ops_can_upload_load_board_csv(client):
    ops_user = User(
        email="ops-loads@example.com",
        password_hash="test-hash",
        role=Role.EMPLOYEE,
        employee_approved=True,
        is_active=True,
        is_ops=True,
    )
    db.session.add(ops_user)
    db.session.commit()
    _login(client, ops_user.id)

    csv_payload = (
        "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,status\n"
        "MAWB-103,HWB-103,Acme,Receiver Four,PHX,LAX,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    entry = db.session.get(LoadBoard, "HWB-103")
    assert entry is not None
    assert entry.shipper == "Acme"


def test_non_ops_user_sees_my_active_loads_only(client):
    driver_id = _create_user("driver-board@example.com", role=Role.EMPLOYEE)
    other_driver_id = _create_user("other-driver-board@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add_all(
        [
            LoadBoard(
                hwb_number="HWB-ME",
                shipper="Acme",
                consignee="Receiver Me",
                contact_name="Driver One",
                phone="555-1000",
                assigned_driver=driver_id,
                status="Pending",
            ),
            LoadBoard(
                hwb_number="HWB-NOT-ME",
                shipper="Acme",
                consignee="Receiver Other",
                contact_name="Driver Two",
                phone="555-2000",
                assigned_driver=other_driver_id,
                status="Pending",
            ),
        ]
    )
    db.session.commit()

    response = client.get("/load-board")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "My Active Loads" in body
    assert "HWB-ME" in body
    assert "HWB-NOT-ME" not in body
    assert "Ops/Admin CSV Upload" not in body


def test_ops_user_sees_full_active_load_board(client):
    ops_user = User(
        email="ops-board@example.com",
        password_hash="test-hash",
        role=Role.EMPLOYEE,
        employee_approved=True,
        is_active=True,
        is_ops=True,
    )
    db.session.add(ops_user)
    db.session.commit()
    _login(client, ops_user.id)

    db.session.add_all(
        [
            LoadBoard(
                hwb_number="HWB-OPS-1",
                shipper="Acme",
                consignee="Receiver One",
                contact_name="Contact One",
                phone="555-3000-should-not-display",
                assigned_driver=ops_user.id,
                status="Pending",
            ),
            LoadBoard(
                hwb_number="HWB-OPS-2",
                shipper="Acme",
                consignee="Receiver Two",
                contact_name="Contact Two",
                phone="555-4000",
                assigned_driver=999,
                status="Pending",
            ),
        ]
    )
    db.session.commit()

    response = client.get("/load-board")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Active Load Board" in body
    assert "HWB-OPS-1" in body
    assert "HWB-OPS-2" in body
    assert "Ops/Admin CSV Upload" in body
    assert "Assigned Driver (Current Leg)" in body
    assert "ops-board@example.com" in body
    assert "555-3000-should-not-display" not in body

def test_active_load_board_shows_pod_details_only_for_delivered_loads(client):
    driver_id = _create_user("driver-pod-details@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-POD-DETAIL",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-7777",
            assigned_driver=driver_id,
            status="Delivered",
        )
    )
    db.session.add(
        PODRecord(
            hwb_number="HWB-POD-DETAIL",
            delivery_photo="https://example.com/photo.png",
            signature_image="https://example.com/signature.png",
            recipient_name="Printed Receiver",
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
            driver_id=driver_id,
            action_type="Delivery",
        )
    )
    db.session.commit()

    response = client.get("/load-board")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "View photo" in body
    assert "View signature" in body
    assert "Printed Receiver" in body


def test_active_load_board_hides_pod_details_until_completed(client):
    driver_id = _create_user("driver-pod-pending@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-POD-HIDDEN",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-8888",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.add(
        PODRecord(
            hwb_number="HWB-POD-HIDDEN",
            delivery_photo="https://example.com/photo-hidden.png",
            signature_image="https://example.com/signature-hidden.png",
            recipient_name="Should Stay Hidden",
            timestamp=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
            driver_id=driver_id,
            action_type="Delivery",
        )
    )
    db.session.commit()

    response = client.get("/load-board")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Should Stay Hidden" not in body
    assert "photo-hidden.png" not in body
    assert "signature-hidden.png" not in body


def test_admin_can_export_full_and_ranged_pod_history_csv(client):
    admin_id = _create_user("admin-export@example.com", role=Role.ADMIN)
    _login(client, admin_id)

    db.session.add(
        PODRecord(
            hwb_number="HWB-200",
            delivery_photo="gs://pod/photo.jpg",
            signature_image="gs://pod/signature.jpg",
            recipient_name="Receiver",
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
            driver_id=admin_id,
            action_type="Delivery",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Jane",
            phone="555-0003",
        )
    )
    db.session.commit()

    full_response = client.get("/pod/history/export")
    assert full_response.status_code == 200
    assert "text/csv" in full_response.content_type
    assert "HWB-200" in full_response.get_data(as_text=True)

    ranged_response = client.get("/pod/history/export?start=2024-01-01T00:00&end=2024-01-31T23:59")
    assert ranged_response.status_code == 200
    assert "HWB-200" in ranged_response.get_data(as_text=True)


def test_non_admin_cannot_export_pod_history_csv(client):
    user_id = _create_user("driver-export@example.com", role=Role.EMPLOYEE)
    _login(client, user_id)

    response = client.get("/pod/history/export", follow_redirects=False)

    assert response.status_code == 302


def test_ops_user_sees_full_pod_history_and_can_export_global_csv(client):
    ops_user = User(
        email="ops-history@example.com",
        password_hash="test-hash",
        role=Role.EMPLOYEE,
        employee_approved=True,
        is_active=True,
        is_ops=True,
    )
    other_user = User(
        email="driver-history-other@example.com",
        password_hash="test-hash",
        role=Role.EMPLOYEE,
        employee_approved=True,
        is_active=True,
    )
    db.session.add_all([ops_user, other_user])
    db.session.commit()
    _login(client, ops_user.id)

    db.session.add_all(
        [
            PODRecord(
                hwb_number="HWB-OPS-ME",
                delivery_photo="gs://pod/photo-ops.jpg",
                signature_image="gs://pod/signature-ops.jpg",
                recipient_name="Ops Receiver",
                timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
                driver_id=ops_user.id,
                action_type="Delivery",
                shipper="Acme",
                consignee="Receiver Ops",
                contact_name="Ops Contact",
                phone="555-0100",
            ),
            PODRecord(
                hwb_number="HWB-OPS-OTHER",
                delivery_photo="gs://pod/photo-other.jpg",
                signature_image="gs://pod/signature-other.jpg",
                recipient_name="Other Receiver",
                timestamp=datetime(2024, 1, 15, 13, 0, tzinfo=timezone.utc),
                driver_id=other_user.id,
                action_type="Delivery",
                shipper="Acme",
                consignee="Receiver Other",
                contact_name="Other Contact",
                phone="555-0101",
            ),
        ]
    )
    db.session.commit()

    history_response = client.get("/pod/history")
    history_body = history_response.get_data(as_text=True)

    assert history_response.status_code == 200
    assert "POD History" in history_body
    assert "My POD History" not in history_body
    assert "Ops/Admin CSV Exports" in history_body
    assert "HWB-OPS-ME" in history_body
    assert "HWB-OPS-OTHER" in history_body

    export_response = client.get("/pod/history/export")
    export_body = export_response.get_data(as_text=True)

    assert export_response.status_code == 200
    assert "text/csv" in export_response.content_type
    assert "HWB-OPS-ME" in export_body
    assert "HWB-OPS-OTHER" in export_body


def test_non_ops_user_sees_only_my_pod_history_and_cannot_export_global_csv(client):
    user_id = _create_user("driver-history@example.com", role=Role.EMPLOYEE)
    other_user_id = _create_user("driver-history-other-two@example.com", role=Role.EMPLOYEE)
    _login(client, user_id)

    db.session.add_all(
        [
            PODRecord(
                hwb_number="HWB-MY-HISTORY",
                delivery_photo="gs://pod/photo-my.jpg",
                signature_image="gs://pod/signature-my.jpg",
                recipient_name="My Receiver",
                timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
                driver_id=user_id,
                action_type="Delivery",
                shipper="Acme",
                consignee="Receiver Mine",
                contact_name="My Contact",
                phone="555-0200",
            ),
            PODRecord(
                hwb_number="HWB-OTHER-HISTORY",
                delivery_photo="gs://pod/photo-not-my.jpg",
                signature_image="gs://pod/signature-not-my.jpg",
                recipient_name="Other Receiver",
                timestamp=datetime(2024, 1, 15, 13, 0, tzinfo=timezone.utc),
                driver_id=other_user_id,
                action_type="Delivery",
                shipper="Acme",
                consignee="Receiver Other",
                contact_name="Other Contact",
                phone="555-0201",
            ),
        ]
    )
    db.session.commit()

    history_response = client.get("/pod/history")
    history_body = history_response.get_data(as_text=True)

    assert history_response.status_code == 200
    assert "My POD History" in history_body
    assert "Showing only your POD events" in history_body
    assert "Ops/Admin CSV Exports" not in history_body
    assert "HWB-MY-HISTORY" in history_body
    assert "HWB-OTHER-HISTORY" not in history_body

    export_response = client.get("/pod/history/export", follow_redirects=False)
    assert export_response.status_code == 302




def test_scan_hwb_assigned_load_has_no_warning(client):
    driver_id = _create_user("scan-assigned-driver@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-SCAN-ASSIGNED",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-7777",
            assigned_driver=driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    response = client.post("/pod/scan", json={"hwb_number": "HWB-SCAN-ASSIGNED"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["is_assigned_to_current_user"] is True
    assert payload["warning_required"] is False

def test_scan_hwb_includes_assignment_and_warning_flags(client):
    driver_id = _create_user("scan-driver@example.com", role=Role.EMPLOYEE)
    other_driver_id = _create_user("scan-other@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-SCAN-WARN",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-8888",
            assigned_driver=other_driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    response = client.post("/pod/scan", json={"hwb_number": "HWB-SCAN-WARN"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["mode"] == "enhanced"
    assert payload["user_has_full_board_rights"] is False
    assert payload["is_assigned_to_current_user"] is False
    assert payload["warning_required"] is True
    assert payload["warning_message"]


def test_off_sheet_completion_without_confirmation_fails(client, monkeypatch):
    driver_id = _create_user("offsheet-driver@example.com", role=Role.EMPLOYEE)
    other_driver_id = _create_user("offsheet-other@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-OFF-NO-CONFIRM",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-1111",
            assigned_driver=other_driver_id,
            status="Pending",
        )
    )
    db.session.commit()

    monkeypatch.setattr("app.services.gcs.GCSService.upload_file", lambda *_args, **_kwargs: "gs://test/path")

    response = client.post(
        "/pod/event",
        data={
            "hwb_number": "HWB-OFF-NO-CONFIRM",
            "action_type": "Delivery",
            "recipient_name": "Receiver",
            "signature_base64": "data:image/png;base64,aGVsbG8=",
            "off_sheet_confirmed": "false",
            "pod_photo": (BytesIO(b"pod-image"), "pod.jpg"),
        },
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert "requires confirmation" in response.get_json()["error"]

    load = db.session.get(LoadBoard, "HWB-OFF-NO-CONFIRM")
    assert load.assigned_driver == other_driver_id
    assert load.status == "Pending"
    assert PODRecord.query.filter_by(hwb_number="HWB-OFF-NO-CONFIRM").count() == 0


def test_off_sheet_completion_with_confirmation_reassigns_and_completes(client, monkeypatch):
    driver_id = _create_user("offsheet-ok-driver@example.com", role=Role.EMPLOYEE)
    _create_user("offsheet-ok-other@example.com", role=Role.EMPLOYEE)
    _login(client, driver_id)

    db.session.add(
        LoadBoard(
            hwb_number="HWB-OFF-CONFIRM",
            shipper="Acme",
            consignee="Receiver",
            contact_name="Contact",
            phone="555-2222",
            assigned_driver=None,
            status="Pending",
        )
    )
    db.session.commit()

    monkeypatch.setattr("app.services.gcs.GCSService.upload_file", lambda *_args, **_kwargs: "gs://test/path")

    response = client.post(
        "/pod/event",
        data={
            "hwb_number": "HWB-OFF-CONFIRM",
            "action_type": "Delivery",
            "recipient_name": "Receiver",
            "signature_base64": "data:image/png;base64,aGVsbG8=",
            "off_sheet_confirmed": "true",
            "reassignment_note": "Driver picked up off-sheet.",
            "pod_photo": (BytesIO(b"pod-image"), "pod.jpg"),
        },
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True

    load = db.session.get(LoadBoard, "HWB-OFF-CONFIRM")
    assert load.assigned_driver == driver_id
    assert load.status == "Delivered"

    pod_record = PODRecord.query.filter_by(hwb_number="HWB-OFF-CONFIRM").one()
    assert pod_record.off_sheet_confirmed is True
    assert "Off-sheet confirmation accepted" in (pod_record.reassignment_note or "")
    assert "Driver picked up off-sheet." in (pod_record.reassignment_note or "")


def test_upload_load_board_csv_rejects_invalid_iata_row_and_reports_feedback(client):
    admin_id = _create_user("admin-invalid-iata@example.com", role=Role.ADMIN)
    _login(client, admin_id)

    csv_payload = (
        "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,status\n"
        "MAWB-200,HWB-200,Acme,Receiver One,PH,LAX,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "origin_airport must be a non-empty 3-letter uppercase IATA code" in body
    assert db.session.get(LoadBoard, "HWB-200") is None


def test_upload_load_board_csv_creates_group_shipment_and_default_legs(client, app):
    admin_id = _create_user("admin-shipment-import@example.com", role=Role.ADMIN)
    _login(client, admin_id)
    app.config["LOAD_BOARD_USE_SHIPMENTS"] = True

    try:
        csv_payload = (
            "mawb_number,hwb_number,shipper_address,consignee_address,origin_airport,destination_airport,first_mile_driver_id,last_mile_driver_id,status\n"
            "MAWB-300,HWB-300,Acme,Receiver One,PHX,LAX,11,22,Pending\n"
        )

        response = client.post(
            "/load-board/upload-csv",
            data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        assert response.status_code == 302
        group = ShipmentGroup.query.filter_by(mawb_number="MAWB-300").first()
        shipment = Shipment.query.filter_by(hwb_number="HWB-300").first()
        assert group is not None
        assert shipment is not None
        assert shipment.shipment_group_id == group.id

        legs = ShipmentLeg.query.filter_by(shipment_id=shipment.id).order_by(ShipmentLeg.leg_sequence.asc()).all()
        assert len(legs) == 3
        assert legs[0].assigned_driver_id == 11
        assert legs[2].assigned_driver_id == 22
    finally:
        app.config["LOAD_BOARD_USE_SHIPMENTS"] = False
