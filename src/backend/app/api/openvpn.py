from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import openvpn as ovpn
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/openvpn", tags=["openvpn"], dependencies=[Depends(require_module("openvpn", "read"))])


class ServerBody(BaseModel):
    network: Optional[str] = Field(default="10.8.0.0/24", max_length=64)
    port: Optional[int] = Field(default=1194, ge=1, le=65535)
    proto: Optional[str] = Field(default="udp", max_length=8)
    dev: Optional[str] = Field(default="tun", max_length=8)
    dns: Optional[str] = Field(default=None, max_length=256)
    endpoint_host: Optional[str] = Field(default=None, max_length=253)
    cipher: Optional[str] = Field(default="AES-256-GCM", max_length=64)
    auth: Optional[str] = Field(default="SHA256", max_length=64)
    nat_enabled: Optional[bool] = True
    wan_interface: Optional[str] = Field(default=None, max_length=64)
    client_to_client: Optional[bool] = True
    compress: Optional[str] = Field(default="off", max_length=16)
    max_clients: Optional[int] = Field(default=100, ge=1, le=1000)
    keepalive: Optional[str] = Field(default="10 120", max_length=32)


class ClientCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    route_mode: str = Field(default="full")
    push_routes: Optional[List[str]] = None
    dns: Optional[str] = Field(default=None, max_length=256)
    notes: Optional[str] = Field(default="", max_length=200)
    apply: bool = True


class ClientUpdateBody(BaseModel):
    route_mode: Optional[str] = None
    push_routes: Optional[List[str]] = None
    dns: Optional[str] = Field(default=None, max_length=256)
    enabled: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=200)
    apply: bool = True


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("openvpn", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="OpenVPN module is disabled in Settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Changes are disabled (enable “Allow changes” for OpenVPN in Settings)",
        )


@router.get("")
@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "OpenVPN module is disabled in Settings",
            "clients": [],
            "allow_mutations": False,
        }
    data = await ovpn.collect_overview(mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/install")
async def install(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.install_tools(mod)


@router.post("/server")
async def upsert_server(
    body: ServerBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.create_or_update_server(body.model_dump(exclude_unset=True), mod)


@router.post("/server/apply")
async def apply_server(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.apply_server(mod)


@router.post("/server/stop")
async def stop_server(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.stop_server(mod)


@router.post("/clients")
async def create_client(
    body: ClientCreateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.create_client(body.model_dump(), mod)


@router.put("/clients/{client_id}")
async def update_client(
    client_id: str,
    body: ClientUpdateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.update_client(client_id, body.model_dump(exclude_unset=True), mod)


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("openvpn", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ovpn.delete_client(client_id, mod)


@router.get("/clients/{client_id}/config")
async def client_config(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ovpn.get_client_config(client_id, mod)
