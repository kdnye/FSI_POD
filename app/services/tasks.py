from __future__ import annotations

import json

from flask import current_app

from app.services.gcs import generate_signed_url


def _get_tasks_v2_module():
    try:
        from google.cloud import tasks_v2
    except ImportError as exc:
        raise RuntimeError("google-cloud-tasks is required to enqueue Cloud Tasks jobs.") from exc
    return tasks_v2


def enqueue_email_task(
    shipment_id,
    action_type,
    actor_user_id,
    hwb_number,
    location_name,
    photo_blob_name,
    signature_blob_name,
    shipper_email,
    consignee_email,
):
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

    photo_url = generate_signed_url(photo_blob_name)
    signature_url = generate_signed_url(signature_blob_name)

    payload = {
        "shipment_id": shipment_id,
        "action_type": action_type,
        "actor_user_id": actor_user_id,
        "hwb_number": hwb_number,
        "location_name": location_name,
        "photo_blob_name": photo_blob_name,
        "signature_blob_name": signature_blob_name,
        "photo_url": photo_url,
        "signature_url": signature_url,
        "shipper_email": shipper_email,
        "consignee_email": consignee_email,
    }

    tasks_v2 = _get_tasks_v2_module()
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(project_id, region, queue_name)
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{public_service_url.rstrip('/')}/api/tasks/send-email",
            "headers": {"Content-Type": "application/json"},
            "oidc_token": {"service_account_email": service_account_email},
            "body": json.dumps(payload).encode("utf-8"),
        }
    }
    client.create_task(parent=parent, task=task)
