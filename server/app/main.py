from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import Settings, get_settings
from .db import Base, build_engine, build_session_factory
from .models import Admin
from .routers import admin, public
from .security import ReceiptSigner, hash_password
from .services import LicenseService, ServiceError


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    engine = build_engine(app_settings.database_url)
    session_factory = build_session_factory(engine)
    signer = ReceiptSigner(app_settings.signing_key_path, app_settings.signing_key_id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        with session_factory() as db:
            admin_record = db.scalar(select(Admin).where(
                Admin.username == app_settings.bootstrap_admin_username
            ))
            if not admin_record:
                db.add(Admin(
                    username=app_settings.bootstrap_admin_username,
                    password_hash=hash_password(app_settings.bootstrap_admin_password),
                ))
                db.commit()
        yield
        engine.dispose()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        docs_url="/api/docs" if app_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.session_factory = session_factory
    app.state.signer = signer
    app.state.license_service = LicenseService(app_settings, signer)

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    app.include_router(public.router)
    app.include_router(admin.router)
    return app
