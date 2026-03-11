from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from app import csrf, db
from app.services.couchdrop import CouchdropService
from app.services.postmark import ALLOWED_SHIPMENT_ALERT_ACTIONS, send_shipment_alert
from models import Shipment, User

tasks_bp = Blueprint("tasks", __name__)


def _log_task_validation_failure(reason: str, payload: dict[str, object]) -> None:
    current_app.logger.warning(
        "send_email_task validation failed reason=%s shipment_id=%s action_type=%s actor_user_id=%s task_name=%s request_id=%s",
        reason,
        payload.get("shipment_id"),
        payload.get("action_type"),
        payload.get("actor_user_id"),
        request.headers.get("X-CloudTasks-TaskName"),
        request.headers.get("X-Request-Id"),
    )


def _validate_task_request(expected_path: str) -> tuple[dict[str, str], int] | None:
    task_name = request.headers.get("X-CloudTasks-TaskName")
    if not task_name:
        return jsonify({"error": "Missing required Cloud Tasks task header."}), 403

    expected_queue_name = (current_app.config.get("TASKS_EXPECTED_QUEUE_NAME") or "").strip()
    queue_name = (request.headers.get("X-CloudTasks-QueueName") or "").strip()
    if queue_name and expected_queue_name and queue_name != expected_queue_name:
        return jsonify({"error": "Invalid Cloud Tasks queue metadata."}), 403

    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing Bearer token for task request."}), 403

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return jsonify({"error": "Missing Bearer token for task request."}), 403

    expected_invoker_email = (current_app.config.get("TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL") or "").strip()
    if not expected_invoker_email:
        return jsonify({"error": "Task endpoint invoker is not configured."}), 403

    public_service_url = (current_app.config.get("PUBLIC_SERVICE_URL") or "").strip().rstrip("/")
    if not public_service_url:
        return jsonify({"error": "PUBLIC_SERVICE_URL is not configured."}), 500

    expected_audience = f"{public_service_url}{expected_path}"

    try:
        claims = _verify_task_oidc_token(token=token, audience=expected_audience)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning("Failed to verify Cloud Tasks OIDC token: %s", exc)
        return jsonify({"error": "Invalid task authentication token."}), 403

    issuer = str(claims.get("iss", "")).strip()
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        return jsonify({"error": "Invalid token issuer for task request."}), 403

    token_email = str(claims.get("email", "")).strip().lower()
    if token_email != expected_invoker_email.lower():
        return jsonify({"error": "Token principal is not allowed for task request."}), 403

    if claims.get("email_verified") is False:
        return jsonify({"error": "Token email must be verified for task request."}), 403

    return None


def _verify_task_oidc_token(token: str, audience: str) -> dict[str, object]:
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, Request(), audience=audience)


@tasks_bp.post("/api/tasks/send-email")
@csrf.exempt
def send_email_task() -> tuple[dict[str, str], int]:
    auth_error = _validate_task_request("/tasks/api/tasks/send-email")
    if auth_error is not None:
        return auth_error

    payload = request.get_json(silent=True) or {}
    task_name = request.headers.get("X-CloudTasks-TaskName")
    request_id = request.headers.get("X-Request-Id")

    shipment_id = payload.get("shipment_id")
    action_type = payload.get("action_type")
    actor_user_id = payload.get("actor_user_id")
    hwb_number = payload.get("hwb_number")
    location_name = payload.get("location_name")
    shipper_email = payload.get("shipper_email")
    consignee_email = payload.get("consignee_email")
    driver_email = payload.get("driver_email")
    driver_name = payload.get("driver_name")
    photo_blob_name = payload.get("photo_blob_name")
    signature_blob_name = payload.get("signature_blob_name")

    if shipment_id is None or actor_user_id is None or not action_type:
        _log_task_validation_failure("missing_required_fields", payload)
        return jsonify({"error": "Missing required task payload fields."}), 400

    if not isinstance(action_type, str):
        _log_task_validation_failure("invalid_action_type_type", payload)
        return jsonify({"error": "Invalid action_type for email task."}), 400

    normalized_action_type = action_type.strip().upper()
    if not normalized_action_type or normalized_action_type not in ALLOWED_SHIPMENT_ALERT_ACTIONS:
        _log_task_validation_failure("unknown_action_type", payload)
        return jsonify({"error": "Invalid action_type for email task."}), 400

    try:
        shipment_id_int = int(shipment_id)
    except (TypeError, ValueError):
        _log_task_validation_failure("malformed_shipment_id", payload)
        return jsonify({"error": "Invalid shipment_id for email task."}), 400

    try:
        actor_user_id_int = int(actor_user_id)
    except (TypeError, ValueError):
        _log_task_validation_failure("malformed_actor_user_id", payload)
        return jsonify({"error": "Invalid actor_user_id for email task."}), 400

    shipment = db.session.get(Shipment, shipment_id_int)
    if shipment is not None:
        shipper_email = shipper_email or shipment.shipper_email
        consignee_email = consignee_email or shipment.consignee_email

    driver = db.session.get(User, actor_user_id_int)
    if driver is not None:
        if not isinstance(driver_email, str) or not driver_email.strip():
            driver_email = driver.email
        if not isinstance(driver_name, str) or not driver_name.strip():
            driver_name = driver.name

    timestamp = datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %I:%M %p MST")

    def _get_raw_string(val: object) -> str | None:
        return val if isinstance(val, str) and val.strip() else None

    sent, reason = send_shipment_alert(
            action_type=normalized_action_type,
            hwb_number=hwb_number,
            location_name=location_name,
            driver_email=driver_email if isinstance(driver_email, str) else None,
            driver_name=driver_name if isinstance(driver_name, str) else None,
            photo_url=_get_raw_string(photo_blob_name),
            signature_url=_get_raw_string(signature_blob_name),
            shipper_email=shipper_email,
            consignee_email=consignee_email,
            timestamp=timestamp,
    )

    if not sent:
        if reason in {"missing_recipients", "disabled_settings"}:
            current_app.logger.info(
                "Shipment alert task skipped action_type=%s hwb_number=%s reason=%s task_name=%s request_id=%s",
                action_type,
                hwb_number,
                reason,
                task_name,
                request_id,
            )
            return jsonify({"status": "skipped", "reason": reason}), 200

        current_app.logger.error(
            "Shipment alert task failed action_type=%s hwb_number=%s reason=%s task_name=%s request_id=%s",
            action_type,
            hwb_number,
            reason,
            task_name,
            request_id,
        )
        return (
            jsonify(
                {
                    "error": {
                        "message": "Failed to send shipment alert.",
                        "hwb_number": hwb_number,
                        "action_type": action_type,
                        "reason": reason,
                    }
                }
            ),
            500,
        )

    return jsonify({"status": "ok"}), 200


@tasks_bp.post("/api/tasks/upload-couchdrop")
@csrf.exempt
def upload_couchdrop_task() -> tuple[dict[str, str], int]:
    auth_error = _validate_task_request("/tasks/api/tasks/upload-couchdrop")
    if auth_error is not None:
        return auth_error

    payload = request.get_json(silent=True) or {}
    staged_blob_name = str(payload.get("staged_blob_name") or "").strip()
    remote_path = str(payload.get("remote_path") or "").strip()
    original_filename = str(payload.get("original_filename") or "").strip()
    content_type = str(payload.get("content_type") or "").strip() or "application/octet-stream"
    idempotency_key = str(payload.get("idempotency_key") or "").strip()

    if not staged_blob_name or not remote_path or not original_filename or not idempotency_key:
        return jsonify({"error": "Missing required couchdrop task payload fields."}), 400

    uploaded, reason = CouchdropService.upload_staged_paperwork(
        staged_blob_name=staged_blob_name,
        remote_path=remote_path,
        filename=original_filename,
        content_type=content_type,
    )
    if not uploaded:
        if reason in {"staged_blob_missing", "staged_blob_empty"}:
            return jsonify({"status": "skipped", "reason": reason, "idempotency_key": idempotency_key}), 200
        return jsonify({"error": "Failed couchdrop upload task.", "reason": reason, "idempotency_key": idempotency_key}), 500

    return jsonify({"status": "ok", "idempotency_key": idempotency_key}), 200

# app/blueprints/tasks/routes.py

# app/blueprints/tasks/routes.py

@tasks_bp.get("/test-email-connectivity")
def test_email_connectivity():
    import requests
    from flask import current_app
    
    # Configuration from your environment
    token = current_app.config.get("POSTMARK_SERVER_TOKEN")
    # Using the 'From' address from your Java example
    from_email = "pod@freightservices.net" 
    
    if not token:
        return "ERROR: POSTMARK_SERVER_TOKEN is missing in config.", 500

    # Payload mimicking your Java snippet
    payload = {
        "From": from_email,
        "To": "test@blackhole.postmarkapp.com",
        "Cc": "david.alexander@freightservices.net",
        "Subject": "Connectivity Test: Standard Email",
        "TextBody": "Hello from the FSI Python App! This is a non-template test.",
        "MessageStream": "pod"
    }

    try:
        response = requests.post(
            "https://api.postmarkapp.com/email",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": token,
            },
            json=payload,
            timeout=10,
        )
        
        if response.status_code == 200:
            return "SUCCESS: Standard email sent. API Token and Stream are valid.", 200
        else:
            # This will capture the exact error message from Postmark (e.g., 'Invalid Message Stream')
            return f"FAILURE: Postmark rejected the request. Status: {response.status_code} | Body: {response.text}", 500
            
    except Exception as e:
        return f"CRITICAL ERROR: {str(e)}", 500
    except Exception as e:
        import traceback
        return f"CRITICAL ERROR: {str(e)}\n\n{traceback.format_exc()}", 500
