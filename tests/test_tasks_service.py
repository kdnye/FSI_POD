import json

import pytest

from app.services.tasks import (
    CouchdropTaskPayload,
    EmailTaskPayload,
    enqueue_couchdrop_task,
    enqueue_email_task,
)


def test_enqueue_email_task_creates_cloud_task_with_blob_names(monkeypatch, app):
    created = {}

    class FakeClient:
        def queue_path(self, project_id, region, queue_name):
            created["queue_path_args"] = (project_id, region, queue_name)
            return "projects/test/locations/us-central1/queues/email-queue"

        def create_task(self, parent, task):
            created["parent"] = parent
            created["task"] = task

    class FakeTasksModule:
        CloudTasksClient = FakeClient

        class HttpMethod:
            POST = "POST"

    monkeypatch.setattr("app.services.tasks._get_tasks_v2_module", lambda: FakeTasksModule)

    with app.app_context():
        enqueue_email_task(
            EmailTaskPayload(
                shipment_id=100,
                action_type="SHIPPER_PICKUP",
                actor_user_id=5,
                driver_email="driver@example.com",
                driver_name="Driver Name",
                hwb_number="HWB100",
                location_name="PHX",
                photo_blob_name="pods/photo-blob.jpg",
                signature_blob_name="pods/signature-blob.jpg",
                shipper_email="shipper@example.com",
                consignee_email="consignee@example.com",
            )
        )

    body = json.loads(created["task"]["http_request"]["body"].decode("utf-8"))

    assert created["queue_path_args"] == ("test-project", "us-central1", "email-queue")
    assert created["parent"] == "projects/test/locations/us-central1/queues/email-queue"
    assert created["task"]["http_request"]["url"] == "https://example.run.app/tasks/api/tasks/send-email"
    assert created["task"]["http_request"]["oidc_token"] == {
        "service_account_email": "tasks-invoker@example.iam.gserviceaccount.com"
    }
    assert body["photo_blob_name"] == "pods/photo-blob.jpg"
    assert body["signature_blob_name"] == "pods/signature-blob.jpg"
    assert body["driver_email"] == "driver@example.com"
    assert body["driver_name"] == "Driver Name"
    assert "photo_url" not in body
    assert "signature_url" not in body


def test_enqueue_email_task_validates_required_fields(app):
    with app.app_context(), pytest.raises(ValueError, match="shipment_id is required"):
        enqueue_email_task(
            EmailTaskPayload(
                shipment_id=None,
                action_type="SHIPPER_PICKUP",
                actor_user_id=5,
            )
        )


def test_enqueue_couchdrop_task_creates_cloud_task(monkeypatch, app):
    created = {}

    class FakeClient:
        def queue_path(self, project_id, region, queue_name):
            created["queue_path_args"] = (project_id, region, queue_name)
            return "projects/test/locations/us-central1/queues/email-queue"

        def create_task(self, parent, task):
            created["parent"] = parent
            created["task"] = task

    class FakeTasksModule:
        CloudTasksClient = FakeClient

        class HttpMethod:
            POST = "POST"

    monkeypatch.setattr("app.services.tasks._get_tasks_v2_module", lambda: FakeTasksModule)

    with app.app_context():
        enqueue_couchdrop_task(
            CouchdropTaskPayload(
                actor_user_id=5,
                original_filename="scan.pdf",
                content_type="application/pdf",
                staged_blob_name="couchdrop_queue/2026-01-01/abc123/scan.pdf",
                remote_path="/Paperwork/Test_User/2026-01-01/scan.pdf",
                idempotency_key="abc123",
            )
        )

    body = json.loads(created["task"]["http_request"]["body"].decode("utf-8"))

    assert created["queue_path_args"] == ("test-project", "us-central1", "email-queue")
    assert created["task"]["http_request"]["url"] == "https://example.run.app/tasks/api/tasks/upload-couchdrop"
    assert body["staged_blob_name"] == "couchdrop_queue/2026-01-01/abc123/scan.pdf"
    assert body["idempotency_key"] == "abc123"
