from datetime import datetime, timezone
from io import BytesIO

from app import db
from models import LoadBoard, PODRecord, Role, User


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
        "hwb_number,shipper,consignee,contact_name,phone,assigned_driver,status\n"
        "HWB-100,Acme,Receiver One,Jane Doe,555-0001,1,Pending\n"
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


def test_non_admin_cannot_upload_load_board_csv(client):
    user_id = _create_user("driver-loads@example.com", role=Role.EMPLOYEE)
    _login(client, user_id)

    csv_payload = (
        "hwb_number,shipper,consignee,contact_name,phone,assigned_driver,status\n"
        "HWB-101,Acme,Receiver Two,John Doe,555-0002,1,Pending\n"
    )

    response = client.post(
        "/load-board/upload-csv",
        data={"load_board_csv": (BytesIO(csv_payload.encode("utf-8")), "loads.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert db.session.get(LoadBoard, "HWB-101") is None


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
