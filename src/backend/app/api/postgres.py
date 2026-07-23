from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import postgres as pg
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.config import get_settings
from app.core.db import get_db
from app.services.persistence import DEFAULT_PG_SETTINGS, get_setting, set_setting

router = APIRouter(prefix="/api/postgres", tags=["postgres"], dependencies=[Depends(require_module("postgres", "read"))])

PASSWORD_MASK = "********"


class PostgresSettingsUpdate(BaseModel):
    enabled: bool = True
    record_history: bool = True
    databases: List[str] = Field(default_factory=list)
    interval_seconds: int = Field(default=30, ge=10, le=3600)
    collect_statements: bool = True
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


class TestConnectionBody(BaseModel):
    """Optional overrides for a one-shot probe (does not persist)."""
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


def _public_settings(raw: dict[str, Any]) -> dict[str, Any]:
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


async def _monitor_settings(db: AsyncSession) -> dict[str, Any]:
    return await get_setting(db, "postgres_monitor", DEFAULT_PG_SETTINGS)


def _merge_password_on_update(
    incoming: dict[str, Any], existing: dict[str, Any]
) -> dict[str, Any]:
    merged = {**DEFAULT_PG_SETTINGS, **existing, **incoming}
    pwd = incoming.get("password")
    if pwd is None or pwd == "" or pwd == PASSWORD_MASK:
        if "password" in existing:
            merged["password"] = existing["password"]
        else:
            merged.pop("password", None)
    return merged


@router.get("/status")
async def postgres_status(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    from app.services.persistence import get_modules

    modules = await get_modules(db)
    if not modules.get("postgres", {}).get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "PostgreSQL module is disabled in settings",
        }
    ms = await _monitor_settings(db)
    return await pg.collect_postgres_summary(ms)


@router.post("/test-connection")
async def postgres_test_connection(
    body: TestConnectionBody | None = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("postgres", "full")),
):
    ms = await _monitor_settings(db)
    probe = {**ms}
    if body:
        data = body.model_dump(exclude_unset=True)
        for key, val in data.items():
            if val is None:
                continue
            if key == "password" and val == PASSWORD_MASK:
                continue
            probe[key] = val
        if body.password in (None, "", PASSWORD_MASK):
            probe["password"] = ms.get("password") or ""
    return await pg.test_connection(probe)


@router.get("/activity")
async def postgres_activity(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    try:
        ms = await _monitor_settings(db)
        return await pg.collect_postgres_activity(ms)
    except Exception as exc:
        return {"error": str(exc), "rows": []}


@router.get("/databases")
async def postgres_databases(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    try:
        ms = await _monitor_settings(db)
        return {"databases": await pg.list_databases(ms)}
    except Exception as exc:
        return {"databases": [], "error": str(exc)}


@router.get("/statements")
async def postgres_statements(
    limit: int = Query(default=30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    try:
        ms = await _monitor_settings(db)
        return await pg.collect_postgres_statements(ms, limit=limit)
    except Exception as exc:
        return {"available": False, "error": str(exc), "statements": []}


@router.get("/tables")
async def postgres_tables(
    database: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    try:
        ms = await _monitor_settings(db)
        return await pg.collect_postgres_tables(ms, database=database)
    except Exception as exc:
        return {"error": str(exc), "rows": []}


@router.get("/locks")
async def postgres_locks(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    try:
        ms = await _monitor_settings(db)
        return await pg.collect_postgres_locks(ms)
    except Exception as exc:
        return {"error": str(exc), "rows": []}


@router.get("/settings")
async def get_postgres_settings(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    raw = await _monitor_settings(db)
    return _public_settings(raw)


@router.put("/settings")
async def put_postgres_settings(
    body: PostgresSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("postgres", "full")),
):
    existing = await _monitor_settings(db)
    merged = _merge_password_on_update(body.model_dump(exclude_unset=True), existing)
    saved = await set_setting(db, "postgres_monitor", merged)
    return _public_settings(saved)
