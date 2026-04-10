#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""FastAPI application entry point for apipool_server."""

import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Startup
    init_db()
    _bootstrap_admin()
    yield
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
            print(f"[apipool] Admin user '{settings.APIPOOL_ADMIN_USERNAME}' created.")
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
