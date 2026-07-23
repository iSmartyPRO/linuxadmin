from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import users as users_collector
from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_module("users", "read"))])


class CreateUserBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: Optional[str] = Field(default=None, max_length=128)
    shell: str = "/bin/bash"
    home: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    create_home: bool = True
    comment: str = ""


class LockBody(BaseModel):
    locked: bool


class ShellBody(BaseModel):
    shell: str


class GroupsBody(BaseModel):
    groups: List[str] = Field(default_factory=list)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class CreateGroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class GroupMemberBody(BaseModel):
    username: str


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("users", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="Users module is disabled in settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="User changes are forbidden (enable “Allow changes” in Settings)",
        )


@router.get("")
@router.get("/overview")
async def users_overview(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Users module is disabled in settings",
            "users": [],
            "groups": [],
            "allow_mutations": False,
        }
    data = await asyncio.to_thread(users_collector.collect_users_overview, mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.get("/groups")
async def groups_list(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    data = await users_overview(db=db, _=_)
    return {
        "available": data.get("available"),
        "disabled": data.get("disabled"),
        "error": data.get("error"),
        "groups": data.get("groups") or [],
        "allow_mutations": data.get("allow_mutations", False),
    }


@router.get("/groups/{name}")
async def group_details(
    name: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await asyncio.to_thread(users_collector.collect_group_details, name)


@router.post("/groups")
async def create_group(
    body: CreateGroupBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.create_group(body.name)


@router.delete("/groups/{name}")
async def delete_group(
    name: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.delete_group(
        name,
        min_gid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )


@router.post("/groups/{name}/members")
async def add_member(
    name: str,
    body: GroupMemberBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.add_user_to_group(body.username, name)


@router.delete("/groups/{name}/members/{username}")
async def remove_member(
    name: str,
    username: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.remove_user_from_group(username, name)


@router.post("")
async def create_user(
    body: CreateUserBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.create_user(
        username=body.username,
        password=body.password,
        shell=body.shell,
        home=body.home,
        groups=body.groups,
        create_home=body.create_home,
        comment=body.comment,
    )


@router.get("/{username}")
async def user_details(
    username: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    data = await asyncio.to_thread(users_collector.collect_user_details, username, mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.delete("/{username}")
async def delete_user(
    username: str,
    remove_home: bool = False,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.delete_user(
        username,
        remove_home=remove_home,
        min_uid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )


@router.post("/{username}/lock")
async def lock_user(
    username: str,
    body: LockBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.set_user_locked(
        username,
        body.locked,
        min_uid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )


@router.post("/{username}/shell")
async def change_shell(
    username: str,
    body: ShellBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.set_user_shell(
        username,
        body.shell,
        min_uid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )


@router.post("/{username}/groups")
async def set_groups(
    username: str,
    body: GroupsBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.set_user_groups(
        username,
        body.groups,
        min_uid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )


@router.post("/{username}/password")
async def set_password(
    username: str,
    body: PasswordBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("users", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await users_collector.set_user_password(
        username,
        body.password,
        min_uid=int(mod.get("min_uid") or 1000),
        allow_system=bool(mod.get("allow_system_mutations", False)),
    )
