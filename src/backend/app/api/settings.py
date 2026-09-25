from __future__ import annotations

import socket
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.principal import Principal, get_principal, require_module
from app.services.fileman import FileManError, normalize_roots
from app.services.persistence import (
    DEFAULT_APP_CONFIG,
    DEFAULT_MODULES,
    DEFAULT_PG_SETTINGS,
    deep_merge,
    get_app_config,
    get_modules,
    get_setting,
    set_setting,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

PASSWORD_MASK = "********"


class AppConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    metrics_interval_seconds: Optional[float] = Field(default=None, ge=0.5, le=60)
    history_interval_seconds: Optional[float] = Field(default=None, ge=5, le=3600)
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)


class PostgresBlockUpdate(BaseModel):
    enabled: Optional[bool] = None
    record_history: Optional[bool] = None
    databases: Optional[List[str]] = None
    interval_seconds: Optional[int] = Field(default=None, ge=10, le=3600)
    collect_statements: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


class SettingsUpdate(BaseModel):
    app: Optional[AppConfigUpdate] = None
    modules: Optional[Dict[str, Any]] = None
    postgres: Optional[PostgresBlockUpdate] = None


def _public_postgres(raw: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULT_PG_SETTINGS, **raw}
    app = get_settings()
    if not out.get("host"):
        out["host"] = app.db_host
    if not out.get("port"):
        out["port"] = app.db_port
    if not out.get("username"):
        out["username"] = app.db_user
    if not out.get("database"):
        out["database"] = app.db_name
    has_password = bool(raw.get("password")) or bool(app.db_password)
    out["password"] = PASSWORD_MASK if has_password else ""
    out["password_set"] = has_password
    return out


def _merge_password(incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_PG_SETTINGS, **existing, **incoming}
    pwd = incoming.get("password")
    if pwd is None or pwd == "" or pwd == PASSWORD_MASK:
        if "password" in existing:
            merged["password"] = existing["password"]
        else:
            merged.pop("password", None)
    return merged


async def _bundle(db: AsyncSession) -> dict[str, Any]:
    app_cfg = await get_app_config(db)
    modules = await get_modules(db)
    pg_raw = await get_setting(db, "postgres_monitor", DEFAULT_PG_SETTINGS)
    # Keep module.postgres.enabled as source of UI visibility;
    # mirror into response postgres.enabled for the form.
    pg_public = _public_postgres(pg_raw)
    pg_public["enabled"] = bool(modules.get("postgres", {}).get("enabled", True)) and bool(
        pg_raw.get("enabled", True)
    )
    return {
        "app": app_cfg,
        "modules": modules,
        "postgres": pg_public,
        "defaults": {
            "app": DEFAULT_APP_CONFIG,
            "modules": DEFAULT_MODULES,
        },
    }


@router.get("")
async def get_all_settings(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("settings", "read")),
):
    return await _bundle(db)


@router.get("/modules")
async def get_modules_only(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(get_principal),
):
    """Lightweight payload for menu / feature gating (any authenticated user)."""
    modules = await get_modules(db)
    app_cfg = await get_app_config(db)
    return {
        "app": {"name": app_cfg.get("name")},
        "modules": modules,
        "hostname": socket.gethostname(),
    }


@router.put("")
async def put_all_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings", "read")),
):
    if body.app is not None:
        principal.require("settings", "full")
        current_app = await get_setting(db, "app_config", {})
        patch = body.app.model_dump(exclude_unset=True)
        await set_setting(db, "app_config", {**current_app, **patch})

    if body.modules is not None:
        principal.require("settings_modules", "full")
        current_modules = await get_modules(db)
        merged_modules = deep_merge(current_modules, body.modules)
        files_in = body.modules.get("files")
        if isinstance(files_in, dict) and "roots" in files_in:
            try:
                merged_modules.setdefault("files", {})["roots"] = normalize_roots(files_in.get("roots"))
            except FileManError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
        # Persist only the modules document (already merged with defaults on read)
        await set_setting(db, "modules", merged_modules)

        # Sync postgres module enabled → postgres_monitor.enabled
        pg_mod = (body.modules or {}).get("postgres")
        if isinstance(pg_mod, dict) and "enabled" in pg_mod:
            pg_existing = await get_setting(db, "postgres_monitor", DEFAULT_PG_SETTINGS)
            pg_existing["enabled"] = bool(pg_mod["enabled"])
            await set_setting(db, "postgres_monitor", pg_existing)

    if body.postgres is not None:
        principal.require("settings_modules", "full")
        existing = await get_setting(db, "postgres_monitor", DEFAULT_PG_SETTINGS)
        incoming = body.postgres.model_dump(exclude_unset=True)
        merged = _merge_password(incoming, existing)
        await set_setting(db, "postgres_monitor", merged)
        # Keep modules.postgres.enabled in sync when postgres.enabled changes
        if "enabled" in incoming:
            modules = await get_modules(db)
            modules.setdefault("postgres", {})["enabled"] = bool(incoming["enabled"])
            await set_setting(db, "modules", modules)

    return await _bundle(db)
