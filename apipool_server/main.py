#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""FastAPI application entry point for apipool_server."""

import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .database import init_db
from .api.router import api_router
from .services.client_registry import ClientRegistry
# Ensure all models are registered in Base.metadata before init_db()
from .models import refresh_token  # noqa: F401

# ── Structured logging setup ──────────────────────────────────────────────

logger = logging.getLogger("apipool")

_LOG_FORMAT = "[%(asctime)s] %(name)s %(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logging():
    """Configure root logger with structured output."""
    level = logging.DEBUG if get_settings().DEBUG else logging.INFO
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        stream=sys.stdout,
    )
    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ── Security checks ────────────────────────────────────────────────────────

_DEFAULT_JWT_SECRET = "change-me-in-production"
_WEAK_PASSWORDS = {"admin", "password", "123456", "admin123", "root", "test"}


def _security_checks(settings) -> None:
    """Run pre-startup security validations. Raises on critical issues."""
    # P0-1: Reject default JWT secret in production
    if settings.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET and not settings.DEBUG:
        raise SystemExit(
            "FATAL: JWT_SECRET_KEY is set to the default insecure value. "
            "Please set a strong random secret via the JWT_SECRET_KEY environment variable "
            "or .env file before running in production."
        )
    if settings.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET:
        warnings.warn(
            "[SECURITY] JWT_SECRET_KEY is using the default value. "
            "This is acceptable only in DEBUG mode. Change it before deploying to production.",
            stacklevel=2,
        )

    # P0-2: Warn on weak admin password
    pwd_lower = settings.APIPOOL_ADMIN_PASSWORD.lower()
    if pwd_lower in _WEAK_PASSWORDS or len(settings.APIPOOL_ADMIN_PASSWORD) < 8:
        warnings.warn(
            f"[SECURITY] Admin password for '{settings.APIPOOL_ADMIN_USERNAME}' is weak. "
            "Please set a strong APIPOOL_ADMIN_PASSWORD (>= 8 chars, not a common password).",
            stacklevel=2,
        )


# ── Application lifecycle ─────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    _setup_logging()

    # Security checks (before any DB operation)
    _security_checks(settings)

    logger.info("Starting apipool-server v%s", settings.APP_VERSION)
    init_db()
    _bootstrap_admin()
    logger.info("apipool-server ready — listening on %s:%s", settings.HOST, settings.PORT)
    yield
    logger.info("Shutting down apipool-server")
    # Shutdown


def _bootstrap_admin():
    """Create default admin user if not exists."""
    from .database import get_session_local
    from .models.user import User
    from .security import hash_password

    settings = get_settings()
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == settings.APIPOOL_ADMIN_USERNAME).first()
        if not admin:
            admin = User(
                username=settings.APIPOOL_ADMIN_USERNAME,
                email=settings.APIPOOL_ADMIN_EMAIL,
                hashed_password=hash_password(settings.APIPOOL_ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            db.commit()
            logger.info("Admin user '%s' created.", settings.APIPOOL_ADMIN_USERNAME)
    finally:
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="apipool-server",
        description="Web service for apipool-ng — API Key pool management with transparent proxy calls",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(api_router)

    # Health check
    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    # Info endpoint
    @app.get("/api/v1/info/client-types")
    def list_client_types():
        """List all registered client types."""
        return {"client_types": ClientRegistry.list_types()}

    # ── Serve frontend static files ──
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        # Serve root-level static files (favicon, vite.svg, etc.)
        for f in static_dir.iterdir():
            if f.is_file() and f.suffix in (".svg", ".png", ".ico", ".json", ".webmanifest"):
                path_name = f"/{f.name}"
                # Avoid re-registering existing routes
                existing_paths = [r.path for r in app.routes if hasattr(r, "path")]
                if path_name not in existing_paths:
                    @app.get(path_name, include_in_schema=False)
                    async def _serve_static(file_path: Path = f):
                        return FileResponse(str(file_path))

        # SPA fallback: serve index.html for all non-API routes
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            """Serve the SPA index.html for all frontend routes."""
            file_path = static_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(static_dir / "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "apipool_server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
