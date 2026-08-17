import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class CardStatus(str, enum.Enum):
    UNUSED = "unused"
    USED = "used"
    DISABLED = "disabled"
    VOID = "void"


class LicenseStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"


class DeviceStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hint: Mapped[str] = mapped_column(String(32), index=True)
    plan_type: Mapped[str] = mapped_column(String(24), index=True)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    device_limit: Mapped[int] = mapped_column(Integer, default=1)
    offline_grace_hours: Mapped[int] = mapped_column(Integer, default=72)
    status: Mapped[str] = mapped_column(String(24), default=CardStatus.UNUSED.value, index=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("admins.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_id: Mapped[str | None] = mapped_column(ForeignKey("licenses.id"))

    license: Mapped["License | None"] = relationship(back_populates="cards")


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(24), default=LicenseStatus.ACTIVE.value, index=True)
    plan_type: Mapped[str] = mapped_column(String(24))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    device_limit: Mapped[int] = mapped_column(Integer, default=1)
    offline_grace_hours: Mapped[int] = mapped_column(Integer, default=72)
    customer_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cards: Mapped[list[Card]] = relationship(back_populates="license")
    devices: Mapped[list["Device"]] = relationship(back_populates="license")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="license")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_license_machine", "license_id", "machine_hash", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    machine_hash: Mapped[str] = mapped_column(String(128), index=True)
    install_id: Mapped[str] = mapped_column(String(128))
    label: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default=DeviceStatus.ACTIVE.value)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_app_version: Mapped[str | None] = mapped_column(String(40))

    license: Mapped[License] = relationship(back_populates="devices")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="device")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    license: Mapped[License] = relationship(back_populates="refresh_tokens")
    device: Mapped[Device] = relationship(back_populates="refresh_tokens")


class RebindToken(Base):
    __tablename__ = "rebind_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hint: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("admins.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str | None] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
