from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..dependencies import get_client_ip, get_current_admin, get_db
from ..models import (
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
from ..schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminPasswordChangeRequest,
    CardGenerateRequest,
    CardGenerateResponse,
    CardStatusRequest,
    LicenseActionRequest,
    RebindCodeRequest,
    RebindCodeResponse,
)
from ..security import (
    code_hint,
    create_admin_token,
    generate_card_code,
    hash_card_code,
    hash_password,
    utcnow,
    verify_password,
)
from ..services import aware


router = APIRouter(prefix="/api/admin", tags=["admin"])


def iso(value):
    return aware(value).isoformat() if value else None


@router.post("/login", response_model=AdminLoginResponse)
def login(payload: AdminLoginRequest, request: Request, db: Session = Depends(get_db),
          client_ip: str | None = Depends(get_client_ip)):
    admin = db.scalar(select(Admin).where(Admin.username == payload.username))
    if not admin or not admin.active or not verify_password(admin.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    admin.last_login_at = utcnow()
    request.app.state.license_service.audit(
        db, "admin.login", "admin", admin.id, ip_address=client_ip
    )
    db.commit()
    minutes = request.app.state.settings.admin_token_minutes
    return AdminLoginResponse(
        access_token=create_admin_token(admin.id, request.app.state.settings.jwt_secret, minutes),
        expires_in=minutes * 60,
    )


@router.post("/password")
def change_password(payload: AdminPasswordChangeRequest, request: Request,
                    admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                    client_ip: str | None = Depends(get_client_ip)):
    if not verify_password(admin.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    admin.password_hash = hash_password(payload.new_password)
    request.app.state.license_service.audit(
        db, "admin.password_change", "admin", admin.id, "admin", admin.id,
        ip_address=client_ip,
    )
    db.commit()
    return {"changed": True}


@router.get("/stats")
def stats(admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db)):
    now = utcnow()
    return {
        "unused_cards": db.scalar(select(func.count(Card.id)).where(Card.status == CardStatus.UNUSED.value)) or 0,
        "active_licenses": db.scalar(select(func.count(License.id)).where(
            License.status == LicenseStatus.ACTIVE.value,
            or_(License.expires_at.is_(None), License.expires_at > now),
        )) or 0,
        "expiring_licenses": db.scalar(select(func.count(License.id)).where(
            License.status == LicenseStatus.ACTIVE.value,
            License.expires_at > now,
            License.expires_at <= now + timedelta(days=7),
        )) or 0,
        "active_devices": db.scalar(select(func.count(Device.id)).where(
            Device.status == DeviceStatus.ACTIVE.value
        )) or 0,
    }


@router.post("/cards/generate", response_model=CardGenerateResponse)
def generate_cards(payload: CardGenerateRequest, request: Request,
                   admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                   client_ip: str | None = Depends(get_client_ip)):
    batch_id, codes, duration = request.app.state.license_service.generate_cards(
        db, admin, payload, client_ip
    )
    return CardGenerateResponse(
        batch_id=batch_id, codes=codes, plan_type=payload.plan_type, duration_days=duration
    )


@router.get("/cards")
def list_cards(
    status: str | None = None,
    search: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = select(Card)
    count_query = select(func.count(Card.id))
    if status:
        query = query.where(Card.status == status)
        count_query = count_query.where(Card.status == status)
    if search:
        term = f"%{search}%"
        condition = or_(Card.code_hint.ilike(term), Card.batch_id.ilike(term), Card.channel.ilike(term))
        query = query.where(condition)
        count_query = count_query.where(condition)
    cards = db.scalars(query.order_by(Card.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "total": db.scalar(count_query) or 0,
        "items": [{
            "id": card.id, "code_hint": card.code_hint, "plan_type": card.plan_type,
            "duration_days": card.duration_days, "status": card.status,
            "batch_id": card.batch_id, "channel": card.channel, "notes": card.notes,
            "license_id": card.license_id, "created_at": iso(card.created_at),
            "used_at": iso(card.used_at),
        } for card in cards],
    }


@router.patch("/cards/{card_id}")
def update_card(card_id: str, payload: CardStatusRequest, request: Request,
                admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                client_ip: str | None = Depends(get_client_ip)):
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")
    transitions = {
        "disable": CardStatus.DISABLED.value,
        "enable": CardStatus.UNUSED.value,
        "void": CardStatus.VOID.value,
    }
    if payload.action == "disable" and card.status != CardStatus.UNUSED.value:
        raise HTTPException(status_code=409, detail="只有未使用卡密可以禁用")
    if payload.action == "enable" and card.status != CardStatus.DISABLED.value:
        raise HTTPException(status_code=409, detail="只有已禁用且未使用的卡密可以恢复")
    if payload.action == "void" and card.status not in {
        CardStatus.UNUSED.value, CardStatus.DISABLED.value
    }:
        raise HTTPException(status_code=409, detail="已使用或已作废卡密不能再次作废")
    card.status = transitions[payload.action]
    request.app.state.license_service.audit(
        db, f"card.{payload.action}", "admin", admin.id, "card", card.id,
        ip_address=client_ip,
    )
    db.commit()
    return {"id": card.id, "status": card.status}


@router.get("/licenses")
def list_licenses(
    status: str | None = None,
    search: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = select(License).options(selectinload(License.devices))
    count_query = select(func.count(License.id))
    if status:
        query = query.where(License.status == status)
        count_query = count_query.where(License.status == status)
    if search:
        condition = License.id.ilike(f"%{search}%")
        query = query.where(condition)
        count_query = count_query.where(condition)
    licenses = db.scalars(query.order_by(License.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "total": db.scalar(count_query) or 0,
        "items": [{
            "id": item.id, "status": item.status, "plan_type": item.plan_type,
            "expires_at": iso(item.expires_at), "device_limit": item.device_limit,
            "offline_grace_hours": item.offline_grace_hours,
            "created_at": iso(item.created_at), "last_check_at": iso(item.last_check_at),
            "devices": [{
                "id": device.id, "machine_hash": device.machine_hash,
                "label": device.label, "status": device.status,
                "bound_at": iso(device.bound_at), "last_seen_at": iso(device.last_seen_at),
            } for device in item.devices],
        } for item in licenses],
    }


@router.post("/licenses/{license_id}/action")
def license_action(license_id: str, payload: LicenseActionRequest, request: Request,
                   admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                   client_ip: str | None = Depends(get_client_ip)):
    item = db.scalar(select(License).where(License.id == license_id).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="授权不存在")
    now = utcnow()
    if payload.action == "disable":
        item.status = LicenseStatus.DISABLED.value
    elif payload.action == "enable":
        item.status = LicenseStatus.ACTIVE.value if not item.expires_at or aware(item.expires_at) > now else LicenseStatus.EXPIRED.value
    elif payload.action == "set_permanent":
        item.status = LicenseStatus.ACTIVE.value
        item.plan_type = "permanent"
        item.expires_at = None
    elif payload.action == "extend":
        if not payload.days:
            raise HTTPException(status_code=422, detail="延长授权必须填写天数")
        base = aware(item.expires_at)
        item.expires_at = (base if base and base > now else now) + timedelta(days=payload.days)
        item.status = LicenseStatus.ACTIVE.value
    item.updated_at = now
    request.app.state.license_service.audit(
        db, f"license.{payload.action}", "admin", admin.id, "license", item.id,
        {"days": payload.days, "note": payload.note}, client_ip,
    )
    db.commit()
    return {"id": item.id, "status": item.status, "expires_at": iso(item.expires_at)}


@router.post("/licenses/{license_id}/rebind-code", response_model=RebindCodeResponse)
def create_rebind_code(license_id: str, payload: RebindCodeRequest, request: Request,
                       admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                       client_ip: str | None = Depends(get_client_ip)):
    license_record = db.get(License, license_id)
    if not license_record:
        raise HTTPException(status_code=404, detail="授权不存在")
    code = generate_card_code("rebind")
    expires_at = utcnow() + timedelta(hours=24)
    token = RebindToken(
        license_id=license_id,
        code_hash=hash_card_code(code, request.app.state.settings.card_hash_pepper),
        code_hint=code_hint(code), notes=payload.notes, created_by=admin.id,
        expires_at=expires_at,
    )
    db.add(token)
    request.app.state.license_service.audit(
        db, "license.rebind_code", "admin", admin.id, "license", license_id,
        {"rebind_token_id": token.id}, client_ip,
    )
    db.commit()
    return RebindCodeResponse(code=code, expires_at=expires_at)


@router.post("/devices/{device_id}/unbind")
def unbind_device(device_id: str, request: Request,
                  admin: Admin = Depends(get_current_admin), db: Session = Depends(get_db),
                  client_ip: str | None = Depends(get_client_ip)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    device.status = DeviceStatus.REVOKED.value
    tokens = db.scalars(select(RefreshToken).where(
        RefreshToken.device_id == device.id, RefreshToken.revoked_at.is_(None)
    )).all()
    for token in tokens:
        token.revoked_at = utcnow()
    request.app.state.license_service.audit(
        db, "device.unbind", "admin", admin.id, "device", device.id,
        {"license_id": device.license_id}, client_ip,
    )
    db.commit()
    return {"id": device.id, "status": device.status}


@router.get("/audit-logs")
def audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [{
        "id": log.id, "actor_type": log.actor_type, "actor_id": log.actor_id,
        "action": log.action, "target_type": log.target_type, "target_id": log.target_id,
        "detail": log.detail, "ip_address": log.ip_address,
        "created_at": iso(log.created_at),
    } for log in logs]}
