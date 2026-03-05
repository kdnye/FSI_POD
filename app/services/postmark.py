from __future__ import annotations

from email.utils import parseaddr

import base64
import os

import requests
from flask import current_app

from models import NotificationSettings

POSTMARK_EMAIL_ENDPOINT = "https://api.postmarkapp.com/email/withTemplate"
_ACTION_TO_SETTING = {
    "SHIPPER_PICKUP": "notify_shipper_pickup",
    "ORIGIN_AIRPORT_DROP": "notify_origin_drop",
    "DEST_AIRPORT_PICKUP": "notify_dest_pickup",
    "CONSIGNEE_DROP": "notify_consignee_drop",
}
_ACTION_TO_TEMPLATE = {
    "SHIPPER_PICKUP": "pod-transit-notification",
    "ORIGIN_AIRPORT_DROP": "pod-transit-notification",
    "DEST_AIRPORT_PICKUP": "pod-transit-notification",
    "CONSIGNEE_DROP": "pod-delivery-notification",
}
ALLOWED_SHIPMENT_ALERT_ACTIONS = frozenset(_ACTION_TO_SETTING)


def _create_inline_attachment(blob_name: str | None) -> dict | None:
    if not blob_name or str(blob_name).startswith("http"):
        return None

    clean_blob = str(blob_name).replace("gs://fsi-pod/", "").replace("POD/", "").lstrip("/")
    file_path = os.path.join("/POD", clean_blob)

    if not os.path.exists(file_path):
        current_app.logger.warning("Attachment bypassed: Local file not found at %s", file_path)
        return None

    try:
        with open(file_path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("utf-8")

        filename = os.path.basename(file_path)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        content_type = "image/png" if ext == "png" else "image/jpeg"

        return {
            "Name": filename,
            "Content": b64_content,
            "ContentType": content_type,
            "ContentID": f"cid:{filename}",
        }
    except Exception as e:
        current_app.logger.error("Attachment encoding failed for %s: %s", file_path, e)
        return None


def _is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    candidate = email.strip()
    if not candidate:
        return False
    _, parsed = parseaddr(candidate)
    return bool(parsed and "@" in parsed and " " not in parsed)


def _parse_custom_cc_emails(raw_emails: str | None) -> list[str]:
    if not raw_emails:
        return []

    valid: list[str] = []
    for entry in raw_emails.split(","):
        candidate = entry.strip()
        if _is_valid_email(candidate):
            valid.append(candidate)
    return valid


def send_shipment_alert(
    action_type,
    hwb_number,
    location_name,
    driver_email,
    driver_name,
    photo_url,
    signature_url,
    shipper_email,
    consignee_email,
    timestamp,
):
    action = str(action_type or "").strip().upper()
    setting_name = _ACTION_TO_SETTING.get(action)
    if not setting_name:
        current_app.logger.warning("Shipment alert skipped: unsupported action_type=%s hwb_number=%s", action_type, hwb_number)
        return False, "unsupported_action_type"

    settings = NotificationSettings.query.first()
    if settings is None or not getattr(settings, setting_name, False):
        current_app.logger.warning(
            "Shipment alert skipped: notifications disabled action_type=%s hwb_number=%s setting=%s",
            action,
            hwb_number,
            setting_name,
        )
        return False, "disabled_settings"

    recipients: list[str] = []
    check_list = {
        "Driver": driver_email,
        "Shipper": shipper_email,
        "Consignee": consignee_email,
    }
    for role, email in check_list.items():
        if _is_valid_email(email):
            recipients.append(email.strip())
        else:
            current_app.logger.info(
                "Shipment alert %s: %s email is missing or invalid: %s",
                hwb_number,
                role,
                email,
            )

    recipients.extend(_parse_custom_cc_emails(settings.custom_cc_emails))

    deduped: list[str] = []
    seen: set[str] = set()
    for email in recipients:
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(email)

    if not deduped:
        current_app.logger.warning(
            "Shipment alert skipped: no valid recipients action_type=%s hwb_number=%s",
            action,
            hwb_number,
        )
        return False, "missing_recipients"

    postmark_token = current_app.config.get("POSTMARK_SERVER_TOKEN", "").strip()
    from_email = current_app.config.get("POSTMARK_FROM_EMAIL", "").strip()
    if not postmark_token or not from_email:
        current_app.logger.error(
            "Shipment alert failed: missing Postmark credentials/config action_type=%s hwb_number=%s",
            action,
            hwb_number,
        )
        return False, "credential_or_config_issue"

    action_display = action.replace("_", " ").title().replace("Dest", "Destination")
    template_alias = _ACTION_TO_TEMPLATE.get(action, "pod-transit-notification")

    template_model = {
        "action_name": action_display,
        "hwb_number": hwb_number or "N/A",
        "timestamp": timestamp,
        "location_name": location_name or "N/A",
        "driver_name": driver_name or "N/A",
    }

    attachments = []

    if action == "CONSIGNEE_DROP":
        photo_att = _create_inline_attachment(photo_url)
        if photo_att:
            attachments.append(photo_att)
            template_model["photo_url"] = photo_att["ContentID"]

        sig_att = _create_inline_attachment(signature_url)
        if sig_att:
            attachments.append(sig_att)
            template_model["signature_url"] = sig_att["ContentID"]

    payload = {
        "From": from_email,
        "To": ",".join(deduped),
        "TemplateAlias": template_alias,
        "TemplateModel": template_model,
        "MessageStream": "pod",
    }

    if attachments:
        payload["Attachments"] = attachments

    try:
        response = requests.post(
            POSTMARK_EMAIL_ENDPOINT,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": postmark_token,
            },
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        error_body = exc.response.text if exc.response is not None else str(exc)
        current_app.logger.error(
            "Shipment alert failed: Postmark exception action_type=%s hwb_number=%s details=%s",
            action,
            hwb_number,
            error_body,
        )
        return False, "postmark_api_rejection"

    return True, "sent"
