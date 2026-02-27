from flask import Blueprint, render_template, request, flash, redirect, url_for, g, jsonify
import base64
import uuid
from io import BytesIO
from werkzeug.datastructures import FileStorage

from app import db
from models import PODEvent
from app.blueprints.auth.guards import require_employee_approval
from app.services.couchdrop import CouchdropService
from app.services.gcs import GCSService
from sqlalchemy.orm import aliased
from models import ExpectedDelivery

paperwork_bp = Blueprint("paperwork", __name__)

@paperwork_bp.route("/pod/event", methods=["GET", "POST"])
@require_employee_approval()
def log_pod_event():
    if request.method == "GET":
        return render_template("paperwork/pod_event.html", title="Capture POD")

    is_ajax = request.headers.get("Accept") == "application/json"
    
    reference_id = request.form.get("reference_id")
    event_type = request.form.get("event_type")
    lat = request.form.get("latitude")
    lon = request.form.get("longitude")
    
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
        # Upload streams to GCS
        photo_uri = GCSService.upload_file(pod_photo, folder=f"pod_photos/{event_type.lower()}")
        sig_uri = GCSService.upload_file(signature_file, folder=f"signatures/{event_type.lower()}")

        # Construct database record
        new_event = PODEvent(
            user_id=g.current_user.id,
            reference_id=reference_id,
            event_type=event_type,
            latitude=lat if lat else None,
            longitude=lon if lon else None,
            signature_url=sig_uri,
            photo_url=photo_uri
        )
        new_event.set_az_timestamp() # Applies timezone translation

        db.session.add(new_event)
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

