import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    Admin,
    AuditLog,
    Card,
    CardStatus,
    Device,
    DeviceStatus,
    License,
    LicenseStatus,
    RebindToken,
    RefreshToken,
)
from .schemas import ActivationRequest, CardGenerateRequest, LicenseCheckRequest, RenewalRequest
from .security import (
    ReceiptSigner,
    code_hint,
    create_refresh_token,
    generate_card_code,
    hash_card_code,
    hash_refresh_token,
    utcnow,
)


PLAN_DAYS = {"monthly": 30, "quarterly": 90, "yearly": 365, "permanent": None}


class ServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class LicenseService:
    def __init__(self, settings: Settings, signer: ReceiptSigner):
        self.settings = settings
        self.signer = signer

    def audit(self, db: Session, action: str, actor_type: str, actor_id: str | None = None,
              target_type: str | None = None, target_id: str | None = None,
              detail: dict | None = None, ip_address: str | None = None):
        db.add(AuditLog(
            actor_type=actor_type, actor_id=actor_id, action=action,
            target_type=target_type, target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address=ip_address,
        ))

    def generate_cards(self, db: Session, admin: Admin, request: CardGenerateRequest,
                       ip_address: str | None) -> tuple[str, list[str], int | None]:
        duration = request.duration_days if request.plan_type == "custom" else PLAN_DAYS[request.plan_type]
        batch_id = str(uuid.uuid4())
        codes: list[str] = []
        for _ in range(request.count):
            while True:
                code = generate_card_code(request.plan_type)
                digest = hash_card_code(code, self.settings.card_hash_pepper)
                if not db.scalar(select(Card.id).where(Card.code_hash == digest)):
                    break
            db.add(Card(
                code_hash=digest, code_hint=code_hint(code), plan_type=request.plan_type,
                duration_days=duration, device_limit=request.device_limit,
                offline_grace_hours=request.offline_grace_hours, batch_id=batch_id,
                channel=request.channel, notes=request.notes, created_by=admin.id,
            ))
            codes.append(code)
        self.audit(db, "cards.generate", "admin", admin.id, "card_batch", batch_id,
                   {"count": request.count, "plan_type": request.plan_type}, ip_address)
        db.commit()
        return batch_id, codes, duration

    def _new_refresh_token(self, db: Session, license_record: License, device: Device) -> str:
        raw = create_refresh_token()
        db.add(RefreshToken(
            license_id=license_record.id, device_id=device.id,
            token_hash=hash_refresh_token(raw),
            expires_at=utcnow() + timedelta(days=self.settings.refresh_token_days),
        ))
        return raw

    def _bind_device(self, db: Session, license_record: License, request: ActivationRequest) -> Device:
        active_count = db.scalar(select(func.count(Device.id)).where(
            Device.license_id == license_record.id, Device.status == DeviceStatus.ACTIVE.value
        )) or 0
        if active_count >= license_record.device_limit:
            raise ServiceError(409, "授权已达到设备数量上限")
        device = Device(
            license_id=license_record.id, machine_hash=request.machine_hash,
            install_id=request.install_id, label=request.device_label,
            last_app_version=request.app_version,
        )
        db.add(device)
        db.flush()
        return device

    def activate(self, db: Session, request: ActivationRequest, ip_address: str | None) -> dict:
        digest = hash_card_code(request.code, self.settings.card_hash_pepper)
        card = db.scalar(select(Card).where(Card.code_hash == digest).with_for_update())
        if card:
            if card.status != CardStatus.UNUSED.value:
                raise ServiceError(409, "卡密已使用、禁用或作废")
            now = utcnow()
            expires_at = None if card.duration_days is None else now + timedelta(days=card.duration_days)
            license_record = License(
                plan_type=card.plan_type, expires_at=expires_at, device_limit=card.device_limit,
                offline_grace_hours=card.offline_grace_hours,
            )
            db.add(license_record)
            db.flush()
            device = self._bind_device(db, license_record, request)
            card.status = CardStatus.USED.value
            card.used_at = now
            card.license_id = license_record.id
            action = "license.activate"
        else:
            rebind = db.scalar(select(RebindToken).where(RebindToken.code_hash == digest).with_for_update())
            if not rebind or rebind.used_at is not None or aware(rebind.expires_at) <= utcnow():
                raise ServiceError(404, "卡密或换机码无效")
            license_record = db.get(License, rebind.license_id)
            self._ensure_usable_license(license_record)
            for old_device in license_record.devices:
                old_device.status = DeviceStatus.REVOKED.value
            for token in license_record.refresh_tokens:
                token.revoked_at = utcnow()
            db.flush()
            device = self._bind_device(db, license_record, request)
            rebind.used_at = utcnow()
            action = "license.rebind"

        raw_token = self._new_refresh_token(db, license_record, device)
        license_record.last_check_at = utcnow()
        license_record.updated_at = utcnow()
        self.audit(db, action, "client", request.machine_hash, "license", license_record.id,
                   {"device_id": device.id}, ip_address)
        db.commit()
        return self.response(license_record, request.machine_hash, raw_token)

    def _ensure_usable_license(self, license_record: License | None):
        if not license_record:
            raise ServiceError(404, "授权不存在")
        if license_record.status == LicenseStatus.DISABLED.value:
            raise ServiceError(403, "授权已被禁用")
        expires_at = aware(license_record.expires_at)
        if expires_at and expires_at <= utcnow():
            license_record.status = LicenseStatus.EXPIRED.value
            raise ServiceError(403, "授权已到期")

    def authenticate_device(self, db: Session, request: LicenseCheckRequest) -> tuple[License, Device, RefreshToken]:
        token = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(request.refresh_token)
        ).with_for_update())
        if not token or token.revoked_at is not None or aware(token.expires_at) <= utcnow():
            raise ServiceError(401, "刷新令牌无效或已过期")
        if token.license_id != request.license_id:
            raise ServiceError(401, "刷新令牌与授权不匹配")
        device = db.get(Device, token.device_id)
        if not device or device.status != DeviceStatus.ACTIVE.value:
            raise ServiceError(403, "设备已解绑")
        if device.machine_hash != request.machine_hash or device.install_id != request.install_id:
            raise ServiceError(403, "机器码或安装标识不匹配")
        license_record = db.get(License, token.license_id)
        self._ensure_usable_license(license_record)
        device.last_seen_at = utcnow()
        device.last_app_version = request.app_version
        license_record.last_check_at = utcnow()
        license_record.updated_at = utcnow()
        return license_record, device, token

    def check(self, db: Session, request: LicenseCheckRequest, ip_address: str | None) -> dict:
        license_record, _, _ = self.authenticate_device(db, request)
        self.audit(db, "license.check", "client", request.machine_hash, "license",
                   license_record.id, ip_address=ip_address)
        db.commit()
        return self.response(license_record, request.machine_hash)

    def renew(self, db: Session, request: RenewalRequest, ip_address: str | None) -> dict:
        license_record, _, _ = self.authenticate_device(db, request)
        digest = hash_card_code(request.code, self.settings.card_hash_pepper)
        card = db.scalar(select(Card).where(Card.code_hash == digest).with_for_update())
        if not card or card.status != CardStatus.UNUSED.value:
            raise ServiceError(409, "续费卡密无效或已使用")
        now = utcnow()
        if card.duration_days is None:
            license_record.expires_at = None
            license_record.plan_type = "permanent"
        else:
            current_expiry = aware(license_record.expires_at)
            base = current_expiry if current_expiry and current_expiry > now else now
            license_record.expires_at = base + timedelta(days=card.duration_days)
            if license_record.plan_type != "permanent":
                license_record.plan_type = card.plan_type
        license_record.status = LicenseStatus.ACTIVE.value
        license_record.updated_at = now
        card.status = CardStatus.USED.value
        card.used_at = now
        card.license_id = license_record.id
        self.audit(db, "license.renew", "client", request.machine_hash, "license",
                   license_record.id, {"card_id": card.id, "days": card.duration_days}, ip_address)
        db.commit()
        return self.response(license_record, request.machine_hash)

    def response(self, license_record: License, machine_hash: str, refresh_token: str | None = None) -> dict:
        now = utcnow()
        expires_at = aware(license_record.expires_at)
        grace_end = now + timedelta(hours=license_record.offline_grace_hours)
        offline_until = min(expires_at, grace_end) if expires_at else grace_end
        payload = {
            "license_id": license_record.id,
            "machine_hash": machine_hash,
            "plan_type": license_record.plan_type,
            "status": license_record.status,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "offline_until": offline_until.isoformat(),
            "server_time": now.isoformat(),
            "key_id": self.signer.key_id,
            "device_limit": license_record.device_limit,
        }
        return {
            "license_id": license_record.id, "status": license_record.status,
            "plan_type": license_record.plan_type, "expires_at": expires_at,
            "offline_until": offline_until, "server_time": now,
            "device_limit": license_record.device_limit, "refresh_token": refresh_token,
            "signed_receipt": self.signer.sign(payload),
        }
