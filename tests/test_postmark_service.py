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

        sent, reason = send_shipment_alert(
            action_type="SHIPPER_PICKUP",
            hwb_number="HWB123",
            location_name="PHX",
            driver_email=driver.email,
            driver_name="Driver One",
            photo_url=None,
            signature_url=None,
            shipper_email="shipper@example.com",
            consignee_email="consignee@example.com",
            timestamp="2025-01-01 09:00 AM MST",
        )

        assert sent is True
        assert reason == "sent"
        assert captured["headers"]["X-Postmark-Server-Token"] == "token"
        assert captured["payload"]["To"] == "driver@example.com,shipper@example.com,consignee@example.com,ops@example.com,qa@example.com"


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

        sent, reason = send_shipment_alert(
            action_type="SHIPPER_PICKUP",
            hwb_number="HWB999",
            location_name="PHX",
            driver_email=driver.email,
            driver_name="Driver Off",
            photo_url=None,
            signature_url=None,
            shipper_email=None,
            consignee_email=None,
            timestamp="2025-01-01 09:00 AM MST",
        )

        assert sent is False
        assert reason == "disabled_settings"
        assert called["value"] is False


def test_send_shipment_alert_signs_media_for_consignee_drop(app, monkeypatch):
    with app.app_context():
        app.config["POSTMARK_SERVER_TOKEN"] = "token"
        app.config["POSTMARK_FROM_EMAIL"] = "alerts@example.com"

        db.session.add(NotificationSettings(notify_consignee_drop=True))
        db.session.commit()

        captured = {}

        def _fake_post(url, headers, json, timeout):
            captured["payload"] = json
            return _FakeResponse()

        def _fake_media_url(blob_name, public_base_url=None):
            if blob_name == "pod/photo.png":
                return "https://signed.example.com/photo"
            if blob_name == "pod/signature.png":
                return "https://signed.example.com/signature"
            return blob_name

        monkeypatch.setattr("app.services.postmark.requests.post", _fake_post)
        monkeypatch.setattr("app.services.postmark.build_media_access_url", _fake_media_url)

        sent, reason = send_shipment_alert(
            action_type="CONSIGNEE_DROP",
            hwb_number="HWB124",
            location_name="PHX",
            driver_email="driver@example.com",
            driver_name="Driver One",
            photo_url="pod/photo.png",
            signature_url="pod/signature.png",
            shipper_email="shipper@example.com",
            consignee_email="consignee@example.com",
            timestamp="2025-01-01 09:00 AM MST",
        )

        assert sent is True
        assert reason == "sent"
        assert captured["payload"]["TemplateModel"]["photo_url"] == "https://signed.example.com/photo"
        assert captured["payload"]["TemplateModel"]["signature_url"] == "https://signed.example.com/signature"
