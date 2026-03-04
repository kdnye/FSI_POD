from app import db
from models import User


def test_send_email_task_route_dispatches_postmark(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        calls = []

        def _fake_send(**kwargs):
            calls.append(kwargs)
            return True, "sent"

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)

        response = client.post(
            "/api/tasks/send-email",
            headers={"X-CloudTasks-TaskName": "task-1", "X-Request-Id": "req-1"},
            json={
                "shipment_id": 44,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "hwb_number": "HWB44",
                "location_name": "PHX",
                "shipper_email": "shipper@example.com",
                "consignee_email": "consignee@example.com",
            },
        )

    assert response.status_code == 200
    assert calls[0]["action_type"] == "SHIPPER_PICKUP"
    assert calls[0]["hwb_number"] == "HWB44"


def test_send_email_task_route_returns_retryable_error_when_send_fails(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver2@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        def _fake_send(**_kwargs):
            return False, "missing_recipients"

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)

        response = client.post(
            "/api/tasks/send-email",
            json={
                "shipment_id": 99,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "hwb_number": "HWB99",
            },
        )

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["error"]["hwb_number"] == "HWB99"
    assert payload["error"]["action_type"] == "SHIPPER_PICKUP"
    assert payload["error"]["reason"] == "missing_recipients"


def test_send_email_task_route_validates_payload(client):
    response = client.post("/api/tasks/send-email", json={"shipment_id": 1})

    assert response.status_code == 400
