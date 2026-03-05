from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, relationship

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


class ShipmentLegType(str, Enum):
    PICKUP_TO_ORIGIN_AIRPORT = "PICKUP_TO_ORIGIN_AIRPORT"
    AIRPORT_TO_AIRPORT = "AIRPORT_TO_AIRPORT"
    DEST_AIRPORT_TO_CONSIGNEE = "DEST_AIRPORT_TO_CONSIGNEE"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ShipmentLegStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class User(db.Model):
    """Paperwork Portal User model."""

    __tablename__ = USERS_TABLE

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    name = db.Column(db.String(120))

    password_hash = db.Column(db.String(255), nullable=False)
    role: Mapped[str] = db.Column(
        SQLAlchemyEnum(
            "EMPLOYEE",
            "SUPERVISOR",
            "FINANCE",
            "ADMIN",
            "ADMINISTRATOR",
            name="user_role",
        ),
        nullable=False,
        default="EMPLOYEE",
    )
    employee_approved: Mapped[bool] = db.Column(Boolean, nullable=False, default=False)
    is_ops: Mapped[bool] = db.Column(Boolean, nullable=False, default=False)
    is_driver: Mapped[bool] = db.Column(Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def can_access_portal(self) -> bool:
        return self.employee_approved and self.is_active


class PODEvent(db.Model):
    __tablename__ = "pod_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reference_id = db.Column(db.String(100), index=True)
    event_type = db.Column(db.String(20))

    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))

    utc_timestamp = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    az_timestamp = db.Column(db.DateTime(timezone=True))

    signature_url = db.Column(db.String(512))
    photo_url = db.Column(db.String(512))

    def set_az_timestamp(self):
        utc_now = datetime.now(ZoneInfo("UTC"))
        self.az_timestamp = utc_now.astimezone(ZoneInfo("America/Phoenix"))


class ExpectedDelivery(db.Model):
    __tablename__ = "expected_deliveries"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(50), index=True)
    reference_id = db.Column(db.String(100), unique=True, index=True)
    consignee_name = db.Column(db.String(150))
    destination_address = db.Column(db.String(255))
    status = db.Column(db.String(20), default="PENDING")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LoadBoard(db.Model):
    __tablename__ = "load_board"

    hwb_number = db.Column(db.String(100), primary_key=True)
    mawb_number = db.Column(db.String(100), index=True, nullable=True)
    shipper = db.Column(db.String(150), nullable=False)
    consignee = db.Column(db.String(150), nullable=False)
    shipper_email = db.Column(db.String(255), nullable=True)
    consignee_email = db.Column(db.String(255), nullable=True)
    contact_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    assigned_driver = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    status = db.Column(db.String(20), nullable=False, default="Pending")


class ShipmentGroup(db.Model):
    __tablename__ = "shipment_groups"

    id = db.Column(Integer, primary_key=True)
    mawb_number = db.Column(String(100), nullable=False, unique=True, index=True)
    carrier = db.Column(String(120), nullable=True)
    origin_airport = db.Column(String(10), nullable=True)
    destination_airport = db.Column(String(10), nullable=True)
    booked_at_utc = db.Column(DateTime(timezone=True), nullable=True)
    created_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipments = relationship("Shipment", back_populates="shipment_group", cascade="all, delete-orphan")


class Shipment(db.Model):
    __tablename__ = "shipments"

    id = db.Column(Integer, primary_key=True)
    hwb_number = db.Column(String(100), nullable=False, unique=True, index=True)
    shipment_group_id = db.Column(Integer, ForeignKey("shipment_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    shipper_address = db.Column(String(255), nullable=True)
    consignee_address = db.Column(String(255), nullable=True)
    shipper_email = db.Column(String(255), nullable=True)
    consignee_email = db.Column(String(255), nullable=True)
    current_leg_index = db.Column(Integer, nullable=False, default=1)
    overall_status = db.Column(
        SQLAlchemyEnum(
            ShipmentStatus,
            name="shipment_status_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ShipmentStatus.PENDING,
    )
    created_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipment_group = relationship("ShipmentGroup", back_populates="shipments")
    legs = relationship("ShipmentLeg", back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentLeg.leg_sequence")


class ShipmentLeg(db.Model):
    __tablename__ = "shipment_legs"

    id = db.Column(Integer, primary_key=True)
    shipment_id = db.Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    leg_sequence = db.Column(Integer, nullable=False)
    leg_type = db.Column(
        SQLAlchemyEnum(
            ShipmentLegType,
            name="shipment_leg_type_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    from_location_type = db.Column(String(30), nullable=True)
    to_location_type = db.Column(String(30), nullable=True)
    from_address = db.Column(String(255), nullable=True)
    to_address = db.Column(String(255), nullable=True)
    from_airport = db.Column(String(10), nullable=True)
    to_airport = db.Column(String(10), nullable=True)
    assigned_driver_id = db.Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = db.Column(
        SQLAlchemyEnum(
            ShipmentLegStatus,
            name="shipment_leg_status_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ShipmentLegStatus.PENDING,
    )
    started_at_utc = db.Column(DateTime(timezone=True), nullable=True)
    completed_at_utc = db.Column(DateTime(timezone=True), nullable=True)
    created_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    shipment = relationship("Shipment", back_populates="legs")

    __table_args__ = (
        UniqueConstraint("shipment_id", "leg_sequence", name="uq_shipment_legs_shipment_id_leg_sequence"),
        CheckConstraint("leg_sequence > 0", name="ck_shipment_legs_leg_sequence_positive"),
        Index("ix_shipment_legs_shipment_id_leg_sequence", "shipment_id", "leg_sequence"),
    )


class ShipmentLegTransition(db.Model):
    __tablename__ = "shipment_leg_transitions"

    id = db.Column(Integer, primary_key=True)
    shipment_id = db.Column(Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_leg_id = db.Column(Integer, ForeignKey("shipment_legs.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = db.Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pod_action = db.Column(String(64), nullable=False)
    from_status = db.Column(
        SQLAlchemyEnum(
            ShipmentLegStatus,
            name="shipment_leg_transition_from_status_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    to_status = db.Column(
        SQLAlchemyEnum(
            ShipmentLegStatus,
            name="shipment_leg_transition_to_status_enum",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    latitude = db.Column(String(32), nullable=True)
    longitude = db.Column(String(32), nullable=True)
    event_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at_utc = db.Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PODRecord(db.Model):
    __tablename__ = "pod_records"

    id = db.Column(db.Integer, primary_key=True)
    hwb_number = db.Column(db.String(100), index=True, nullable=True)
    delivery_photo = db.Column(db.String(512), nullable=True)
    signature_image = db.Column(db.String(512), nullable=True)
    recipient_name = db.Column(db.String(120), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action_type = db.Column(db.String(64), nullable=False)

    shipper = db.Column(db.String(150), nullable=True)
    consignee = db.Column(db.String(150), nullable=True)
    contact_name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    off_sheet_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    reassignment_note = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.String(32), nullable=True)
    longitude = db.Column(db.String(32), nullable=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True)
    leg_id = db.Column(db.Integer, db.ForeignKey("shipment_legs.id", ondelete="SET NULL"), nullable=True, index=True)
    leg_sequence = db.Column(db.Integer, nullable=True)
    leg_type = db.Column(db.String(64), nullable=True)


class NotificationSettings(db.Model):
    __tablename__ = "notification_settings"

    id = db.Column(Integer, primary_key=True)
    notify_shipper_pickup = db.Column(Boolean, nullable=False, default=False)
    notify_origin_drop = db.Column(Boolean, nullable=False, default=False)
    notify_dest_pickup = db.Column(Boolean, nullable=False, default=False)
    notify_consignee_drop = db.Column(Boolean, nullable=False, default=False)
    custom_cc_emails = db.Column(Text, nullable=True)
