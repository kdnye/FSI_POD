from app import db
from models import User


def test_send_email_task_route_accepts_trusted_task_request(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        calls = []

        def _fake_send(**kwargs):
            calls.append(kwargs)
            return True, "sent"

        generated_for = []

        def _fake_signed_url(blob_name):
            generated_for.append(blob_name)
            return f"https://signed/{blob_name}"

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
        monkeypatch.setattr("app.blueprints.tasks.routes.generate_signed_url", _fake_signed_url)
        observed = {}

        def _fake_verify(token, audience):
            observed["audience"] = audience
            return {
                "iss": "https://accounts.google.com",
                "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
                "email_verified": True,
                "aud": audience,
            }

        monkeypatch.setattr("app.blueprints.tasks.routes._verify_task_oidc_token", _fake_verify)

        response = client.post(
            "/tasks/api/tasks/send-email",
            headers={
                "X-CloudTasks-TaskName": "task-1",
                "X-CloudTasks-QueueName": app.config["TASKS_EXPECTED_QUEUE_NAME"],
                "X-Request-Id": "req-1",
                "Authorization": "Bearer valid-token",
            },
            json={
                "shipment_id": 44,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "driver_email": "driver@example.com",
                "driver_name": "Driver One",
                "hwb_number": "HWB44",
                "location_name": "PHX",
                "photo_blob_name": "pods/photo.jpg",
                "signature_blob_name": "pods/signature.jpg",
                "shipper_email": "shipper@example.com",
                "consignee_email": "consignee@example.com",
            },
        )

    assert response.status_code == 200
    assert calls[0]["action_type"] == "SHIPPER_PICKUP"
    assert calls[0]["hwb_number"] == "HWB44"
    assert calls[0]["driver_email"] == "driver@example.com"
    assert calls[0]["driver_name"] == "Driver One"
    assert calls[0]["photo_url"] == "https://signed/pods/photo.jpg"
    assert calls[0]["signature_url"] == "https://signed/pods/signature.jpg"
    assert generated_for == ["pods/photo.jpg", "pods/signature.jpg"]
    assert observed["audience"] == "https://example.run.app/tasks/api/tasks/send-email"


def test_send_email_task_route_passes_none_urls_when_blob_names_absent(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver4@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        calls = []
        generated_for = []

        def _fake_send(**kwargs):
            calls.append(kwargs)
            return True, "sent"

        def _fake_signed_url(blob_name):
            generated_for.append(blob_name)
            return f"https://signed/{blob_name}"

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
        monkeypatch.setattr("app.blueprints.tasks.routes.generate_signed_url", _fake_signed_url)
        monkeypatch.setattr(
            "app.blueprints.tasks.routes._verify_task_oidc_token",
            lambda token, audience: {
                "iss": "https://accounts.google.com",
                "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
                "email_verified": True,
                "aud": audience,
            },
        )

        response = client.post(
            "/tasks/api/tasks/send-email",
            headers={
                "X-CloudTasks-TaskName": "task-no-media",
                "Authorization": "Bearer valid-token",
            },
            json={
                "shipment_id": 45,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "driver_email": "driver4@example.com",
                "driver_name": "Driver Four",
                "hwb_number": "HWB45",
            },
        )

    assert response.status_code == 200
    assert calls[0]["photo_url"] is None
    assert calls[0]["signature_url"] is None
    assert calls[0]["driver_email"] == "driver4@example.com"
    assert calls[0]["driver_name"] == "Driver Four"
    assert generated_for == []


def test_send_email_task_route_rejects_untrusted_direct_post(client, app):
    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-2",
        },
        json={"shipment_id": 1, "action_type": "SHIPPER_PICKUP", "actor_user_id": 1},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Missing Bearer token for task request."


def test_send_email_task_route_rejects_missing_cloud_tasks_metadata(client, app):
    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={"Authorization": "Bearer valid-token"},
        json={"shipment_id": 1, "action_type": "SHIPPER_PICKUP", "actor_user_id": 1},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Missing required Cloud Tasks task header."


def test_send_email_task_route_rejects_invalid_token(client, app, monkeypatch):
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: (_ for _ in ()).throw(ValueError("bad token")),
    )

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-invalid-token",
            "Authorization": "Bearer invalid-token",
        },
        json={"shipment_id": 1, "action_type": "SHIPPER_PICKUP", "actor_user_id": 1},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Invalid task authentication token."


def test_send_email_task_route_returns_retryable_error_when_send_fails(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver2@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()

        def _fake_send(**_kwargs):
            return False, "missing_recipients"

        monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
        monkeypatch.setattr("app.blueprints.tasks.routes.generate_signed_url", lambda blob_name: f"https://signed/{blob_name}")
        monkeypatch.setattr(
            "app.blueprints.tasks.routes._verify_task_oidc_token",
            lambda token, audience: {
                "iss": "https://accounts.google.com",
                "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
                "email_verified": True,
                "aud": audience,
            },
        )

        response = client.post(
            "/tasks/api/tasks/send-email",
            headers={
                "X-CloudTasks-TaskName": "task-3",
                "Authorization": "Bearer valid-token",
            },
            json={
                "shipment_id": 99,
                "action_type": "SHIPPER_PICKUP",
                "actor_user_id": driver.id,
                "hwb_number": "HWB99",
                "photo_blob_name": "pods/photo.jpg",
            },
        )

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["error"]["hwb_number"] == "HWB99"
    assert payload["error"]["action_type"] == "SHIPPER_PICKUP"
    assert payload["error"]["reason"] == "missing_recipients"


def test_send_email_task_route_returns_retryable_error_when_url_generation_fails(client, app, monkeypatch):
    with app.app_context():
        driver = User(email="driver3@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.commit()
        driver_id = driver.id

    monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", lambda **_kwargs: (True, "sent"))
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
            "aud": audience,
        },
    )

    def _broken_signed_url(_blob_name):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.blueprints.tasks.routes.generate_signed_url", _broken_signed_url)

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-3b",
            "Authorization": "Bearer valid-token",
        },
        json={
            "shipment_id": 100,
            "action_type": "SHIPPER_PICKUP",
            "actor_user_id": driver_id,
            "hwb_number": "HWB100",
            "photo_blob_name": "pods/photo.jpg",
        },
    )

    assert response.status_code == 500
    assert response.get_json()["error"]["reason"] == "signed_url_generation_failed"


def test_send_email_task_route_validates_payload_after_auth(client, app):
    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-4",
            "Authorization": "Bearer missing",
        },
        json={"shipment_id": 1},
    )

    assert response.status_code == 403


def test_send_email_task_route_rejects_non_integer_actor_user_id(client, app, monkeypatch):
    called = False

    def _fake_send(**_kwargs):
        nonlocal called
        called = True
        return True, "sent"

    monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
            "aud": audience,
        },
    )

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-5",
            "X-Request-Id": "req-5",
            "Authorization": "Bearer valid-token",
        },
        json={
            "shipment_id": 1,
            "action_type": "SHIPPER_PICKUP",
            "actor_user_id": "abc",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid actor_user_id for email task."
    assert called is False


def test_send_email_task_route_rejects_unknown_action_type(client, app, monkeypatch):
    called = False

    def _fake_send(**_kwargs):
        nonlocal called
        called = True
        return True, "sent"

    monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
            "aud": audience,
        },
    )

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-6",
            "X-Request-Id": "req-6",
            "Authorization": "Bearer valid-token",
        },
        json={
            "shipment_id": 1,
            "action_type": "NOT_A_REAL_ACTION",
            "actor_user_id": 1,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid action_type for email task."
    assert called is False


def test_send_email_task_route_allows_missing_driver_record_when_payload_includes_driver_fields(client, app, monkeypatch):
    calls = []

    def _fake_send(**kwargs):
        calls.append(kwargs)
        return True, "sent"

    monkeypatch.setattr("app.blueprints.tasks.routes.send_shipment_alert", _fake_send)
    monkeypatch.setattr("app.blueprints.tasks.routes.generate_signed_url", lambda blob_name: f"https://signed/{blob_name}")
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
            "aud": audience,
        },
    )

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-no-driver-record",
            "Authorization": "Bearer valid-token",
        },
        json={
            "shipment_id": 1,
            "action_type": "SHIPPER_PICKUP",
            "actor_user_id": 99999,
            "driver_email": "driver-missing@example.com",
            "driver_name": "Missing Driver",
        },
    )

    assert response.status_code == 200
    assert calls[0]["driver_email"] == "driver-missing@example.com"
    assert calls[0]["driver_name"] == "Missing Driver"


def test_send_email_task_route_rejects_missing_required_fields(client, app):
    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-7",
            "X-Request-Id": "req-7",
            "Authorization": "Bearer valid-token",
        },
        json={"shipment_id": 1, "actor_user_id": 1},
    )

    assert response.status_code == 403


def test_send_email_task_route_rejects_missing_required_fields_after_auth(client, app, monkeypatch):
    monkeypatch.setattr(
        "app.blueprints.tasks.routes._verify_task_oidc_token",
        lambda token, audience: {
            "iss": "https://accounts.google.com",
            "email": app.config["TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL"],
            "email_verified": True,
            "aud": audience,
        },
    )

    response = client.post(
        "/tasks/api/tasks/send-email",
        headers={
            "X-CloudTasks-TaskName": "task-7",
            "X-Request-Id": "req-7",
            "Authorization": "Bearer valid-token",
        },
        json={"shipment_id": 1, "actor_user_id": 1},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing required task payload fields."
