from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .models import Admin
from .security import decode_admin_token


bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="需要管理员登录")
    try:
        admin_id = decode_admin_token(credentials.credentials, request.app.state.settings.jwt_secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="管理员登录已失效") from exc
    admin = db.get(Admin, admin_id)
    if not admin or not admin.active:
        raise HTTPException(status_code=401, detail="管理员账号不可用")
    return admin
