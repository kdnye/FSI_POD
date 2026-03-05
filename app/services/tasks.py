from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from flask import current_app


def _get_tasks_v2_module():
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError("google-cloud-tasks is required to enqueue Cloud Tasks jobs.") from exc
    return tasks_v2


@dataclass(slots=True)
class EmailTaskPayload:
    shipment_id: int
    action_type: str
    actor_user_id: int
    driver_email: str | None = None
    driver_name: str | None = None
    hwb_number: str | None = None
    location_name: str | None = None
    photo_blob_name: str | None = None
    signature_blob_name: str | None = None
    shipper_email: str | None = None
    consignee_email: str | None = None


def _validate_required_fields(payload: EmailTaskPayload) -> None:
    if payload.shipment_id is None:
        raise ValueError("EmailTaskPayload.shipment_id is required.")
    if not str(payload.action_type or "").strip():
        raise ValueError("EmailTaskPayload.action_type is required.")
    if payload.actor_user_id is None:
        raise ValueError("EmailTaskPayload.actor_user_id is required.")


def enqueue_email_task(payload: EmailTaskPayload) -> None:
    _validate_required_fields(payload)

    project_id = current_app.config.get("GCP_PROJECT_ID", "").strip()
    public_service_url = current_app.config.get("PUBLIC_SERVICE_URL", "").strip()
    service_account_email = current_app.config.get("TASK_SERVICE_ACCOUNT_EMAIL", "").strip()
    region = current_app.config.get("GCP_REGION", "us-central1").strip()
    queue_name = current_app.config.get("EMAIL_QUEUE_NAME", "email-queue").strip()

    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID is required to enqueue Cloud Tasks email jobs.")
    if not public_service_url:
        raise RuntimeError("PUBLIC_SERVICE_URL is required to enqueue Cloud Tasks email jobs.")
    if not service_account_email:
        raise RuntimeError("TASK_SERVICE_ACCOUNT_EMAIL is required to enqueue Cloud Tasks email jobs.")

    tasks_v2 = _get_tasks_v2_module()
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(project_id, region, queue_name)
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{public_service_url.rstrip('/')}/api/tasks/send-email",
            "headers": {"Content-Type": "application/json"},
            "oidc_token": {"service_account_email": service_account_email},
            "body": json.dumps(asdict(payload)).encode("utf-8"),
        }
    }
    client.create_task(parent=parent, task=task)
