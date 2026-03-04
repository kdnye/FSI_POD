from __future__ import annotations

from flask import Blueprint, jsonify, request

from app import csrf, db
from app.services.postmark import send_shipment_alert
from models import User

tasks_bp = Blueprint("tasks", __name__)


@tasks_bp.post("/api/tasks/send-email")
@csrf.exempt
def send_email_task() -> tuple[dict[str, str], int]:
    payload = request.get_json(silent=True) or {}

    shipment_id = payload.get("shipment_id")
    action_type = payload.get("action_type")
    actor_user_id = payload.get("actor_user_id")
    shipper_email = payload.get("shipper_email")
    consignee_email = payload.get("consignee_email")
    hwb_number = payload.get("hwb_number")
    location_name = payload.get("location_name")
    driver_name = payload.get("driver_name")
    photo_url = payload.get("photo_url")
    signature_url = payload.get("signature_url")

    if shipment_id is None or not action_type or actor_user_id is None:
        return jsonify({"error": "Missing required task payload fields."}), 400

    driver_user = db.session.get(User, actor_user_id)
    if driver_user is None:
        return jsonify({"error": "Driver user not found for email task."}), 404

    try:
        send_shipment_alert(
            shipment_id,
            action_type,
            driver_user,
            shipper_email=shipper_email,
            consignee_email=consignee_email,
            hwb_number=hwb_number,
            location_name=location_name,
            driver_name=driver_name,
            photo_url=photo_url,
            signature_url=signature_url,
        )
    except TypeError:
        send_shipment_alert(
            shipment_id,
            action_type,
            driver_user,
            shipper_email=shipper_email,
            consignee_email=consignee_email,
        )
    return jsonify({"status": "ok"}), 200
