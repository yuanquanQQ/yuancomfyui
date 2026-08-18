from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..dependencies import get_client_ip, get_db
from ..schemas import ActivationRequest, LicenseCheckRequest, LicenseResponse, RenewalRequest
from ..workflow_catalog import workflow_catalog_response


router = APIRouter(prefix="/api/v1/license", tags=["license"])


@router.post("/activate", response_model=LicenseResponse)
def activate(
    payload: ActivationRequest,
    request: Request,
    db: Session = Depends(get_db),
    client_ip: str | None = Depends(get_client_ip),
):
    return request.app.state.license_service.activate(db, payload, client_ip)


@router.post("/check", response_model=LicenseResponse)
def check(
    payload: LicenseCheckRequest,
    request: Request,
    db: Session = Depends(get_db),
    client_ip: str | None = Depends(get_client_ip),
):
    return request.app.state.license_service.check(db, payload, client_ip)


@router.post("/renew", response_model=LicenseResponse)
def renew(
    payload: RenewalRequest,
    request: Request,
    db: Session = Depends(get_db),
    client_ip: str | None = Depends(get_client_ip),
):
    return request.app.state.license_service.renew(db, payload, client_ip)


@router.get("/public-key")
def public_key(request: Request):
    return {
        "key_id": request.app.state.signer.key_id,
        "algorithm": "Ed25519",
        "public_key_pem": request.app.state.signer.public_key_pem(),
    }


@router.post("/workflows")
def workflows(
    payload: LicenseCheckRequest,
    request: Request,
    db: Session = Depends(get_db),
    client_ip: str | None = Depends(get_client_ip),
):
    service = request.app.state.license_service
    license_record, _, _ = service.authenticate_device(db, payload)
    service.audit(
        db, "workflow.catalog", "client", payload.machine_hash,
        "license", license_record.id, ip_address=client_ip,
    )
    db.commit()
    return workflow_catalog_response()
