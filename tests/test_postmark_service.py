from app import db
from app.services.postmark import send_shipment_alert
from models import NotificationSettings, User


class _FakeResponse:
    def raise_for_status(self):
        return None


def test_send_shipment_alert_honors_toggle_and_recipients(app, monkeypatch):
    with app.app_context():
        app.config["POSTMARK_SERVER_TOKEN"] = "token"
        app.config["POSTMARK_FROM_EMAIL"] = "alerts@example.com"

        driver = User(email="driver@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.add(
            NotificationSettings(
                notify_shipper_pickup=True,
                custom_cc_emails="ops@example.com, invalid, qa@example.com",
            )
        )
        db.session.commit()

        captured = {}

        def _fake_post(url, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            captured["timeout"] = timeout
            return _FakeResponse()

        monkeypatch.setattr("app.services.postmark.requests.post", _fake_post)

        sent = send_shipment_alert(
            shipment_id=42,
            action_type="SHIPPER_PICKUP",
            driver_user=driver,
            shipper_email="shipper@example.com",
            consignee_email="consignee@example.com",
        )

        assert sent is True
        assert captured["headers"]["X-Postmark-Server-Token"] == "token"
        assert captured["payload"]["To"] == "driver@example.com"
        assert captured["payload"]["Cc"] == "shipper@example.com,consignee@example.com,ops@example.com,qa@example.com"


def test_send_shipment_alert_returns_early_when_toggle_is_off(app, monkeypatch):
    with app.app_context():
        driver = User(email="driver-off@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.add(NotificationSettings(notify_shipper_pickup=False))
        db.session.commit()

        called = {"value": False}

        def _fake_post(*_args, **_kwargs):
            called["value"] = True
            return _FakeResponse()

        monkeypatch.setattr("app.services.postmark.requests.post", _fake_post)

        sent = send_shipment_alert(shipment_id=10, action_type="SHIPPER_PICKUP", driver_user=driver)

        assert sent is False
        assert called["value"] is False
