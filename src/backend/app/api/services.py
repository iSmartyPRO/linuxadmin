from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import services as svc
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/services", tags=["services"], dependencies=[Depends(require_module("services", "read"))])

ALLOWED = {"start", "stop", "restart", "reload", "enable", "disable"}


class ActionBody(BaseModel):
    action: str = Field(..., description="start|stop|restart|reload|enable|disable")


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("services", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="Services module is disabled in settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Service management is forbidden (enable “Allow management” in Settings)",
        )


@router.get("")
@router.get("/overview")
async def services_overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Services module is disabled in settings",
            "services": [],
            "counts": {},
            "allow_mutations": False,
        }
    data = await svc.collect_services_overview(mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.get("/{unit}")
async def service_details(
    unit: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    data = await svc.collect_service_details(unit, log_lines=int(mod.get("log_lines") or 80))
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/{unit}/action")
async def service_action(
    unit: str,
    body: ActionBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("services", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    action = (body.action or "").strip().lower()
    if action not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    # Optional deny list from settings
    denied = mod.get("denied_units") or []
    if isinstance(denied, list) and unit in denied:
        raise HTTPException(status_code=403, detail=f"Unit {unit} is in the deny-list")
    return await svc.service_action(unit, action)
