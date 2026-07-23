from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import ssh_tunnel as tun
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/ssh-tunnel", tags=["ssh-tunnel"], dependencies=[Depends(require_module("ssh_tunnel", "read"))])


class Destination(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    label: str = Field(default="", max_length=64)


class CreateUserBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    comment: str = Field(default="", max_length=128)
    destinations: List[Destination] = Field(default_factory=list)


class DestinationsBody(BaseModel):
    destinations: List[Destination] = Field(default_factory=list)


class AddKeyBody(BaseModel):
    public_key: str = Field(min_length=32, max_length=8192)
    comment: Optional[str] = Field(default=None, max_length=80)


class GenerateKeyBody(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=128)
    key_type: str = Field(default="rsa", description="rsa (default, -b 4096) or ed25519")
    bits: int = Field(default=4096, ge=2048, le=8192)


class SshConfigBody(BaseModel):
    host_alias: Optional[str] = None
    identity_file: Optional[str] = None
    local_port_mode: str = Field(
        default="random",
        description="random|same|custom — local port for LocalForward",
    )
    local_forwards: Optional[List[dict[str, Any]]] = None


class EnsureBody(BaseModel):
    reload_sshd: bool = False


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("ssh_tunnel", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="SSH Tunnel module is disabled in settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Changes are forbidden (enable “Allow changes” for SSH Tunnel in Settings)",
        )


@router.get("")
@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "SSH Tunnel module is disabled in settings",
            "users": [],
            "count": 0,
            "allow_mutations": False,
        }
    data = await tun.collect_overview(mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.get("/sessions")
async def sessions(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    if not mod.get("show_sessions", True):
        return {
            "available": False,
            "error": "Session display is disabled in settings",
            "active_count": 0,
            "sessions": [],
        }
    return await asyncio.to_thread(tun.collect_active_sessions, mod)


@router.post("/ensure")
async def ensure_infra(
    body: EnsureBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.ensure_infra(mod, reload_sshd=body.reload_sshd)


@router.get("/users/{username}")
async def user_detail(
    username: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    data = await tun.collect_user_detail(username, mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/users")
async def create_user(
    body: CreateUserBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.create_tunnel_user(
        body.username,
        comment=body.comment,
        destinations=[d.model_dump() for d in body.destinations],
        options=mod,
    )


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.delete_tunnel_user(username, remove_home=True, options=mod)


@router.put("/users/{username}/destinations")
async def set_destinations(
    username: str,
    body: DestinationsBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.set_destinations(
        username,
        [d.model_dump() for d in body.destinations],
        options=mod,
    )


@router.post("/users/{username}/keys")
async def add_key(
    username: str,
    body: AddKeyBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.add_public_key(
        username, body.public_key, comment=body.comment, options=mod
    )


@router.post("/users/{username}/keys/generate")
async def generate_key(
    username: str,
    body: GenerateKeyBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.generate_keypair(
        username,
        comment=body.comment,
        key_type=body.key_type,
        bits=body.bits,
        options=mod,
    )


@router.delete("/users/{username}/keys")
async def delete_key(
    username: str,
    fingerprint: str = Query(..., min_length=8),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await tun.remove_public_key(username, fingerprint, options=mod)


@router.get("/users/{username}/ssh-config")
async def ssh_config_get(
    username: str,
    local_port_mode: str = Query("random"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return tun.build_ssh_config(
        username, options=mod, local_port_mode=local_port_mode
    )


@router.post("/users/{username}/ssh-config")
async def ssh_config_post(
    username: str,
    body: SshConfigBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("ssh_tunnel", "full")),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return tun.build_ssh_config(
        username,
        options=mod,
        local_forwards=body.local_forwards,
        local_port_mode=body.local_port_mode,
        identity_file=body.identity_file,
        host_alias=body.host_alias,
    )
