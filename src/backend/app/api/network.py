from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import network as net_collector
from app.core.auth import get_current_user
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/network", tags=["network"])


class IfaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    state: str = Field(..., description="up|down")


class KillBody(BaseModel):
    pid: int
    signal: str = "TERM"


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("network", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="Network module is disabled in settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Network management is forbidden (enable “Allow management” in Settings)",
        )


@router.get("/overview")
async def network_overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    modules = await get_modules(db)
    if not modules.get("network", {}).get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Network module is disabled in settings",
            "listening": 0,
            "established": 0,
            "total": 0,
            "allow_mutations": False,
        }
    import asyncio

    data = await asyncio.to_thread(net_collector.collect_network_overview)
    data["allow_mutations"] = bool(modules.get("network", {}).get("allow_mutations", False))
    return data


@router.get("")
async def network_details(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Network module is disabled in settings",
            "listening_ports": [],
            "connections": [],
            "interfaces_detail": [],
            "allow_mutations": False,
        }
    import asyncio

    data = await asyncio.to_thread(net_collector.collect_network_details, mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/iface")
async def network_iface(
    body: IfaceBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await net_collector.network_set_iface(body.name, body.state)


@router.post("/kill")
async def network_kill(
    body: KillBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    if not mod.get("allow_kill", True):
        raise HTTPException(status_code=403, detail="Process kill is disabled in settings")
    return await net_collector.network_kill_pid(body.pid, body.signal)
