from flask import Blueprint, render_template, request, flash, redirect, url_for, g, jsonify, Response, send_from_directory
import csv
import base64
import re
import uuid
from io import BytesIO, StringIO
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from werkzeug.datastructures import FileStorage

from app import db
from models import PODEvent, Role
from app.blueprints.auth.guards import require_employee_approval
from app.services.couchdrop import CouchdropService
from app.services.gcs import GCSService
from app.services.shipment_workflow import ShipmentTransitionError, apply_pod_transition, normalize_pod_action
from models import ExpectedDelivery
from models import (
    PODRecord,
    Shipment,
    ShipmentGroup,
    ShipmentLeg,
    ShipmentLegStatus,
    ShipmentLegTransition,
    ShipmentStatus,
    ShipmentLegType,
    User,
)

paperwork_bp = Blueprint("paperwork", __name__)
ARIZONA_TZ = ZoneInfo("America/Phoenix")


def current_user_role() -> str:
    role = getattr(g.current_user, "role", None)
    raw_role = getattr(role, "value", role)

    try:
        return Role.from_value(raw_role).value
    except ValueError:
        return str(raw_role or "")


def is_admin_user() -> bool:
    try:
        return Role.from_value(current_user_role()).is_admin
    except ValueError:
        return False


def is_ops_or_admin_user() -> bool:
    if is_admin_user():
        return True

    return bool(getattr(g.current_user, "is_ops", False))


def require_ops_or_admin_or_redirect(redirect_endpoint: str):
    if not is_ops_or_admin_user():
        flash("Ops or admin access is required.")
        return redirect(url_for(redirect_endpoint))
    return None


def parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pod_history_csv_response(records, filename: str) -> Response:
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)

    writer.writerow([
        "id",
        "hwb_number",
        "action_type",
        "recipient_name",
        "shipper",
        "consignee",
        "contact_name",
        "phone",
        "driver_id",
        "latitude",
        "longitude",
        "shipment_id",
        "leg_id",
        "leg_sequence",
        "leg_type",
        "timestamp_utc",
        "timestamp_az",
    ])
    for record in records:
        timestamp_utc = record.timestamp.astimezone(timezone.utc) if record.timestamp else None
        timestamp_az = record.timestamp.astimezone(ARIZONA_TZ) if record.timestamp else None
        writer.writerow([
            record.id,
            record.hwb_number or "",
            record.action_type,
            record.recipient_name,
            record.shipper or "",
            record.consignee or "",
            record.contact_name or "",
            record.phone or "",
            record.driver_id,
            record.latitude or "",
            record.longitude or "",
            record.shipment_id or "",
            record.leg_id or "",
            record.leg_sequence or "",
            record.leg_type or "",
            timestamp_utc.isoformat() if timestamp_utc else "",
            timestamp_az.isoformat() if timestamp_az else "",
        ])

    return Response(
        csv_buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@dataclass
class LegacyLoadView:
    hwb_number: str
    shipper: str
    consignee: str
    contact_name: str
    phone: str
    assigned_driver: int | None
    status: str
    shipment: Shipment | None = None
    current_leg_type: str | None = None
    current_leg_status: str | None = None
    stage_label: str = "Awaiting Pickup"
    stage_class: str = "status-awaiting-pickup"


def _shipment_current_leg(shipment: Shipment) -> ShipmentLeg | None:
    for leg in shipment.legs:
        if leg.leg_sequence == shipment.current_leg_index:
            return leg
    return shipment.legs[0] if shipment.legs else None


def _legacy_status_label(status: ShipmentStatus | str | None) -> str:
    raw = status.value if hasattr(status, "value") else str(status or "")
    mapping = {
        "PENDING": "Pending",
        "IN_PROGRESS": "In Progress",
        "PICKED_UP": "Picked Up",
        "DELIVERED": "Delivered",
        "CANCELLED": "Cancelled",
    }
    return mapping.get(raw, raw.title() if raw else "Pending")


def load_view_from_shipment(shipment: Shipment) -> LegacyLoadView:
    # 1. Identify specific legs
    display_driver_id = None
    active_leg = _shipment_current_leg(shipment)
    if active_leg:
        if active_leg.leg_sequence == 2:
            leg3 = next((l for l in shipment.legs if l.leg_sequence == 3), None)
            display_driver_id = leg3.assigned_driver_id if leg3 else None
        else:
            display_driver_id = active_leg.assigned_driver_id

    current_leg_type = None
    current_leg_status = None
    if active_leg:
        leg_type_value = getattr(active_leg.leg_type, "value", active_leg.leg_type)
        leg_status_value = getattr(active_leg.status, "value", active_leg.status)
        current_leg_type = str(leg_type_value) if leg_type_value is not None else None
        current_leg_status = str(leg_status_value) if leg_status_value is not None else None

    # UI Stage Labels - This explicitly maps the workflow state to the CSS badges
    stage_label = "Awaiting Pickup"
    stage_class = "status-awaiting-pickup"

    # Evaluate using the enum names directly from the workflow engine
    overall = getattr(shipment.overall_status, "name", shipment.overall_status)
    
    if overall == "IN_PROGRESS" and shipment.current_leg_index == 1:
        stage_label = "En Route to Origin Airport"
        stage_class = "status-in-progress"
    elif overall == "PICKED_UP" or (overall == "IN_PROGRESS" and shipment.current_leg_index == 2):
        stage_label = "At Origin Airport (In Transit)"
        stage_class = "status-picked-up"
    elif overall == "IN_PROGRESS" and shipment.current_leg_index == 3:
        stage_label = "Out for Delivery"
        stage_class = "status-in-progress"
    elif overall == "DELIVERED":
        stage_label = "Delivered"
        stage_class = "status-delivered"

    return LegacyLoadView(
        hwb_number=shipment.hwb_number,
        shipper=shipment.shipper_address or "N/A",
        consignee=shipment.consignee_address or "N/A",
        contact_name="System",
        phone="N/A",
        assigned_driver=display_driver_id,
        status=stage_label, # Pass the resolved label here
        shipment=shipment,
        current_leg_type=current_leg_type,
        current_leg_status=current_leg_status,
        stage_label=stage_label,
        stage_class=stage_class,
    )

def get_load_entry(hwb_number: str) -> LegacyLoadView | None:
    entries = get_load_entries_by_identifier(hwb_number)
    return entries[0] if entries else None


def get_load_entries_by_identifier(identifier: str) -> list[LegacyLoadView]:
    normalized = (identifier or "").strip()
    if not normalized:
        return []

    shipment = Shipment.query.filter_by(hwb_number=normalized).first()
    if shipment:
        return [load_view_from_shipment(shipment)]

    shipment_group = ShipmentGroup.query.filter_by(mawb_number=normalized).first()
    if not shipment_group:
        return []

    return [
        load_view_from_shipment(shipment)
        for shipment in sorted(shipment_group.shipments, key=lambda item: item.hwb_number or "")
    ]


def set_load_status(
    load_entry: LegacyLoadView,
    action_type: str,
    latitude: str | None = None,
    longitude: str | None = None,
    photo_blob_name: str | None = None,
    signature_blob_name: str | None = None,
) -> None:
    canonical_action = normalize_pod_action(action_type)
    if not load_entry.shipment:
        return

    apply_pod_transition(
        shipment=load_entry.shipment,
        action_type=canonical_action,
        actor_user_id=g.current_user.id,
        latitude=latitude,
        longitude=longitude,
        photo_blob_name=photo_blob_name,
        signature_blob_name=signature_blob_name,
    )


def assign_load_to_current_driver(load_entry: LegacyLoadView) -> None:
    if not load_entry.shipment:
        return

    active_leg = _shipment_current_leg(load_entry.shipment)
    if active_leg:
        active_leg.assigned_driver_id = g.current_user.id
        if active_leg.status in {ShipmentLegStatus.PENDING, ShipmentLegStatus.ASSIGNED}:
            active_leg.status = ShipmentLegStatus.ASSIGNED


def query_loads(full_board_access: bool, include_delivered: bool = True, include_cancelled: bool = False) -> list[LegacyLoadView]:
    shipment_query = Shipment.query.order_by(Shipment.hwb_number.asc())
    if not include_cancelled:
        shipment_query = shipment_query.filter(Shipment.overall_status != ShipmentStatus.CANCELLED)

    shipments = shipment_query.all()
    views = []

    for shipment in shipments:
        view = load_view_from_shipment(shipment)
        # Apply delivery visibility filter
        if not include_delivered and view.status == "Delivered":
            continue
        # Apply driver assignment filter
        if full_board_access or view.assigned_driver == g.current_user.id:
            views.append(view)

    return views


def resolve_pod_shipment_context(
    hwb_number: str,
    load_board_entry: LegacyLoadView | None,
) -> tuple[int | None, int | None, int | None, str | None, str]:
    """Resolve shipment/leg metadata for POD history rows when available."""
    shipment = None
    target_hwb_number = hwb_number

    if load_board_entry:
        target_hwb_number = load_board_entry.hwb_number

    if load_board_entry and load_board_entry.shipment:
        shipment = load_board_entry.shipment
    elif target_hwb_number:
        shipment = Shipment.query.filter_by(hwb_number=target_hwb_number).first()

    if not shipment:
        return None, None, None, None, target_hwb_number

    active_leg = _shipment_current_leg(shipment)
    if not active_leg:
        return shipment.id, None, None, None, shipment.hwb_number

    leg_type = active_leg.leg_type.value if hasattr(active_leg.leg_type, "value") else str(active_leg.leg_type)
    return shipment.id, active_leg.id, active_leg.leg_sequence, leg_type, shipment.hwb_number


def submit_pod(
    *,
    hwb_number: str,
    action_type: str,
    recipient_name: str | None,
    pod_photo,
    signature_file,
    latitude: str | None,
    longitude: str | None,
    shipper: str | None,
    consignee: str | None,
    contact_name: str | None,
    phone: str | None,
    off_sheet_confirmed: bool,
    reassignment_note: str | None,
) -> int:
    """Persist POD data in hybrid mode and keep legacy POD event logging."""
    canonical_action = normalize_pod_action(action_type)
    action_folder = canonical_action.lower()
    # Conditional Validation
    if canonical_action == "CONSIGNEE_DROP":
        if not recipient_name:
            raise ValueError("Recipient name is required for consignee drop.")
        if not pod_photo or not getattr(pod_photo, "filename", ""):
            raise ValueError("POD photo is required for consignee drop.")
        if not signature_file:
            raise ValueError("Signature image is required for consignee drop.")
    elif canonical_action == "ORIGIN_AIRPORT_DROP":
        if not recipient_name:
            raise ValueError("Recipient name is required for origin airport drop.")

    target_load_entries = get_load_entries_by_identifier(hwb_number)
    user_has_full_board_rights = is_ops_or_admin_user()
    off_sheet_entries = [
        entry
        for entry in target_load_entries
        if not user_has_full_board_rights and entry.assigned_driver != g.current_user.id
    ]
    is_off_sheet = bool(off_sheet_entries)

    if is_off_sheet and not off_sheet_confirmed:
        raise ValueError("Off-sheet completion requires confirmation.")

    # Conditional Uploads
    photo_uri = None
    if pod_photo and getattr(pod_photo, "filename", ""):
        photo_uri = GCSService.upload_file(pod_photo, folder=f"pod_photos/{action_folder}")
        if not photo_uri:
            raise ValueError("Failed to upload POD photo.")

    sig_uri = None
    if signature_file:
        sig_uri = GCSService.upload_file(signature_file, folder=f"signatures/{action_folder}")
        if not sig_uri:
            raise ValueError("Failed to upload signature image.")

    persisted_reassignment_note = None
    if is_off_sheet and off_sheet_confirmed and off_sheet_entries:
        from_driver_ids = sorted(
            {
                entry.assigned_driver if entry.assigned_driver is not None else "unassigned"
                for entry in off_sheet_entries
            },
            key=str,
        )
        note_suffix = f" Note: {reassignment_note.strip()}" if reassignment_note and reassignment_note.strip() else ""
        persisted_reassignment_note = (
            "Off-sheet confirmation accepted. Loads reassigned from "
            f"{', '.join(str(driver_id) for driver_id in from_driver_ids)} to {g.current_user.id}.{note_suffix}"
        )

    for entry in off_sheet_entries:
        assign_load_to_current_driver(entry)

    entries_to_process = target_load_entries or [None]
    for load_board_entry in entries_to_process:
        shipment_id, leg_id, leg_sequence, leg_type, target_hwb_number = resolve_pod_shipment_context(
            hwb_number,
            load_board_entry,
        )

        pod_record = PODRecord(
            hwb_number=target_hwb_number,
            delivery_photo=photo_uri,
            signature_image=sig_uri,
            recipient_name=recipient_name if recipient_name else None,
            driver_id=g.current_user.id,
            action_type=canonical_action,
            off_sheet_confirmed=off_sheet_confirmed,
            reassignment_note=persisted_reassignment_note,
            latitude=latitude if latitude else None,
            longitude=longitude if longitude else None,
            shipment_id=shipment_id,
            leg_id=leg_id,
            leg_sequence=leg_sequence,
            leg_type=leg_type,
        )

        if load_board_entry:
            # Path A: system match
            pod_record.shipper = load_board_entry.shipper
            pod_record.consignee = load_board_entry.consignee
            pod_record.contact_name = load_board_entry.contact_name
            pod_record.phone = load_board_entry.phone
            set_load_status(
                load_board_entry,
                canonical_action,
                latitude=latitude,
                longitude=longitude,
                photo_blob_name=photo_uri,
                signature_blob_name=sig_uri,
            )
        else:
            # Path B: manual POD
            pod_record.shipper = shipper
            pod_record.consignee = consignee
            pod_record.contact_name = contact_name
            pod_record.phone = phone

        db.session.add(pod_record)

        # Keep existing dashboard status feed functioning.
        legacy_event = PODEvent(
            user_id=g.current_user.id,
            reference_id=target_hwb_number,
            event_type=canonical_action,
            latitude=latitude if latitude else None,
            longitude=longitude if longitude else None,
            signature_url=sig_uri,
            photo_url=photo_uri,
        )
        legacy_event.set_az_timestamp()
        db.session.add(legacy_event)

    return len(entries_to_process)

@paperwork_bp.route("/pod/event", methods=["GET", "POST"])
@require_employee_approval()
def log_pod_event():
    if request.method == "GET":
        return render_template("paperwork/pod_event.html", title="Capture POD")

    is_ajax = request.headers.get("Accept") == "application/json"
    
    hwb_number = (request.form.get("hwb_number") or "").strip()
    action_type = request.form.get("action_type")
    recipient_name = (request.form.get("recipient_name") or "").strip()
    shipper = (request.form.get("shipper") or "").strip() or None
    consignee = (request.form.get("consignee") or "").strip() or None
    contact_name = (request.form.get("contact_name") or "").strip() or None
    phone = (request.form.get("phone") or "").strip() or None
    lat = request.form.get("latitude")
    lon = request.form.get("longitude")
    off_sheet_confirmed = (request.form.get("off_sheet_confirmed") or "").strip().lower() in {"1", "true", "yes", "on"}
    reassignment_note = (request.form.get("reassignment_note") or "").strip() or None

    if not hwb_number:
        message = {"error": "HWB number is required."}
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
            # Ensure stream starts at byte 0 to prevent accidental 0-byte uploads after intermediate handling.
            if not getattr(signature_file, "stream", None) or not hasattr(signature_file.stream, "seek"):
                raise ValueError("Signature stream is not seekable.")
            signature_file.stream.seek(0)
        except Exception as e:
            if is_ajax: return jsonify({"error": "Failed to decode signature"}), 400
            flash("Failed to process signature.")
            return redirect(url_for("paperwork.log_pod_event"))

    # 3. Database Insertion & Storage Logic Execution
    try:
        processed_count = submit_pod(
            hwb_number=hwb_number,
            action_type=action_type,
            recipient_name=recipient_name or None,
            pod_photo=pod_photo,
            signature_file=signature_file,
            latitude=lat,
            longitude=lon,
            shipper=shipper,
            consignee=consignee,
            contact_name=contact_name,
            phone=phone,
            off_sheet_confirmed=off_sheet_confirmed,
            reassignment_note=reassignment_note,
        )
        db.session.commit()
    except ShipmentTransitionError as e:
        db.session.rollback()
        if is_ajax:
            return jsonify({"error": str(e)}), 400
        flash(str(e))
        return redirect(url_for("paperwork.log_pod_event"))
    except ValueError as e:
        db.session.rollback()
        if is_ajax:
            return jsonify({"error": str(e)}), 400
        flash(str(e))
        return redirect(url_for("paperwork.log_pod_event"))
    except Exception as e:
        db.session.rollback()
        if is_ajax: return jsonify({"error": f"Transaction failed: {str(e)}"}), 500
        flash("Transaction failed. Please try again.")
        return redirect(url_for("paperwork.log_pod_event"))

    if is_ajax:
        return jsonify({"success": True, "message": f"Recorded event for {processed_count} shipments."}), 200

    flash(f"Recorded event for {processed_count} shipments.")
    return redirect(url_for("paperwork.log_pod_event"))


@paperwork_bp.post("/pod/scan")
@require_employee_approval()
def scan_hwb():
    payload = request.get_json(silent=True) or {}
    hwb_number = (payload.get("hwb_number") or "").strip()
    if not hwb_number:
        return jsonify({"error": "HWB number is required."}), 400

    target_load_entries = get_load_entries_by_identifier(hwb_number)
    if not target_load_entries:
        return jsonify(
            {
                "mode": "base",
                "hwb_number": hwb_number,
                "user_has_full_board_rights": is_ops_or_admin_user(),
                "is_assigned_to_current_user": False,
                "warning_required": False,
                "warning_message": "",
            }
        ), 200

    summary_entry = target_load_entries[0]
    user_has_full_board_rights = is_ops_or_admin_user()
    is_assigned_to_current_user = all(entry.assigned_driver == g.current_user.id for entry in target_load_entries)
    warning_required = not user_has_full_board_rights and not is_assigned_to_current_user
    shipment_count = len(target_load_entries)
    warning_message = (
        f"{shipment_count} load(s) are currently off-sheet for your driver assignment. "
        "Confirm to continue and reassign all matched loads to yourself."
        if warning_required
        else ""
    )

    return jsonify(
        {
            "mode": "enhanced",
            "hwb_number": hwb_number,
            "shipper": summary_entry.shipper,
            "consignee": summary_entry.consignee,
            "contact_name": summary_entry.contact_name,
            "phone": summary_entry.phone,
            "status": summary_entry.status,
            "user_has_full_board_rights": user_has_full_board_rights,
            "is_assigned_to_current_user": is_assigned_to_current_user,
            "warning_required": warning_required,
            "warning_message": warning_message,
            "shipment_count": shipment_count,
            "matched_by": "hwb" if shipment_count == 1 and summary_entry.hwb_number == hwb_number else "mawb",
            "hwbs": [entry.hwb_number for entry in target_load_entries if entry.hwb_number],
        }
    ), 200


@paperwork_bp.get("/help")
@require_employee_approval()
def help_page():
    return render_template(
        "paperwork/help.html",
        title="Help & Documentation",
        is_admin=is_admin_user(),
        is_ops=is_ops_or_admin_user(),
        role=current_user_role(),
    )


@paperwork_bp.get("/load-board")
@require_employee_approval()
def active_load_board():
    full_board_access = is_ops_or_admin_user()
    show_delivered = request.args.get("show_delivered", "0") == "1"
    show_cancelled = request.args.get("show_cancelled", "0") == "1"
    loads = query_loads(
        full_board_access,
        include_delivered=show_delivered,
        include_cancelled=show_cancelled,
    )

    latest_delivery_by_hwb: dict[str, PODRecord] = {}
    load_hwbs = [load.hwb_number for load in loads if load.hwb_number]
    if load_hwbs:
        pod_records = (
            PODRecord.query
            .filter(PODRecord.hwb_number.in_(load_hwbs))
            .order_by(PODRecord.id.desc())
            .all()
        )
        for pod_record in pod_records:
            if pod_record.hwb_number and pod_record.hwb_number not in latest_delivery_by_hwb:
                latest_delivery_by_hwb[pod_record.hwb_number] = pod_record

    if not show_delivered:
        now_utc = datetime.now(timezone.utc)
        visible_loads = []
        for load in loads:
            if load.status != "Delivered":
                visible_loads.append(load)
                continue

            pod_record = latest_delivery_by_hwb.get(load.hwb_number)
            delivered_at = pod_record.timestamp if pod_record else None
            if delivered_at and delivered_at.tzinfo is None:
                delivered_at = delivered_at.replace(tzinfo=timezone.utc)

            if delivered_at and (now_utc - delivered_at).total_seconds() > 4 * 60 * 60:
                continue
            visible_loads.append(load)
        loads = visible_loads

    for load in loads:
        pod_record = latest_delivery_by_hwb.get(load.hwb_number)
        if pod_record:
            load.pod_delivery_photo = pod_record.delivery_photo
            load.pod_signature_image = pod_record.signature_image
            load.pod_recipient_name = pod_record.recipient_name
        else:
            load.pod_delivery_photo = None
            load.pod_signature_image = None
            load.pod_recipient_name = None

    assigned_driver_ids = {
        load.assigned_driver
        for load in loads
        if getattr(load, "assigned_driver", None) is not None
    }
    users_by_id = {
        user.id: user
        for user in User.query.filter(User.id.in_(assigned_driver_ids)).all()
    } if assigned_driver_ids else {}

    for load in loads:
        assigned_driver_id = getattr(load, "assigned_driver", None)
        assigned_driver = users_by_id.get(assigned_driver_id)
        if not assigned_driver:
            load.current_leg_driver_name = "—"
            continue

        load.current_leg_driver_name = (
            getattr(assigned_driver, "full_name", None)
            or assigned_driver.name
            or " ".join(part for part in [assigned_driver.first_name, assigned_driver.last_name] if part).strip()
            or assigned_driver.email
        )

    return render_template(
        "paperwork/load_board.html",
        title="Active Load Board",
        loads=loads,
        full_board_access=full_board_access,
        show_delivered=show_delivered,
        show_cancelled=show_cancelled,
    )


@paperwork_bp.post("/load-board/clear")
@require_employee_approval()
def clear_load_board():
    if not is_ops_or_admin_user():
        return jsonify({"error": "Ops or Admin access required."}), 403

    payload = request.get_json(silent=True) or {}
    target_hwb = (payload.get("hwb_number") or "").strip()
    resolution = (payload.get("resolution") or "CANCELLED").strip().upper()
    hard_delete = bool(payload.get("hard_delete", False))

    if not target_hwb:
        return jsonify({"error": "Target HWB or 'ALL' required."}), 400

    if resolution not in {"CANCELLED", "COMPLETED_3RD_PARTY"}:
        return jsonify({"error": "Invalid resolution type."}), 400

    def log_clearance(hwb_number: str, action_type: str) -> None:
        db.session.add(
            PODRecord(
                hwb_number=hwb_number,
                action_type=action_type,
                driver_id=g.current_user.id,
                recipient_name="SYSTEM_RESOLUTION",
                delivery_photo="N/A",
                signature_image="N/A",
                reassignment_note=f"Record resolved as {action_type} by User {g.current_user.id}",
            )
        )

    cleared_count = 0
    try:
        with db.session.begin_nested():
            if target_hwb == "ALL":
                shipments = Shipment.query.filter(
                    Shipment.overall_status.notin_([ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED])
                ).all()
                for shipment in shipments:
                    if hard_delete:
                        db.session.delete(shipment)
                    else:
                        shipment.overall_status = ShipmentStatus.CANCELLED
                        log_clearance(shipment.hwb_number, "CANCELLED")
                    cleared_count += 1
            else:
                shipment = Shipment.query.filter_by(hwb_number=target_hwb).first()
                if shipment and shipment.overall_status not in [ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]:
                    if hard_delete:
                        db.session.delete(shipment)
                    else:
                        mapped_shipment_status = (
                            ShipmentStatus.DELIVERED if resolution == "COMPLETED_3RD_PARTY" else ShipmentStatus.CANCELLED
                        )
                        shipment.overall_status = mapped_shipment_status
                        log_clearance(shipment.hwb_number, resolution)
                    cleared_count += 1

        db.session.commit()
        return jsonify({"success": True, "message": f"Successfully resolved {cleared_count} records as {resolution}."}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(exc)}"}), 500


@paperwork_bp.post("/load-board/upload-csv")
@require_employee_approval()
def upload_load_board_csv():
    unauthorized = require_ops_or_admin_or_redirect("paperwork.active_load_board")
    if unauthorized:
        return unauthorized

    csv_file = request.files.get("load_board_csv")
    if not csv_file or not csv_file.filename:
        flash("Please choose a CSV file to upload.")
        return redirect(url_for("paperwork.active_load_board"))

    try:
        csv_file.seek(0)
        decoded_lines = csv_file.read().decode("utf-8-sig").splitlines()
        header_index = None
        for index, line in enumerate(decoded_lines):
            if "HWB" in line and "Mawb#" in line:
                header_index = index
                break

        if header_index is None:
            flash("CSV is missing required headers.")
            return redirect(url_for("paperwork.active_load_board"))

        reader = csv.DictReader(decoded_lines[header_index:])
        rows = list(reader)
    except Exception:
        flash("Unable to read the CSV file. Ensure it is a valid format.")
        return redirect(url_for("paperwork.active_load_board"))

    required_fields = {
        "Mawb#",
        "HWB",
        "Org",
        "Dest",
    }
    if not rows:
        flash("CSV is empty or missing headers.")
        return redirect(url_for("paperwork.active_load_board"))

    csv_headers = set(rows[0].keys())
    if not required_fields.issubset(csv_headers):
        flash(
            "CSV is missing required headers: "
            "Mawb#, HWB, Org, Dest."
        )
        return redirect(url_for("paperwork.active_load_board"))

    csv_to_model_field_map = {
        "HWB": "hwb_number",
        "Mawb#": "mawb_number",
    }

    def build_address(row: dict[str, str | None], name_key: str, extra_keys: list[str]) -> str:
        name_value = (row.get(name_key) or "").strip()
        extra_parts = [(row.get(key) or "").strip() for key in extra_keys]
        extra_parts = [part for part in extra_parts if part]
        if extra_parts:
            return ", ".join([name_value, *extra_parts] if name_value else extra_parts)
        return name_value

    # Index active drivers by name and email for faster lookup
    all_drivers = User.query.filter_by(is_active=True).all()
    driver_map: dict[str, int] = {}
    for driver in all_drivers:
        # Map by standard name
        name_key = (driver.name or "").strip().lower()
        if name_key:
            driver_map[name_key] = driver.id

        # Map by email (standardized company format)
        email_key = (driver.email or "").strip().lower()
        if email_key:
            driver_map[email_key] = driver.id

    def resolve_driver_id(driver_name_raw: str | None) -> int | None:
        if not driver_name_raw:
            return None
        cleaned_name = str(driver_name_raw).strip().lower()
        if not cleaned_name:
            return None

        # Try 1: Direct name match (e.g., "mickey jadallah")
        if cleaned_name in driver_map:
            return driver_map[cleaned_name]

        # Try 2: Convert name to company email format (e.g., "david alexander" -> "david.alexander@freightservices.net")
        # Handles middle initials by replacing all spaces with dots
        email_format = cleaned_name.replace(" ", ".") + "@freightservices.net"
        if email_format in driver_map:
            return driver_map[email_format]

        return None

    def map_legacy_status_to_leg_state(legacy_status: str) -> dict:
        normalized_status = (legacy_status or "").strip()
        status_map = {
            "Awaiting Pickup": {
                "overall_status": ShipmentStatus.PENDING,
                "current_leg_index": 1,
                "leg1_status": "pending_or_assigned",
                "leg3_status": "pending_or_assigned",
            },
            "In Progress": {
                "overall_status": ShipmentStatus.IN_PROGRESS,
                "current_leg_index": 1,
                "leg1_status": ShipmentLegStatus.IN_PROGRESS,
                "leg3_status": "pending_or_assigned",
            },
            "Picked Up": {
                "overall_status": ShipmentStatus.PICKED_UP,
                "current_leg_index": 2,
                "leg1_status": ShipmentLegStatus.COMPLETED,
                "leg3_status": "pending_or_assigned",
            },
            "Delivered": {
                "overall_status": ShipmentStatus.DELIVERED,
                "current_leg_index": 3,
                "leg1_status": ShipmentLegStatus.COMPLETED,
                "leg3_status": ShipmentLegStatus.COMPLETED,
            },
        }
        return status_map.get(normalized_status, status_map["Awaiting Pickup"])

    iata_pattern = re.compile(r"^[A-Z]{3}$")
    row_errors: list[str] = []
    parsed_rows: list[dict] = []
    seen_hwb_numbers: set[str] = set()

    for index, row in enumerate(rows, start=(header_index or 0) + 2):
        row_issue_list: list[str] = []

        mawb_number = (row.get("Mawb#") or "").strip()
        hwb_number = (row.get("HWB") or "").strip()
        shipper_address = build_address(row, "Shipper Name", ["Shipper Address1", "S-City", "S-State", "S-Zip"])
        consignee_address = build_address(row, "Consignee Name", ["Consignee Address 1", "C-City", "C-State", "C-Zip"])
        origin_airport = (row.get("Org") or "").strip().upper()
        destination_airport = (row.get("Dest") or "").strip().upper()
        raw_status = row.get("Status") or row.get("status")
        status = raw_status.strip() if raw_status and raw_status.strip() else "Awaiting Pickup"

        if not mawb_number:
            row_issue_list.append("mawb_number is required")
        if not hwb_number:
            row_issue_list.append("hwb_number is required")
        if not shipper_address:
            row_issue_list.append("shipper_address is required")
        if not consignee_address:
            row_issue_list.append("consignee_address is required")
        if not iata_pattern.match(origin_airport):
            row_issue_list.append("origin_airport must be a non-empty 3-letter uppercase IATA code")
        if not iata_pattern.match(destination_airport):
            row_issue_list.append("destination_airport must be a non-empty 3-letter uppercase IATA code")

        if hwb_number in seen_hwb_numbers:
            row_issue_list.append("duplicate hwb_number in CSV")
        elif hwb_number:
            seen_hwb_numbers.add(hwb_number)

        first_mile_driver = resolve_driver_id(row.get("PU Driver"))
        last_mile_driver = resolve_driver_id(row.get("DEL Driver"))

        if row_issue_list:
            row_errors.append(f"Row {index}: {'; '.join(row_issue_list)}")
            continue

        parsed_rows.append(
            {
                csv_to_model_field_map["Mawb#"]: mawb_number,
                csv_to_model_field_map["HWB"]: hwb_number,
                "shipper_address": shipper_address,
                "consignee_address": consignee_address,
                "origin_airport": origin_airport,
                "destination_airport": destination_airport,
                "status": status,
                "first_mile_driver_id": first_mile_driver,
                "last_mile_driver_id": last_mile_driver,
            }
        )

    upserted_count = 0
    invalid_hwb_numbers: set[str] = set()
    if parsed_rows:
        mawb_numbers = {item["mawb_number"] for item in parsed_rows}
        hwb_numbers = {item["hwb_number"] for item in parsed_rows}
        shipment_groups = {
            group.mawb_number: group
            for group in ShipmentGroup.query.filter(ShipmentGroup.mawb_number.in_(mawb_numbers)).all()
        }
        shipments = {
            shipment.hwb_number: shipment
            for shipment in Shipment.query.filter(Shipment.hwb_number.in_(hwb_numbers)).all()
        }

        for parsed_row in parsed_rows:
            existing_shipment = shipments.get(parsed_row["hwb_number"])
            if (
                existing_shipment
                and existing_shipment.overall_status not in {ShipmentStatus.CANCELLED, ShipmentStatus.DELIVERED}
                and existing_shipment.shipment_group
                and existing_shipment.shipment_group.mawb_number != parsed_row["mawb_number"]
            ):
                row_errors.append(
                    f"Row for HWB {parsed_row['hwb_number']}: hwb_number already belongs to active shipment "
                    f"under MAWB {existing_shipment.shipment_group.mawb_number}."
                )
                invalid_hwb_numbers.add(parsed_row["hwb_number"])

    applied_rows = [row for row in parsed_rows if row["hwb_number"] not in invalid_hwb_numbers]

    if applied_rows:
        try:
            with db.session.begin_nested():
                for parsed_row in applied_rows:
                    now_utc = datetime.now(timezone.utc)
                    shipment_group = ShipmentGroup.query.filter_by(mawb_number=parsed_row["mawb_number"]).first()
                    if not shipment_group:
                        shipment_group = ShipmentGroup(
                            mawb_number=parsed_row["mawb_number"],
                            carrier="CSV_IMPORT",
                        )
                        db.session.add(shipment_group)
                        db.session.flush()

                    shipment_group.origin_airport = parsed_row["origin_airport"]
                    shipment_group.destination_airport = parsed_row["destination_airport"]

                    shipment = Shipment.query.filter_by(hwb_number=parsed_row["hwb_number"]).first()
                    if not shipment:
                        shipment = Shipment(
                            hwb_number=parsed_row["hwb_number"],
                            shipment_group_id=shipment_group.id,
                        )
                        db.session.add(shipment)
                        db.session.flush()

                    shipment.shipment_group_id = shipment_group.id
                    shipment.shipper_address = parsed_row["shipper_address"]
                    shipment.consignee_address = parsed_row["consignee_address"]
                    status_reconciliation = map_legacy_status_to_leg_state(parsed_row["status"])
                    shipment.overall_status = status_reconciliation["overall_status"]
                    shipment.current_leg_index = status_reconciliation["current_leg_index"]

                    legs_by_sequence = {leg.leg_sequence: leg for leg in shipment.legs}
                    if 1 not in legs_by_sequence:
                        leg1 = ShipmentLeg(
                            shipment_id=shipment.id,
                            leg_sequence=1,
                            leg_type=ShipmentLegType.PICKUP_TO_ORIGIN_AIRPORT,
                            from_location_type="SHIPPER",
                            to_location_type="ORIGIN_AIRPORT",
                            from_address=parsed_row["shipper_address"],
                            to_airport=parsed_row["origin_airport"],
                            assigned_driver_id=parsed_row["first_mile_driver_id"],
                            status=ShipmentLegStatus.ASSIGNED if parsed_row["first_mile_driver_id"] else ShipmentLegStatus.PENDING,
                        )
                        db.session.add(leg1)
                        legs_by_sequence[1] = leg1

                    if 2 not in legs_by_sequence:
                        leg2 = ShipmentLeg(
                            shipment_id=shipment.id,
                            leg_sequence=2,
                            leg_type=ShipmentLegType.AIRPORT_TO_AIRPORT,
                            from_location_type="ORIGIN_AIRPORT",
                            to_location_type="DESTINATION_AIRPORT",
                            from_airport=parsed_row["origin_airport"],
                            to_airport=parsed_row["destination_airport"],
                            status=ShipmentLegStatus.PENDING,
                        )
                        db.session.add(leg2)
                        legs_by_sequence[2] = leg2

                    if 3 not in legs_by_sequence:
                        leg3 = ShipmentLeg(
                            shipment_id=shipment.id,
                            leg_sequence=3,
                            leg_type=ShipmentLegType.DEST_AIRPORT_TO_CONSIGNEE,
                            from_location_type="DESTINATION_AIRPORT",
                            to_location_type="CONSIGNEE",
                            from_airport=parsed_row["destination_airport"],
                            to_address=parsed_row["consignee_address"],
                            assigned_driver_id=parsed_row["last_mile_driver_id"],
                            status=ShipmentLegStatus.ASSIGNED if parsed_row["last_mile_driver_id"] else ShipmentLegStatus.PENDING,
                        )
                        db.session.add(leg3)
                        legs_by_sequence[3] = leg3

                    leg1 = legs_by_sequence[1]
                    leg3 = legs_by_sequence[3]

                    # Force CSV data to overwrite existing database assignments unconditionally
                    leg1.assigned_driver_id = parsed_row["first_mile_driver_id"]
                    leg3.assigned_driver_id = parsed_row["last_mile_driver_id"]

                    # Align leg status with the newly assigned driver state
                    if leg1.status in {ShipmentLegStatus.PENDING, ShipmentLegStatus.ASSIGNED}:
                        leg1.status = ShipmentLegStatus.ASSIGNED if leg1.assigned_driver_id else ShipmentLegStatus.PENDING

                    if leg3.status in {ShipmentLegStatus.PENDING, ShipmentLegStatus.ASSIGNED}:
                        leg3.status = ShipmentLegStatus.ASSIGNED if leg3.assigned_driver_id else ShipmentLegStatus.PENDING

                    for leg, desired_state in (
                        (leg1, status_reconciliation["leg1_status"]),
                        (leg3, status_reconciliation["leg3_status"]),
                    ):
                        if desired_state == "pending_or_assigned":
                            leg.status = ShipmentLegStatus.ASSIGNED if leg.assigned_driver_id else ShipmentLegStatus.PENDING
                            leg.started_at_utc = None
                            leg.completed_at_utc = None
                            continue

                        if desired_state == ShipmentLegStatus.IN_PROGRESS and leg.status == ShipmentLegStatus.COMPLETED:
                            continue

                        leg.status = desired_state
                        if desired_state == ShipmentLegStatus.IN_PROGRESS:
                            leg.started_at_utc = leg.started_at_utc or now_utc
                            leg.completed_at_utc = None
                        elif desired_state == ShipmentLegStatus.COMPLETED:
                            leg.started_at_utc = leg.started_at_utc or now_utc
                            leg.completed_at_utc = leg.completed_at_utc or now_utc

                    # Guardrail: downstream POD workflow transitions validate leg state, not only shipment.overall_status.
                    # Keep this importer leg-first so repeated CSV upserts remain safe and deterministic.

                    upserted_count += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Load board CSV failed due to a transaction error. No rows were applied.")
            return redirect(url_for("paperwork.active_load_board"))

    flash(f"Load board CSV processed. {upserted_count} rows applied.")
    for row_error in row_errors:
        flash(row_error)
    return redirect(url_for("paperwork.active_load_board"))


@paperwork_bp.get("/pod/history")
@require_employee_approval()
def pod_history():
    has_full_history_access = is_ops_or_admin_user()
    query = PODRecord.query.order_by(PODRecord.id.desc())
    if not has_full_history_access:
        query = query.filter_by(driver_id=g.current_user.id)

    records = query.limit(100).all()

    return render_template(
        "paperwork/pod_history.html",
        title="POD History" if has_full_history_access else "My POD History",
        records=records,
        has_full_history_access=has_full_history_access,
    )


@paperwork_bp.get("/pod/history/export")
@require_employee_approval()
def pod_history_export():
    unauthorized = require_ops_or_admin_or_redirect("paperwork.pod_history")
    if unauthorized:
        return unauthorized

    start_dt_raw = request.args.get("start")
    end_dt_raw = request.args.get("end")

    query = PODRecord.query.order_by(PODRecord.timestamp.desc())
    try:
        start_dt = parse_iso_datetime(start_dt_raw) if start_dt_raw else None
        end_dt = parse_iso_datetime(end_dt_raw) if end_dt_raw else None
    except ValueError:
        flash("Invalid date format. Use ISO date values.")
        return redirect(url_for("paperwork.pod_history"))

    if start_dt:
        query = query.filter(PODRecord.timestamp >= start_dt)
    if end_dt:
        query = query.filter(PODRecord.timestamp <= end_dt)

    filename = "pod_history_full.csv"
    if start_dt or end_dt:
        filename = "pod_history_ranged.csv"

    return pod_history_csv_response(query.all(), filename)


@paperwork_bp.get("/POD/<path:filename>")
@require_employee_approval()
def serve_pod_file(filename: str):
    return send_from_directory("/POD", filename)

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
    # Only allow users designated for ops or admins to view dashboard.
    if not is_ops_or_admin_user():
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
