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

        def _fake_send(shipment_id, action_type, driver_user, shipper_email=None, consignee_email=None):
            calls.append((shipment_id, action_type, driver_user.email, shipper_email, consignee_email))

        monkeypatch.setattr("app.services.shipment_workflow.send_shipment_alert", _fake_send)

        apply_pod_transition(shipment=shipment, action_type="SHIPPER_PICKUP", actor_user_id=driver.id)

        assert calls == [
            (shipment.id, "SHIPPER_PICKUP", "workflow-driver@example.com", "shipper@example.com", "consignee@example.com")
        ]
