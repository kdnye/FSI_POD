from __future__ import annotations

from email.utils import parseaddr

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
ALLOWED_SHIPMENT_ALERT_ACTIONS = frozenset(_ACTION_TO_SETTING)


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
    for email in [driver_email, shipper_email, consignee_email, *_parse_custom_cc_emails(settings.custom_cc_emails)]:
        if _is_valid_email(email):
            recipients.append(email.strip())

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

    payload = {
        "From": from_email,
        "To": ",".join(deduped),
        "TemplateAlias": "pod-event-notification",
        "TemplateModel": {
            "action_name": action_display,
            "hwb_number": hwb_number or "",
            "timestamp": timestamp,
            "location_name": location_name or "",
            "driver_name": driver_name or "",
            "photo_url": photo_url or "",
            "signature_url": signature_url or "",
        },
        "MessageStream": "pod",  # Added to route via the dedicated pod stream
    }

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
        current_app.logger.exception(
            "Shipment alert failed: Postmark request exception action_type=%s hwb_number=%s error=%s",
            action,
            hwb_number,
            exc,
        )
        return False, "credential_or_config_issue"

    return True, "sent"
