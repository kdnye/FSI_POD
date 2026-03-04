from app import db
from models import User


def test_send_email_task_route_dispatches_postmark(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        calls = []

        def _fake_send(shipment_id, action_type, driver_user, shipper_email=None, consignee_email=None):
            calls.append((shipment_id, action_type, driver_user.id, shipper_email, consignee_email))
            return True

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)

        response = client.post(
            "/api/tasks/send-email",
            json={
                "shipment_id": 44,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "shipper_email": "shipper@example.com",
                "consignee_email": "consignee@example.com",
            },
        )

    assert response.status_code == 200
    assert calls == [(44, "SHIPPER_PICKUP", driver.id, "shipper@example.com", "consignee@example.com")]


def test_send_email_task_route_validates_payload(client):
    response = client.post("/api/tasks/send-email", json={"shipment_id": 1})

    assert response.status_code == 400
