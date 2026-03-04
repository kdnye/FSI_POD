from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.services.tasks import enqueue_email_task
from models import Shipment, ShipmentLeg, ShipmentLegStatus, ShipmentLegTransition, ShipmentStatus


class ShipmentTransitionError(ValueError):
    """Raised when a POD action does not match the next valid shipment transition."""


ACTION_ALIASES = {
    "PICKUP": "SHIPPER_PICKUP",
    "DELIVERY": "CONSIGNEE_DROP",
    "SHIPPER PICKUP": "SHIPPER_PICKUP",
    "SHIPPER_PICKUP": "SHIPPER_PICKUP",
    "ORIGIN AIRPORT DROP": "ORIGIN_AIRPORT_DROP",
    "ORIGIN_AIRPORT_DROP": "ORIGIN_AIRPORT_DROP",
    "DESTINATION AIRPORT PICKUP": "DESTINATION_AIRPORT_PICKUP",
    "DESTINATION_AIRPORT_PICKUP": "DESTINATION_AIRPORT_PICKUP",
    "CONSIGNEE DROP": "CONSIGNEE_DROP",
    "CONSIGNEE_DROP": "CONSIGNEE_DROP",
}


def normalize_pod_action(action_type: str) -> str:
    normalized = str(action_type or "").strip().upper().replace("-", " ")
    canonical = ACTION_ALIASES.get(normalized)
    if not canonical:
        raise ShipmentTransitionError(
            "Invalid POD action. Use shipper pickup, origin airport drop, destination airport pickup, or consignee drop."
        )
    return canonical


def _record_leg_transition(
    *,
    shipment: Shipment,
    leg: ShipmentLeg,
    actor_user_id: int,
    pod_action: str,
    from_status: ShipmentLegStatus,
    to_status: ShipmentLegStatus,
    latitude: str | None,
    longitude: str | None,
    event_at_utc: datetime,
) -> None:
    db.session.add(
        ShipmentLegTransition(
            shipment_id=shipment.id,
            shipment_leg_id=leg.id,
            actor_user_id=actor_user_id,
            pod_action=pod_action,
            from_status=from_status,
            to_status=to_status,
            latitude=latitude,
            longitude=longitude,
            event_at_utc=event_at_utc,
        )
    )


def _resolve_location_name(action: str, leg1: ShipmentLeg | None, leg3: ShipmentLeg | None) -> str | None:
    if action == "SHIPPER_PICKUP" and leg1:
        return leg1.from_address or leg1.to_address
    if action == "ORIGIN_AIRPORT_DROP" and leg1:
        return leg1.to_address or leg1.from_address
    if action == "DESTINATION_AIRPORT_PICKUP" and leg3:
        return leg3.from_address or leg3.to_address
    if action == "CONSIGNEE_DROP" and leg3:
        return leg3.to_address or leg3.from_address
    return None


def _enqueue_pod_notification(
    *,
    shipment: Shipment,
    action: str,
    actor_user_id: int,
    leg1: ShipmentLeg | None,
    leg3: ShipmentLeg | None,
    photo_blob_name: str | None,
    signature_blob_name: str | None,
) -> None:
    enqueue_email_task(
        shipment_id=shipment.id,
        action_type=action,
        actor_user_id=actor_user_id,
        hwb_number=shipment.hwb_number,
        location_name=_resolve_location_name(action, leg1, leg3),
        photo_blob_name=photo_blob_name,
        signature_blob_name=signature_blob_name,
        shipper_email=shipment.shipper_email,
        consignee_email=shipment.consignee_email,
    )


def apply_pod_transition(
    *,
    shipment: Shipment,
    action_type: str,
    actor_user_id: int,
    latitude: str | None = None,
    longitude: str | None = None,
    photo_blob_name: str | None = None,
    signature_blob_name: str | None = None,
) -> str:
    action = normalize_pod_action(action_type)
    legs_by_sequence = {leg.leg_sequence: leg for leg in shipment.legs}
    leg1 = legs_by_sequence.get(1)
    leg3 = legs_by_sequence.get(3)
    now_utc = datetime.now(timezone.utc)

    if action == "SHIPPER_PICKUP":
        if not leg1:
            raise ShipmentTransitionError("Cannot start shipper pickup: shipment leg 1 is missing.")
        if leg1.status == ShipmentLegStatus.COMPLETED:
            raise ShipmentTransitionError("Cannot start shipper pickup: leg 1 is already completed.")

        leg1.assigned_driver_id = actor_user_id

        from_status = leg1.status
        if leg1.status in {ShipmentLegStatus.PENDING, ShipmentLegStatus.ASSIGNED}:
            leg1.status = ShipmentLegStatus.IN_PROGRESS
            leg1.started_at_utc = leg1.started_at_utc or now_utc

        shipment.current_leg_index = 1
        shipment.overall_status = ShipmentStatus.IN_PROGRESS
        _record_leg_transition(
            shipment=shipment,
            leg=leg1,
            actor_user_id=actor_user_id,
            pod_action=action,
            from_status=from_status,
            to_status=leg1.status,
            latitude=latitude,
            longitude=longitude,
            event_at_utc=now_utc,
        )
        _enqueue_pod_notification(
            shipment=shipment,
            action=action,
            actor_user_id=actor_user_id,
            leg1=leg1,
            leg3=leg3,
            photo_blob_name=photo_blob_name,
            signature_blob_name=signature_blob_name,
        )
        return action

    if action == "ORIGIN_AIRPORT_DROP":
        if not leg1:
            raise ShipmentTransitionError("Cannot complete origin airport drop: shipment leg 1 is missing.")
        if leg1.status != ShipmentLegStatus.IN_PROGRESS:
            raise ShipmentTransitionError("Cannot complete origin airport drop before shipper pickup is in progress.")

        from_status = leg1.status
        leg1.status = ShipmentLegStatus.COMPLETED
        leg1.completed_at_utc = now_utc
        shipment.current_leg_index = 2
        shipment.overall_status = ShipmentStatus.PICKED_UP
        _record_leg_transition(
            shipment=shipment,
            leg=leg1,
            actor_user_id=actor_user_id,
            pod_action=action,
            from_status=from_status,
            to_status=leg1.status,
            latitude=latitude,
            longitude=longitude,
            event_at_utc=now_utc,
        )
        _enqueue_pod_notification(
            shipment=shipment,
            action=action,
            actor_user_id=actor_user_id,
            leg1=leg1,
            leg3=leg3,
            photo_blob_name=photo_blob_name,
            signature_blob_name=signature_blob_name,
        )
        return action

    if action == "DESTINATION_AIRPORT_PICKUP":
        if not leg1 or leg1.status != ShipmentLegStatus.COMPLETED:
            raise ShipmentTransitionError("Cannot mark destination-airport pickup before origin-airport drop.")
        if not leg3:
            raise ShipmentTransitionError("Cannot start destination-airport pickup: shipment leg 3 is missing.")
        if leg3.status == ShipmentLegStatus.COMPLETED:
            raise ShipmentTransitionError("Cannot start destination-airport pickup: final leg is already completed.")

        leg3.assigned_driver_id = actor_user_id

        from_status = leg3.status
        if leg3.status in {ShipmentLegStatus.PENDING, ShipmentLegStatus.ASSIGNED}:
            leg3.status = ShipmentLegStatus.IN_PROGRESS
            leg3.started_at_utc = leg3.started_at_utc or now_utc

        shipment.current_leg_index = 3
        shipment.overall_status = ShipmentStatus.IN_PROGRESS
        _record_leg_transition(
            shipment=shipment,
            leg=leg3,
            actor_user_id=actor_user_id,
            pod_action=action,
            from_status=from_status,
            to_status=leg3.status,
            latitude=latitude,
            longitude=longitude,
            event_at_utc=now_utc,
        )
        _enqueue_pod_notification(
            shipment=shipment,
            action=action,
            actor_user_id=actor_user_id,
            leg1=leg1,
            leg3=leg3,
            photo_blob_name=photo_blob_name,
            signature_blob_name=signature_blob_name,
        )
        return action

    if action == "CONSIGNEE_DROP":
        if not leg3 or leg3.status != ShipmentLegStatus.IN_PROGRESS:
            raise ShipmentTransitionError("Cannot mark consignee drop before destination-airport pickup.")

        from_status = leg3.status
        leg3.status = ShipmentLegStatus.COMPLETED
        leg3.completed_at_utc = now_utc
        shipment.current_leg_index = 3
        shipment.overall_status = ShipmentStatus.DELIVERED
        _record_leg_transition(
            shipment=shipment,
            leg=leg3,
            actor_user_id=actor_user_id,
            pod_action=action,
            from_status=from_status,
            to_status=leg3.status,
            latitude=latitude,
            longitude=longitude,
            event_at_utc=now_utc,
        )
        _enqueue_pod_notification(
            shipment=shipment,
            action=action,
            actor_user_id=actor_user_id,
            leg1=leg1,
            leg3=leg3,
            photo_blob_name=photo_blob_name,
            signature_blob_name=signature_blob_name,
        )
        return action

    raise ShipmentTransitionError("Unsupported POD transition requested.")
