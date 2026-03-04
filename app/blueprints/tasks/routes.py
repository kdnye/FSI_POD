from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from app import csrf, db
from app.services.gcs import generate_signed_url
from app.services.postmark import ALLOWED_SHIPMENT_ALERT_ACTIONS, send_shipment_alert
from models import User

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


def _validate_task_request() -> tuple[dict[str, str], int] | None:
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

    expected_audience = (current_app.config.get("TASKS_EXPECTED_AUDIENCE") or "").strip()
    if not expected_audience:
        return jsonify({"error": "Task endpoint audience is not configured."}), 403

    expected_invoker_email = (current_app.config.get("TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL") or "").strip()
    if not expected_invoker_email:
        return jsonify({"error": "Task endpoint invoker is not configured."}), 403

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
    auth_error = _validate_task_request()
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
        actor_user_id_int = int(actor_user_id)
    except (TypeError, ValueError):
        _log_task_validation_failure("malformed_actor_user_id", payload)
        return jsonify({"error": "Invalid actor_user_id for email task."}), 400

    driver = db.session.get(User, actor_user_id_int)
    if driver is None:
        return jsonify({"error": "Driver user not found for email task."}), 404

    def _build_media_url(blob_name: object) -> str | None:
        if not isinstance(blob_name, str) or not blob_name.strip():
            return None
        return generate_signed_url(blob_name)

    timestamp = datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %I:%M %p MST")

    try:
        sent, reason = send_shipment_alert(
            action_type=normalized_action_type,
            hwb_number=hwb_number,
            location_name=location_name,
            driver_email=driver.email,
            driver_name=driver.name,
            photo_url=_build_media_url(photo_blob_name),
            signature_url=_build_media_url(signature_blob_name),
            shipper_email=shipper_email,
            consignee_email=consignee_email,
            timestamp=timestamp,
        )
    except Exception as exc:
        current_app.logger.exception(
            "Failed to generate signed URLs for shipment alert task shipment_id=%s action_type=%s task_name=%s request_id=%s",
            shipment_id,
            action_type,
            task_name,
            request_id,
            exc_info=exc,
        )
        return (
            jsonify(
                {
                    "error": {
                        "message": "Failed to generate media URLs for shipment alert.",
                        "hwb_number": hwb_number,
                        "action_type": action_type,
                        "reason": "signed_url_generation_failed",
                    }
                }
            ),
            500,
        )

    if not sent:
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

# app/blueprints/tasks/routes.py

@tasks_bp.get("/test-email-connectivity")
def test_email_connectivity():
    from app.services.postmark import send_shipment_alert
    from models import Shipment, User
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    # Get test data from your DB
    shipment = Shipment.query.first()
    driver = User.query.filter_by(is_active=True).first()
    
    if not shipment:
        return "Error: No shipments found in DB to use for test.", 404
    if not driver:
        return "Error: No active users found in DB to use as driver.", 404

    # Mimic the real timestamp logic
    timestamp = datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %I:%M %p MST")

    try:
        # Correctly passing individual parameters to match postmark.py signature
        success, reason = send_shipment_alert(
            action_type="SHIPPER_PICKUP",
            hwb_number=shipment.hwb_number,
            location_name="Test Connectivity Location",
            driver_email=driver.email,
            driver_name=driver.name or "Test Driver",
            photo_url="https://placehold.co/600x400?text=Test+Photo",
            signature_url="https://placehold.co/600x400?text=Test+Signature",
            shipper_email="shipper-test@freightservicesinc.com",
            consignee_email="consignee-test@freightservicesinc.com",
            timestamp=timestamp
        )
        
        if success:
            return f"SUCCESS: Test email accepted by Postmark. (Reason: {reason})", 200
        else:
            return f"FAILURE: Postmark function rejected the request. Reason: {reason}", 500
            
    except Exception as e:
        import traceback
        return f"CRITICAL ERROR: {str(e)}\n\n{traceback.format_exc()}", 500
