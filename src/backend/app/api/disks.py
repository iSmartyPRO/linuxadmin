from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import disks as disks_collector
from app.core.auth import get_current_user
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/disks", tags=["disks"])


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("disks", {})


@router.get("/overview")
async def disks_overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Disks module is disabled in settings",
            "count": 0,
            "partitions": [],
        }
    data = await asyncio.to_thread(disks_collector.collect_disks_overview, mod)
    return {
        "available": data.get("available", True),
        "count": data.get("count", 0),
        "partitions": data.get("partitions", []),
        "used_total": sum(p.get("used", 0) for p in data.get("partitions", [])),
        "free_total": sum(p.get("free", 0) for p in data.get("partitions", [])),
    }


@router.get("")
async def disks_details(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Disks module is disabled in settings",
            "partitions": [],
            "io": {"devices": []},
        }
    return await asyncio.to_thread(disks_collector.collect_disks_overview, mod)


@router.get("/browse")
async def disks_browse(
    path: str = Query("/", description="Absolute path to browse"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Disks module is disabled in settings",
            "entries": [],
        }
    if not mod.get("allow_browse", True):
        return {
            "available": False,
            "error": "Directory browsing is disabled in module settings",
            "entries": [],
        }
    return await asyncio.to_thread(disks_collector.browse_path, path, mod)
