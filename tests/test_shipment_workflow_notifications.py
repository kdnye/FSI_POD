from app import db
from app.services.shipment_workflow import apply_pod_transition
from models import Shipment, ShipmentGroup, ShipmentLeg, ShipmentLegStatus, ShipmentLegType, User


def test_apply_pod_transition_triggers_notification(monkeypatch, app):
    with app.app_context():
        driver = User(email="workflow-driver@example.com", password_hash="hash", employee_approved=True)
        db.session.add(driver)
        db.session.flush()

        group = ShipmentGroup(mawb_number="MAWB-WF-NOTIFY", carrier="TEST")
        db.session.add(group)
        db.session.flush()

        shipment = Shipment(
            hwb_number="HWB-WF-NOTIFY",
            shipment_group_id=group.id,
            shipper_email="shipper@example.com",
            consignee_email="consignee@example.com",
        )
        db.session.add(shipment)
        db.session.flush()

        db.session.add(
            ShipmentLeg(
                shipment_id=shipment.id,
                leg_sequence=1,
                leg_type=ShipmentLegType.PICKUP_TO_ORIGIN_AIRPORT,
                status=ShipmentLegStatus.ASSIGNED,
                assigned_driver_id=driver.id,
            )
        )
        db.session.commit()

        calls = []

        def _fake_enqueue(payload):
            calls.append(
                (
                    payload.shipment_id,
                    payload.action_type,
                    payload.actor_user_id,
                    payload.driver_email,
                    payload.shipper_email,
                    payload.consignee_email,
                )
            )

        monkeypatch.setattr("app.services.shipment_workflow.enqueue_email_task", _fake_enqueue)

        apply_pod_transition(shipment=shipment, action_type="SHIPPER_PICKUP", actor_user_id=driver.id)

        assert calls == [
            (
                shipment.id,
                "SHIPPER_PICKUP",
                driver.id,
                "workflow-driver@example.com",
                "shipper@example.com",
                "consignee@example.com",
            )
        ]


def test_shipper_pickup_reassigns_leg_1_to_scanning_driver(monkeypatch, app):
    monkeypatch.setattr("app.services.shipment_workflow.enqueue_email_task", lambda _payload: None)
    with app.app_context():
        original_driver = User(email="workflow-leg1-original@example.com", password_hash="hash", employee_approved=True)
        scanning_driver = User(email="workflow-leg1-scan@example.com", password_hash="hash", employee_approved=True)
        db.session.add_all([original_driver, scanning_driver])
        db.session.flush()

        group = ShipmentGroup(mawb_number="MAWB-WF-LEG1", carrier="TEST")
        db.session.add(group)
        db.session.flush()

        shipment = Shipment(hwb_number="HWB-WF-LEG1", shipment_group_id=group.id)
        db.session.add(shipment)
        db.session.flush()

        leg1 = ShipmentLeg(
            shipment_id=shipment.id,
            leg_sequence=1,
            leg_type=ShipmentLegType.PICKUP_TO_ORIGIN_AIRPORT,
            status=ShipmentLegStatus.ASSIGNED,
            assigned_driver_id=original_driver.id,
        )
        db.session.add(leg1)
        db.session.commit()

        apply_pod_transition(shipment=shipment, action_type="SHIPPER_PICKUP", actor_user_id=scanning_driver.id)

        assert leg1.assigned_driver_id == scanning_driver.id


def test_destination_pickup_reassigns_leg_3_to_scanning_driver(monkeypatch, app):
    monkeypatch.setattr("app.services.shipment_workflow.enqueue_email_task", lambda _payload: None)
    with app.app_context():
        pickup_driver = User(email="workflow-leg3-pickup@example.com", password_hash="hash", employee_approved=True)
        original_delivery_driver = User(email="workflow-leg3-original@example.com", password_hash="hash", employee_approved=True)
        scanning_delivery_driver = User(email="workflow-leg3-scan@example.com", password_hash="hash", employee_approved=True)
        db.session.add_all([pickup_driver, original_delivery_driver, scanning_delivery_driver])
        db.session.flush()

        group = ShipmentGroup(mawb_number="MAWB-WF-LEG3", carrier="TEST")
        db.session.add(group)
        db.session.flush()

        shipment = Shipment(hwb_number="HWB-WF-LEG3", shipment_group_id=group.id)
        db.session.add(shipment)
        db.session.flush()

        leg1 = ShipmentLeg(
            shipment_id=shipment.id,
            leg_sequence=1,
            leg_type=ShipmentLegType.PICKUP_TO_ORIGIN_AIRPORT,
            status=ShipmentLegStatus.COMPLETED,
            assigned_driver_id=pickup_driver.id,
        )
        leg3 = ShipmentLeg(
            shipment_id=shipment.id,
            leg_sequence=3,
            leg_type=ShipmentLegType.DEST_AIRPORT_TO_CONSIGNEE,
            status=ShipmentLegStatus.ASSIGNED,
            assigned_driver_id=original_delivery_driver.id,
        )
        db.session.add_all([leg1, leg3])
        db.session.commit()

        apply_pod_transition(
            shipment=shipment,
            action_type="DESTINATION_AIRPORT_PICKUP",
            actor_user_id=scanning_delivery_driver.id,
        )

        assert leg3.assigned_driver_id == scanning_delivery_driver.id
