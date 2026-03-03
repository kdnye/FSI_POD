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




def test_administrator_can_upload_load_board_csv(client):
    admin_id = _create_user("administrator-loads@example.com", role=Role.ADMINISTRATOR)
    _login(client, admin_id)

    csv_payload = (
        "hwb_number,shipper,consignee,contact_name,phone,assigned_driver,status\n"
        "HWB-102,Acme,Receiver Three,Alex Doe,555-0004,1,Pending\n"
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
        "hwb_number,shipper,consignee,contact_name,phone,assigned_driver,status\n"
        "HWB-103,Acme,Receiver Four,Casey Doe,555-0005,1,Pending\n"
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
                phone="555-3000",
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
