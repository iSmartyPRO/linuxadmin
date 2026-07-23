from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import wireguard as wg
from app.core.auth import get_current_user
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/wireguard", tags=["wireguard"])


class ServerBody(BaseModel):
    interface: Optional[str] = Field(default="wg0", max_length=15)
    address: Optional[str] = Field(default="10.66.0.1/24", max_length=64)
    listen_port: Optional[int] = Field(default=51820, ge=1, le=65535)
    dns: Optional[str] = Field(default=None, max_length=256)
    endpoint: Optional[str] = Field(default=None, max_length=253)
    mtu: Optional[int] = Field(default=1420, ge=1280, le=9000)
    nat_enabled: Optional[bool] = True
    wan_interface: Optional[str] = Field(default=None, max_length=64)
    rotate_keys: bool = False


class PeerCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    address: Optional[str] = Field(default=None, max_length=64)
    route_mode: str = Field(default="full")
    allowed_ips_client: Optional[List[str]] = None
    dns: Optional[str] = Field(default=None, max_length=256)
    persistent_keepalive: int = Field(default=25, ge=0, le=600)
    use_preshared_key: bool = True
    notes: Optional[str] = Field(default="", max_length=200)
    apply: bool = True


class PeerUpdateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=32)
    address: Optional[str] = Field(default=None, max_length=64)
    route_mode: Optional[str] = None
    allowed_ips_client: Optional[List[str]] = None
    dns: Optional[str] = Field(default=None, max_length=256)
    persistent_keepalive: Optional[int] = Field(default=None, ge=0, le=600)
    enabled: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=200)
    apply: bool = True


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("wireguard", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="WireGuard module is disabled in Settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Changes are disabled (enable “Allow changes” for WireGuard in Settings)",
        )


@router.get("")
@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "WireGuard module is disabled in Settings",
            "peers": [],
            "allow_mutations": False,
        }
    data = await wg.collect_overview(mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/install")
async def install(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.install_tools(mod)


@router.post("/server")
async def upsert_server(
    body: ServerBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.create_or_update_server(body.model_dump(exclude_unset=True), mod)


@router.post("/server/apply")
async def apply_server(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.apply_server(mod)


@router.post("/server/stop")
async def stop_server(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.stop_server(mod)


@router.post("/peers")
async def create_peer(
    body: PeerCreateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.create_peer(body.model_dump(), mod)


@router.put("/peers/{peer_id}")
async def update_peer(
    peer_id: str,
    body: PeerUpdateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.update_peer(peer_id, body.model_dump(exclude_unset=True), mod)


@router.delete("/peers/{peer_id}")
async def delete_peer(
    peer_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await wg.delete_peer(peer_id, mod)


@router.get("/peers/{peer_id}/config")
async def peer_config(
    peer_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await wg.get_peer_config(peer_id, mod)
