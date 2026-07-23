from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import auth, disks, docker, history, network, openvpn, postgres, security, services, setup, ssh_tunnel, system, users, wireguard
from app.api import settings as settings_api
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, configure_engine, init_db
from app.core.setup_state import is_setup_complete
from app.services.persistence import ensure_admin_user
from app.services.worker import worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lnxadmin")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if get_settings().is_production:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto == "https":
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configured = is_setup_complete()
    app.state.setup_complete = configured
    app.state.worker_started = False

    for msg in cfg.security_warnings():
        logger.warning("security: %s", msg)
    errors = cfg.security_errors()
    if errors:
        for msg in errors:
            logger.error("security: %s", msg)
        raise RuntimeError("; ".join(errors))

    if not configured:
        logger.warning("Setup mode: open the UI wizard to configure the database and admin account")
        yield
        return

    if AsyncSessionLocal is None:
        configure_engine()
    await init_db()
    assert AsyncSessionLocal is not None
    async with AsyncSessionLocal() as session:
        await ensure_admin_user(session)
    await worker.start()
    app.state.worker_started = True
    logger.info("Linux Admin backend started (env=%s bind=%s:%s)", cfg.app_env, cfg.bind_host, cfg.bind_port)
    yield
    await worker.stop()
    logger.info("Linux Admin backend stopped")


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    index = dist / "index.html"

    @app.get("/")
    async def spa_index():
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built (run: make build)")
        return FileResponse(index)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = dist / full_path
        if candidate.is_file() and dist in candidate.resolve().parents:
            return FileResponse(candidate)
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built (run: make build)")
        return FileResponse(index)


def create_app() -> FastAPI:
    cfg = get_settings()
    # In setup mode keep docs available for operators unless explicitly disabled
    docs_off = cfg.docs_disabled and is_setup_complete()
    docs_url = None if docs_off else "/docs"
    redoc_url = None if docs_off else "/redoc"
    openapi_url = None if docs_off else "/openapi.json"

    app = FastAPI(
        title="Linux Admin",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    origins = cfg.cors_origin_list or ["http://127.0.0.1:8000", "http://localhost:8000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )
    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(history.router)
    app.include_router(security.router)
    app.include_router(docker.router)
    app.include_router(network.router)
    app.include_router(disks.router)
    app.include_router(ssh_tunnel.router)
    app.include_router(wireguard.router)
    app.include_router(openvpn.router)
    app.include_router(users.router)
    app.include_router(services.router)
    app.include_router(postgres.router)
    app.include_router(settings_api.router)

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "app": "Linux Admin",
            "env": get_settings().app_env,
            "configured": is_setup_complete(),
        }

    dist = cfg.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        _mount_frontend(app, dist)
        logger.info("Serving frontend from %s", dist)
    else:

        @app.get("/")
        async def root_hint():
            return JSONResponse(
                {
                    "app": "Linux Admin",
                    "configured": is_setup_complete(),
                    "message": "API is running. Build the UI with `make build` or use Vite in development.",
                    "health": "/api/health",
                    "setup": "/api/setup/status",
                }
            )

    return app


app = create_app()
