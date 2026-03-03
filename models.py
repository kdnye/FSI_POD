from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import Boolean, Enum as SQLALchemyEnum
from sqlalchemy.orm import Mapped
from datetime import datetime
from zoneinfo import ZoneInfo

# Import the initialized db from your main app
from app import db

# Table name constants
# This MUST match the Expenses app to share the same user pool
USERS_TABLE = "users"
WORKFLOWS_TABLE = "workflows"
QUOTES_TABLE = "quotes"
AUDIT_LOGS_TABLE = "audit_logs"

class Role(str, Enum):
    """Matches the enum values in the Expenses app user_role type."""
    EMPLOYEE = "EMPLOYEE"
    SUPERVISOR = "SUPERVISOR"
    FINANCE = "FINANCE"
    ADMIN = "ADMIN"
    ADMINISTRATOR = "ADMINISTRATOR"

    @classmethod
    def from_value(cls, value: "Role | str") -> "Role":
        if isinstance(value, cls):
            return value

        normalized = str(value or "").strip().upper()
        aliases = {
            "ADMINISTRATOR": cls.ADMINISTRATOR.value,
        }

        return cls(aliases.get(normalized, normalized))

    @property
    def is_admin(self) -> bool:
        return self in {Role.ADMIN, Role.ADMINISTRATOR}

class User(db.Model):
    """
    Paperwork Portal User model.
    Inherits the schema from the Expenses App to allow shared authentication.
    """
    __tablename__ = USERS_TABLE

    # Core identification (Shared with Expenses App)
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    
    # Name fields (Shared with Expenses App)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    name = db.Column(db.String(120))  # Full name field used in some Expenses views
    
    # Authentication & Access (Shared with Expenses App)
    password_hash = db.Column(db.String(255), nullable=False)
    role: Mapped[str] = db.Column(
        SQLALchemyEnum(
            "EMPLOYEE",
            "SUPERVISOR",
            "FINANCE",
            "ADMIN",
            "ADMINISTRATOR",
            name="user_role", # Must match the existing Postgres enum type name
        ),
        nullable=False,
        default="EMPLOYEE",
    )
    employee_approved: Mapped[bool] = db.Column(Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def can_access_portal(self) -> bool:
        """Standard FSI guard check."""
        return self.employee_approved and self.is_active

class PODEvent(db.Model):
    __tablename__ = "pod_events"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reference_id = db.Column(db.String(100), index=True) # E.g., Order or BOL number from QR
    event_type = db.Column(db.String(20)) # 'PICKUP' or 'DELIVERY'
    
    # Geolocation
    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))
    
    # Timestamps
    utc_timestamp = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    az_timestamp = db.Column(db.DateTime(timezone=True))
    
    # Media Links
    signature_url = db.Column(db.String(512))
    photo_url = db.Column(db.String(512))

    def set_az_timestamp(self):
        """Translates current UTC time to Arizona time (MST, no DST)."""
        utc_now = datetime.now(ZoneInfo("UTC"))
        self.az_timestamp = utc_now.astimezone(ZoneInfo("America/Phoenix"))

class ExpectedDelivery(db.Model):
    __tablename__ = "expected_deliveries"
    
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(50), index=True) # Grouping ID for a truck/route
    reference_id = db.Column(db.String(100), unique=True, index=True) # Matches QR code
    consignee_name = db.Column(db.String(150))
    destination_address = db.Column(db.String(255))
    
    # Dynamic status evaluated on the fly or updated via triggers
    status = db.Column(db.String(20), default="PENDING") # PENDING, PICKED_UP, DELIVERED
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LoadBoard(db.Model):
    __tablename__ = "load_board"

    hwb_number = db.Column(db.String(100), primary_key=True)
    shipper = db.Column(db.String(150), nullable=False)
    consignee = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    assigned_driver = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    status = db.Column(db.String(20), nullable=False, default="Pending")


class PODRecord(db.Model):
    __tablename__ = "pod_records"

    id = db.Column(db.Integer, primary_key=True)
    hwb_number = db.Column(db.String(100), db.ForeignKey("load_board.hwb_number"), index=True, nullable=True)
    delivery_photo = db.Column(db.String(512), nullable=False)
    signature_image = db.Column(db.String(512), nullable=False)
    recipient_name = db.Column(db.String(120), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action_type = db.Column(db.String(20), nullable=False)

    # Nullable on purpose to support standalone/manual POD entries.
    shipper = db.Column(db.String(150), nullable=True)
    consignee = db.Column(db.String(150), nullable=True)
    contact_name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
