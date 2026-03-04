import json

import pytest

from app.services.tasks import EmailTaskPayload, enqueue_email_task


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
    assert created["task"]["http_request"]["url"] == "https://example.run.app/api/tasks/send-email"
    assert created["task"]["http_request"]["oidc_token"] == {
        "service_account_email": "tasks-invoker@example.iam.gserviceaccount.com"
    }
    assert body["photo_blob_name"] == "pods/photo-blob.jpg"
    assert body["signature_blob_name"] == "pods/signature-blob.jpg"
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
