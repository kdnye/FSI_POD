from __future__ import annotations

from email.utils import parseaddr

import requests
from flask import current_app

from models import NotificationSettings

POSTMARK_EMAIL_ENDPOINT = "https://api.postmarkapp.com/email"
_ACTION_TO_SETTING = {
    "SHIPPER_PICKUP": "notify_shipper_pickup",
    "ORIGIN_AIRPORT_DROP": "notify_origin_drop",
    "DESTINATION_AIRPORT_PICKUP": "notify_dest_pickup",
    "CONSIGNEE_DROP": "notify_consignee_drop",
}


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

    emails: list[str] = []
    for part in raw_emails.split(","):
        email = part.strip()
        if _is_valid_email(email):
            emails.append(email)
    return emails


def send_shipment_alert(
    shipment_id,
    action_type,
    driver_user,
    shipper_email=None,
    consignee_email=None,
):
    action = str(action_type or "").strip().upper()
    setting_name = _ACTION_TO_SETTING.get(action)
    if not setting_name:
        return False

    settings = NotificationSettings.query.order_by(NotificationSettings.id.asc()).first()
    if settings is None or not getattr(settings, setting_name, False):
        return False

    recipients: list[str] = []
    if _is_valid_email(getattr(driver_user, "email", None)):
        recipients.append(driver_user.email.strip())
    if _is_valid_email(shipper_email):
        recipients.append(shipper_email.strip())
    if _is_valid_email(consignee_email):
        recipients.append(consignee_email.strip())

    recipients.extend(_parse_custom_cc_emails(settings.custom_cc_emails))

    unique_recipients: list[str] = []
    seen: set[str] = set()
    for recipient in recipients:
        normalized = recipient.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_recipients.append(recipient)

    if not unique_recipients:
        return False

    postmark_token = current_app.config.get("POSTMARK_SERVER_TOKEN", "").strip()
    from_email = current_app.config.get("POSTMARK_FROM_EMAIL", "").strip()
    if not postmark_token or not from_email:
        current_app.logger.warning("Skipping shipment alert: Postmark credentials are missing.")
        return False

    payload = {
        "From": from_email,
        "To": unique_recipients[0],
        "Cc": ",".join(unique_recipients[1:]) if len(unique_recipients) > 1 else "",
        "Subject": f"Shipment {shipment_id} update: {action.replace('_', ' ').title()}",
        "TextBody": (
            f"Shipment {shipment_id} recorded event: {action.replace('_', ' ').title()}.\n"
            "This notification was generated automatically by FSI POD workflow."
        ),
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
        current_app.logger.exception("Failed to send Postmark shipment alert for shipment %s: %s", shipment_id, exc)
        return False

    return True
