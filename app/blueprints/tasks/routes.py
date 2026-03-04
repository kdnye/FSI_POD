from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

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
    hwb_number = payload.get("hwb_number")
    location_name = payload.get("location_name")
    shipper_email = payload.get("shipper_email")
    consignee_email = payload.get("consignee_email")
    photo_url = payload.get("photo_url")
    signature_url = payload.get("signature_url")

    if shipment_id is None or actor_user_id is None or not action_type:
        return jsonify({"error": "Missing required task payload fields."}), 400

    driver = db.session.get(User, int(actor_user_id))
    if driver is None:
        return jsonify({"error": "Driver user not found for email task."}), 404

    timestamp = datetime.now(ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d %I:%M %p MST")

    send_shipment_alert(
        action_type=action_type,
        hwb_number=hwb_number,
        location_name=location_name,
        driver_email=driver.email,
        driver_name=driver.name,
        photo_url=photo_url,
        signature_url=signature_url,
        shipper_email=shipper_email,
        consignee_email=consignee_email,
        timestamp=timestamp,
    )
    return jsonify({"status": "ok"}), 200
