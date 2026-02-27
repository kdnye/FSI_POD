import uuid
from app import create_app, db
from models import ExpectedDelivery

def seed_expected_deliveries():
    app = create_app()
    
    with app.app_context():
        # Generate a mock batch ID to group this specific route/manifest
        current_batch_id = f"BATCH-{uuid.uuid4().hex[:6].upper()}"
        
        deliveries = [
            ExpectedDelivery(
                batch_id=current_batch_id,
                reference_id="BOL-847291A",
                consignee_name="Desert Tech Manufacturing",
                destination_address="1400 E Innovation Park Dr, Tucson, AZ 85719",
                status="PENDING"
            ),
            ExpectedDelivery(
                batch_id=current_batch_id,
                reference_id="BOL-847291B",
                consignee_name="Sonoran BioLabs",
                destination_address="Oro Valley Hospital Campus, Oro Valley, AZ 85755",
                status="PENDING"
            ),
            ExpectedDelivery(
                batch_id=current_batch_id,
                reference_id="BOL-847291C",
                consignee_name="Catalina Distribution Center",
                destination_address="Retail Hub Blvd, Marana, AZ 85658",
                status="PENDING"
            )
        ]
        
        try:
            db.session.bulk_save_objects(deliveries)
            db.session.commit()
            print(f"Successfully seeded {len(deliveries)} deliveries for batch {current_batch_id}.")
        except Exception as e:
