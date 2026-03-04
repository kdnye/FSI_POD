from __future__ import annotations

import json

from flask import current_app


def _get_tasks_v2_module():
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError("google-cloud-tasks is required to enqueue Cloud Tasks jobs.") from exc
    return tasks_v2


def enqueue_email_task(
    shipment_id: int,
    action_type: str,
    actor_user_id: int,
    shipper_email: str | None,
    consignee_email: str | None,
) -> None:
    project_id = current_app.config.get("GCP_PROJECT_ID", "").strip()
    public_service_url = current_app.config.get("PUBLIC_SERVICE_URL", "").strip()
    service_account_email = current_app.config.get("TASK_SERVICE_ACCOUNT_EMAIL", "").strip()

    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID is required to enqueue Cloud Tasks email jobs.")
    if not public_service_url:
        raise RuntimeError("PUBLIC_SERVICE_URL is required to enqueue Cloud Tasks email jobs.")
    if not service_account_email:
        raise RuntimeError("TASK_SERVICE_ACCOUNT_EMAIL is required to enqueue Cloud Tasks email jobs.")

    tasks_v2 = _get_tasks_v2_module()
    client = tasks_v2.CloudTasksClient()
    queue_name = client.queue_path(
        project_id,
        current_app.config.get("GCP_REGION", "us-central1").strip(),
        current_app.config.get("QUEUE_NAME", "email-queue").strip(),
    )

    payload = {
        "shipment_id": shipment_id,
        "action_type": action_type,
        "actor_user_id": actor_user_id,
        "shipper_email": shipper_email,
        "consignee_email": consignee_email,
    }

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{public_service_url.rstrip('/')}/api/tasks/send-email",
            "headers": {"Content-Type": "application/json"},
            "oidc_token": {"service_account_email": service_account_email},
            "body": json.dumps(payload).encode("utf-8"),
        }
    }

    client.create_task(parent=queue_name, task=task)
