from flask import Blueprint, render_template, request, flash, redirect, url_for, g, jsonify
from app.blueprints.auth.guards import require_employee_approval
from app.services.couchdrop import CouchdropService
import base64
import uuid
from io import BytesIO
from werkzeug.datastructures import FileStorage

paperwork_bp = Blueprint("paperwork", __name__)

# --- 1. NEW: POD Event Capture Route ---
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
        # Strip the data URI scheme header
        header, encoded = signature_base64.split(",", 1)
        decoded_image_data = base64.b64decode(encoded)
        # Wrap in a FileStorage object for compatibility with downstream services
        signature_file = FileStorage(
            stream=BytesIO(decoded_image_data),
            filename=f"signature_{uuid.uuid4().hex[:8]}.png",
            content_type="image/png"
        )

    # 3. Database Insertion & Storage Logic Execution
    # Connect to the expanded PODEvent SQLAlchemy model and GCS storage execution here.
    # e.g., gcs_photo_url = GCSService.upload(pod_photo)
    # e.g., gcs_sig_url = GCSService.upload(signature_file)

    if is_ajax:
        return jsonify({"success": True, "message": "Event logged."}), 200
    
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
