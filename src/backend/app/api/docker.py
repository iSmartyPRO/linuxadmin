from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import docker as docker_collector
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/docker", tags=["docker"], dependencies=[Depends(require_module("docker", "read"))])


@router.get("/overview")
async def docker_overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    modules = await get_modules(db)
    if not modules.get("docker", {}).get("enabled", True):
        return {
            "installed": False,
            "available": False,
            "active": False,
            "disabled": True,
            "error": "Docker module is disabled in settings",
        }
    return await docker_collector.collect_docker_overview()


@router.get("")
async def docker_details(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    modules = await get_modules(db)
    docker_mod = modules.get("docker", {})
    if not docker_mod.get("enabled", True):
        return {
            "installed": False,
            "available": False,
            "active": False,
            "disabled": True,
            "error": "Docker module is disabled in settings",
            "containers_list": [],
            "stats": [],
            "images_list": [],
            "volumes_list": [],
            "networks_list": [],
            "disk_usage": None,
            "info": None,
        }
    return await docker_collector.collect_docker_details(docker_mod)
