from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.auth import get_current_user, hash_password
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, configure_engine, init_db
from app.core.setup_state import (
    apply_bootstrap,
    generate_jwt_secret,
    is_setup_complete,
    mark_setup_complete,
    public_connection_view,
)
from app.models import User
from app.services.worker import worker

logger = logging.getLogger("lnxadmin.setup")
router = APIRouter(prefix="/api/setup", tags=["setup"])

PASSWORD_MASK = "********"


class DbParams(BaseModel):
    host: str = Field(default="localhost", min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    username: str = Field(default="lnxadmin", min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)
    database: str = Field(default="lnxadmin", min_length=1, max_length=128)


class SetupCompleteBody(BaseModel):
    database: DbParams
    admin_user: str = Field(default="admin", min_length=1, max_length=64)
    admin_password: str = Field(min_length=8, max_length=128)
    app_name: Optional[str] = Field(default="Linux Admin", max_length=128)
    app_env: str = Field(default="production")


class ConnectionUpdate(BaseModel):
    db_host: Optional[str] = Field(default=None, max_length=253)
    db_port: Optional[int] = Field(default=None, ge=1, le=65535)
    db_user: Optional[str] = Field(default=None, max_length=128)
    db_password: Optional[str] = Field(default=None, max_length=256)
    db_name: Optional[str] = Field(default=None, max_length=128)
    admin_user: Optional[str] = Field(default=None, max_length=64)
    admin_password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    cors_origins: Optional[str] = Field(default=None, max_length=1024)
    bind_host: Optional[str] = Field(default=None, max_length=64)
    bind_port: Optional[int] = Field(default=None, ge=1, le=65535)
    rotate_jwt: bool = False


async def _test_asyncpg(params: DbParams) -> dict[str, Any]:
    try:
        conn = await asyncpg.connect(
            host=params.host,
            port=params.port,
            user=params.username,
            password=params.password,
            database=params.database,
            timeout=8,
        )
        try:
            version = await conn.fetchval("select version()")
            return {"ok": True, "version": version}
        finally:
            await conn.close()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _upsert_admin(username: str, password: str) -> None:
    from app.core.db import AsyncSessionLocal as SessionLocal

    assert SessionLocal is not None
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            session.add(User(username=username, password_hash=hash_password(password), is_active=True))
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
        await session.commit()


@router.get("/status")
async def setup_status():
    cfg = get_settings()
    return {
        "configured": is_setup_complete(),
        "env": cfg.app_env,
        "bind_host": cfg.bind_host,
        "bind_port": cfg.bind_port,
        "suggested": {
            "db_host": cfg.db_host or "localhost",
            "db_port": cfg.db_port or 5432,
            "db_user": cfg.db_user or "lnxadmin",
            "db_name": cfg.db_name or "lnxadmin",
            "admin_user": cfg.admin_user or "admin",
        },
    }


@router.post("/test-db")
async def setup_test_db(body: DbParams):
    if is_setup_complete():
        # Still allow authenticated testing via settings; here only for wizard
        raise HTTPException(status_code=400, detail="Setup already completed — use Settings to test DB")
    return await _test_asyncpg(body)


@router.post("/complete")
async def setup_complete(body: SetupCompleteBody, request: Request):
    if is_setup_complete():
        raise HTTPException(status_code=400, detail="Setup already completed")

    if body.admin_password in {"admin", "password", "changeme", "change-me"}:
        raise HTTPException(status_code=400, detail="Choose a stronger admin password")

    test = await _test_asyncpg(body.database)
    if not test.get("ok"):
        raise HTTPException(status_code=400, detail=f"Database connection failed: {test.get('error')}")

    jwt_secret = generate_jwt_secret()
    app_env = "production" if body.app_env.lower() in {"prod", "production"} else "development"

    apply_bootstrap(
        {
            "app_env": app_env,
            "db_host": body.database.host,
            "db_port": body.database.port,
            "db_user": body.database.username,
            "db_password": body.database.password,
            "db_name": body.database.database,
            "jwt_secret": jwt_secret,
            "admin_user": body.admin_user,
            "admin_password": body.admin_password,
            "cors_origins": "http://127.0.0.1:8000,http://localhost:8000,http://localhost:5173,http://127.0.0.1:5173",
            "setup_complete": True,
        }
    )

    try:
        configure_engine()
        await init_db()
        await _upsert_admin(body.admin_user, body.admin_password)

        # Seed app display name
        from app.services.persistence import set_setting

        assert AsyncSessionLocal is not None
        async with AsyncSessionLocal() as session:
            await set_setting(session, "app_config", {"name": body.app_name or "Linux Admin"})

        mark_setup_complete()

        if not worker._task or worker._task.done():
            await worker.start()
        request.app.state.setup_complete = True
        request.app.state.worker_started = True
    except Exception as exc:
        logger.exception("setup complete failed")
        raise HTTPException(status_code=500, detail=f"Setup failed: {exc}") from exc

    return {
        "ok": True,
        "configured": True,
        "admin_user": body.admin_user,
        "message": "Setup complete. You can sign in now.",
        "db_version": test.get("version"),
    }


@router.get("/connection")
async def get_connection(_: str = Depends(get_current_user)):
    return public_connection_view()


@router.post("/test-connection")
async def test_connection(body: DbParams, _: str = Depends(get_current_user)):
    cfg = get_settings()
    password = body.password
    if not password or password == PASSWORD_MASK:
        password = cfg.db_password
    return await _test_asyncpg(
        DbParams(
            host=body.host,
            port=body.port,
            username=body.username,
            password=password,
            database=body.database,
        )
    )


@router.put("/connection")
async def update_connection(body: ConnectionUpdate, request: Request, _: str = Depends(get_current_user)):
    """Update bootstrap DB / admin settings (persisted to .env). May reconnect live."""
    if not is_setup_complete():
        raise HTTPException(status_code=503, detail="Initial setup required")

    cfg = get_settings()
    updates: dict[str, Any] = {}
    if body.db_host is not None:
        updates["db_host"] = body.db_host
    if body.db_port is not None:
        updates["db_port"] = body.db_port
    if body.db_user is not None:
        updates["db_user"] = body.db_user
    if body.db_name is not None:
        updates["db_name"] = body.db_name
    if body.db_password is not None and body.db_password not in {"", PASSWORD_MASK}:
        updates["db_password"] = body.db_password
    if body.admin_user is not None:
        updates["admin_user"] = body.admin_user
    if body.admin_password is not None and body.admin_password not in {"", PASSWORD_MASK}:
        if body.admin_password in {"admin", "password", "changeme", "change-me"}:
            raise HTTPException(status_code=400, detail="Choose a stronger admin password")
        updates["admin_password"] = body.admin_password
    if body.cors_origins is not None:
        updates["cors_origins"] = body.cors_origins
    if body.bind_host is not None:
        updates["bind_host"] = body.bind_host
    if body.bind_port is not None:
        updates["bind_port"] = body.bind_port
    if body.rotate_jwt:
        updates["jwt_secret"] = generate_jwt_secret()

    if not updates:
        return {"ok": True, "connection": public_connection_view(), "reconnected": False}

    # Test DB before saving if DB fields changed
    db_fields = {"db_host", "db_port", "db_user", "db_password", "db_name"}
    if db_fields & set(updates):
        test = await _test_asyncpg(
            DbParams(
                host=updates.get("db_host", cfg.db_host),
                port=int(updates.get("db_port", cfg.db_port)),
                username=updates.get("db_user", cfg.db_user),
                password=updates.get("db_password", cfg.db_password),
                database=updates.get("db_name", cfg.db_name),
            )
        )
        if not test.get("ok"):
            raise HTTPException(status_code=400, detail=f"Database connection failed: {test.get('error')}")

    apply_bootstrap(updates)
    configure_engine()
    await init_db()

    admin_user = updates.get("admin_user", cfg.admin_user)
    if "admin_password" in updates:
        await _upsert_admin(admin_user, updates["admin_password"])
    elif "admin_user" in updates:
        # rename not supported — just ensure user exists with current password from env
        pass

    restart_hint = bool({"bind_host", "bind_port", "jwt_secret"} & set(updates))
    return {
        "ok": True,
        "reconnected": True,
        "restart_required": restart_hint,
        "connection": public_connection_view(),
        "message": (
            "Saved. Restart the process if bind address or JWT was changed."
            if restart_hint
            else "Connection settings saved and applied."
        ),
    }
