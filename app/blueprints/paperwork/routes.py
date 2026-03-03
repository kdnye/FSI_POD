from flask import Blueprint, render_template, request, flash, redirect, url_for, g, jsonify, current_app
import base64
import uuid
from io import BytesIO
from werkzeug.datastructures import FileStorage
from sqlalchemy import inspect

from app import db
from models import PODEvent
from app.blueprints.auth.guards import require_employee_approval
from app.services.couchdrop import CouchdropService
from app.services.gcs import GCSService
from sqlalchemy.orm import aliased
from models import ExpectedDelivery
from models import LoadBoard, PODRecord

paperwork_bp = Blueprint("paperwork", __name__)


def ensure_hybrid_pod_tables() -> None:
    """Create hybrid POD tables when missing."""
    if current_app.config.get("HYBRID_POD_TABLES_READY"):
        return

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if LoadBoard.__tablename__ not in table_names:
        LoadBoard.__table__.create(db.engine)
    if PODRecord.__tablename__ not in table_names:
        PODRecord.__table__.create(db.engine)

    current_app.config["HYBRID_POD_TABLES_READY"] = True


def submit_pod(
    *,
    hwb_number: str,
    action_type: str,
    recipient_name: str,
    pod_photo,
    signature_file,
    latitude: str | None,
    longitude: str | None,
) -> None:
    """Persist POD data in hybrid mode and keep legacy POD event logging."""
    if action_type not in {"Pickup", "Delivery"}:
        raise ValueError("Invalid action type.")

    load_board_entry = db.session.get(LoadBoard, hwb_number)
    photo_uri = GCSService.upload_file(pod_photo, folder=f"pod_photos/{action_type.lower()}")
    sig_uri = GCSService.upload_file(signature_file, folder=f"signatures/{action_type.lower()}")

    pod_record = PODRecord(
        hwb_number=hwb_number,
        delivery_photo=photo_uri,
        signature_image=sig_uri,
        recipient_name=recipient_name,
        driver_id=g.current_user.id,
        action_type=action_type,
    )

    if load_board_entry:
        pod_record.shipper = load_board_entry.shipper
        pod_record.consignee = load_board_entry.consignee
        pod_record.contact_name = load_board_entry.contact_name
        pod_record.phone = load_board_entry.phone
        load_board_entry.status = "Picked Up" if action_type == "Pickup" else "Delivered"

    db.session.add(pod_record)

    # Keep existing dashboard status feed functioning.
    legacy_event = PODEvent(
        user_id=g.current_user.id,
        reference_id=hwb_number,
        event_type=action_type.upper(),
        latitude=latitude if latitude else None,
        longitude=longitude if longitude else None,
        signature_url=sig_uri,
        photo_url=photo_uri,
    )
    legacy_event.set_az_timestamp()
    db.session.add(legacy_event)

@paperwork_bp.route("/pod/event", methods=["GET", "POST"])
@require_employee_approval()
def log_pod_event():
    ensure_hybrid_pod_tables()

    if request.method == "GET":
        return render_template("paperwork/pod_event.html", title="Capture POD")

    is_ajax = request.headers.get("Accept") == "application/json"
    
    hwb_number = (request.form.get("hwb_number") or "").strip()
    action_type = request.form.get("action_type")
    recipient_name = (request.form.get("recipient_name") or "").strip()
    lat = request.form.get("latitude")
    lon = request.form.get("longitude")

    if not hwb_number:
        message = {"error": "HWB number is required."}
        if is_ajax:
            return jsonify(message), 400
        flash(message["error"])
        return redirect(url_for("paperwork.log_pod_event"))

    if not recipient_name:
        message = {"error": "Recipient name is required."}
        if is_ajax:
            return jsonify(message), 400
        flash(message["error"])
        return redirect(url_for("paperwork.log_pod_event"))
    
    # 1. Handle Native Photo File
    pod_photo = request.files.get("pod_photo")
    
    # 2. Decode Signature Base64 to Binary
    signature_base64 = request.form.get("signature_base64")
    signature_file = None
    if signature_base64:
        try:
            header, encoded = signature_base64.split(",", 1)
            decoded_image_data = base64.b64decode(encoded)
            signature_file = FileStorage(
                stream=BytesIO(decoded_image_data),
                filename=f"signature_{uuid.uuid4().hex[:8]}.png",
                content_type="image/png"
            )
        except Exception as e:
            if is_ajax: return jsonify({"error": "Failed to decode signature"}), 400
            flash("Failed to process signature.")
            return redirect(url_for("paperwork.log_pod_event"))

    # 3. Database Insertion & Storage Logic Execution
    try:
        submit_pod(
            hwb_number=hwb_number,
            action_type=action_type,
            recipient_name=recipient_name,
            pod_photo=pod_photo,
            signature_file=signature_file,
            latitude=lat,
            longitude=lon,
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        if is_ajax: return jsonify({"error": f"Transaction failed: {str(e)}"}), 500
        flash("Transaction failed. Please try again.")
        return redirect(url_for("paperwork.log_pod_event"))

    if is_ajax:
        return jsonify({"success": True, "message": "Event logged successfully."}), 200
    
    flash("POD Event logged.")
    return redirect(url_for("paperwork.log_pod_event"))


@paperwork_bp.post("/pod/scan")
@require_employee_approval()
def scan_hwb():
    ensure_hybrid_pod_tables()
    payload = request.get_json(silent=True) or {}
    hwb_number = (payload.get("hwb_number") or "").strip()
    if not hwb_number:
        return jsonify({"error": "HWB number is required."}), 400

    load_board_entry = db.session.get(LoadBoard, hwb_number)
    if not load_board_entry:
        return jsonify({"mode": "base", "hwb_number": hwb_number}), 200

    return jsonify(
        {
            "mode": "enhanced",
            "hwb_number": hwb_number,
            "shipper": load_board_entry.shipper,
            "consignee": load_board_entry.consignee,
            "contact_name": load_board_entry.contact_name,
            "phone": load_board_entry.phone,
            "status": load_board_entry.status,
        }
    ), 200


@paperwork_bp.get("/load-board")
@require_employee_approval()
def active_load_board():
    ensure_hybrid_pod_tables()
    loads = (
        LoadBoard.query.filter_by(assigned_driver=g.current_user.id)
        .order_by(LoadBoard.hwb_number.asc())
        .all()
    )
    return render_template("paperwork/load_board.html", title="Active Load Board", loads=loads)


@paperwork_bp.get("/pod/history")
@require_employee_approval()
def pod_history():
    ensure_hybrid_pod_tables()
    records = (
        PODRecord.query.filter_by(driver_id=g.current_user.id)
        .order_by(PODRecord.id.desc())
        .limit(100)
        .all()
    )
    return render_template("paperwork/pod_history.html", title="POD History", records=records)

# --- 2. EXISTING: Batch Upload Route ---
@paperwork_bp.route("/upload", methods=["GET", "POST"])
@require_employee_approval()
def upload():
    if request.method == "POST":
        files = request.files.getlist("scans")
        is_ajax = request.headers.get("Accept") == "application/json"
        
        if not files or files[0].filename == '':
            if is_ajax: return jsonify({"error": "No files selected."}), 400
            flash("No files selected.")
            return redirect(request.url)
            
        if len(files) > 100:
            if is_ajax: return jsonify({"error": "Batch exceeds 100 file limit."}), 400
            flash("Batch exceeds 100 file limit.")
            return redirect(request.url)

        success_count = 0
        for file in files:
            if CouchdropService.upload_driver_paperwork(g.current_user, file):
                success_count += 1
        
        # Return lightweight JSON for sequential client-side uploads
        if is_ajax:
            return jsonify({"success_count": success_count}), 200
        
        # Fallback for standard synchronous post
        flash(f"Successfully uploaded {success_count} documents.")
        return redirect(url_for("paperwork.history"))

    return render_template("paperwork/upload.html", title="Batch Upload")


# --- 3. EXISTING: History Route ---
@paperwork_bp.get("/history")
@require_employee_approval()
def history():
    return render_template("paperwork/history.html", title="Upload History")

# --- 4. NEW: Ops Dashboard UI ---
@paperwork_bp.route("/ops/dashboard")
@require_employee_approval()
def ops_dashboard():
    # Only allow Admin or Supervisor to view the ops dashboard (optional RBAC)
    if g.current_user.role.value not in ["ADMIN", "SUPERVISOR"]:
        flash("Unauthorized access.")
        return redirect(url_for("paperwork.history"))
        
    return render_template("paperwork/dashboard.html", title="Live Ops Dashboard")

# --- 5. NEW: Real-Time Data Feed ---
@paperwork_bp.route("/api/deliveries/live")
@require_employee_approval()
def api_live_deliveries():
    """Returns the current state of expected deliveries and latest POD events."""
    # Fetch today's expected deliveries
    deliveries = ExpectedDelivery.query.order_by(ExpectedDelivery.id.desc()).limit(50).all()
    
    payload = []
    for d in deliveries:
        # Find the latest event for this reference ID
        latest_event = PODEvent.query.filter_by(reference_id=d.reference_id).order_by(PODEvent.id.desc()).first()
        
        status = d.status
        timestamp = None
        
        # Determine real-time status based on events
        if latest_event:
            status = latest_event.event_type # 'PICKUP' or 'DELIVERY'
            # Format Arizona time if available
            timestamp = latest_event.az_timestamp.strftime("%I:%M %p MST") if latest_event.az_timestamp else "Recent"

        payload.append({
            "reference_id": d.reference_id,
            "consignee": d.consignee_name,
            "address": d.destination_address,
            "status": status,
            "last_updated": timestamp or "Pending",
            "batch_id": d.batch_id
        })
        
    return jsonify(payload)
