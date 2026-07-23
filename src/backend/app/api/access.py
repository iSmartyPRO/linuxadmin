"""Panel access control: users, roles, API keys, docs catalog."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import hash_password
from app.core.db import get_db
from app.core.permissions import ACCESS_MODULES, merge_permissions, normalize_level
from app.core.principal import Principal, get_principal, hash_api_key, require_module
from app.models import ApiKey, Role, User
from app.services import module_docs

router = APIRouter(prefix="/api/access", tags=["access"])

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")


class RoleBody(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    slug: Optional[str] = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=500)
    permissions: dict[str, str] = Field(default_factory=dict)


class UserCreateBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)
    role_id: int
    is_active: bool = True
    is_superadmin: bool = False


class UserUpdateBody(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_superadmin: Optional[bool] = None


class ApiKeyCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    user_id: Optional[int] = None
    expires_days: Optional[int] = Field(default=None, ge=1, le=3650)
    permissions: Optional[dict[str, str]] = None


def _public_role(role: Role) -> dict[str, Any]:
    return {
        "id": role.id,
        "name": role.name,
        "slug": role.slug,
        "description": role.description or "",
        "is_system": bool(role.is_system),
        "permissions": merge_permissions(role.permissions),
        "created_at": role.created_at.isoformat() if role.created_at else None,
    }


def _public_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "is_active": bool(user.is_active),
        "is_superadmin": bool(user.is_superadmin),
        "role_id": user.role_id,
        "role": (
            {"id": user.role.id, "name": user.role.name, "slug": user.role.slug}
            if user.role
            else None
        ),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _public_key(key: ApiKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "user_id": key.user_id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "permissions": key.permissions,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "active": key.revoked_at is None,
    }


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return (s or "role")[:64]


def _clean_perms(raw: dict[str, str] | None) -> dict[str, str]:
    return merge_permissions(raw or {})


async def _count_superadmins(db: AsyncSession, exclude_id: int | None = None) -> int:
    q = select(func.count()).select_from(User).where(
        User.is_superadmin.is_(True), User.is_active.is_(True)
    )
    if exclude_id is not None:
        q = q.where(User.id != exclude_id)
    return int((await db.execute(q)).scalar_one())


@router.get("/me")
async def access_me(principal: Principal = Depends(get_principal)):
    return principal.public_dict()


@router.get("/catalog")
async def permission_catalog(_: Principal = Depends(require_module("settings_access", "read"))):
    return {
        "modules": ACCESS_MODULES,
        "levels": [
            {"key": "none", "label": "No access"},
            {"key": "read", "label": "Read only"},
            {"key": "full", "label": "Full (read + changes)"},
        ],
    }


@router.get("/docs")
async def list_docs(principal: Principal = Depends(get_principal)):
    return {"modules": module_docs.list_module_docs(principal)}


@router.get("/docs/api/integration")
async def api_integration_docs(principal: Principal = Depends(get_principal)):
    return module_docs.api_integration_doc()


@router.get("/docs/{doc_key}")
async def get_doc(doc_key: str, principal: Principal = Depends(get_principal)):
    doc = module_docs.get_module_doc(doc_key, principal)
    if not doc:
        raise HTTPException(status_code=404, detail="Documentation not found")
    return doc


# ── Roles ────────────────────────────────────────────────────────────


@router.get("/roles")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("settings_access", "read")),
):
    rows = (await db.execute(select(Role).order_by(Role.name))).scalars().all()
    return {"roles": [_public_role(r) for r in rows]}


@router.post("/roles")
async def create_role(
    body: RoleBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    slug = (body.slug or _slugify(body.name)).lower()
    if not SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="Invalid role slug")
    if slug == "superadmin":
        raise HTTPException(status_code=400, detail="Cannot create another superadmin role")
    exists = await db.execute(select(Role).where((Role.slug == slug) | (Role.name == body.name)))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role name or slug already exists")
    role = Role(
        name=body.name.strip(),
        slug=slug,
        description=(body.description or "")[:500],
        is_system=False,
        permissions=_clean_perms(body.permissions),
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return {"ok": True, "role": _public_role(role)}


@router.put("/roles/{role_id}")
async def update_role(
    role_id: int,
    body: RoleBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.slug == "superadmin" and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="Only Super Admin can edit this role")
    if role.is_system and role.slug == "superadmin":
        # Keep slug; allow description/permissions update only by superadmin
        role.description = (body.description or "")[:500]
        role.permissions = all_full_if_superadmin_role(role, body.permissions)
    else:
        if body.name.strip():
            role.name = body.name.strip()
        role.description = (body.description or "")[:500]
        role.permissions = _clean_perms(body.permissions)
    await db.commit()
    await db.refresh(role)
    return {"ok": True, "role": _public_role(role)}


def all_full_if_superadmin_role(role: Role, perms: dict[str, str]) -> dict[str, str]:
    from app.core.permissions import all_full_permissions

    if role.slug == "superadmin":
        return all_full_permissions()
    return _clean_perms(perms)


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("settings_access", "full")),
):
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    users = await db.execute(select(func.count()).select_from(User).where(User.role_id == role_id))
    if int(users.scalar_one()) > 0:
        raise HTTPException(status_code=400, detail="Role is assigned to users")
    await db.delete(role)
    await db.commit()
    return {"ok": True}


# ── Users ────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("settings_access", "read")),
):
    rows = (
        await db.execute(select(User).options(selectinload(User.role)).order_by(User.username))
    ).scalars().all()
    return {"users": [_public_user(u) for u in rows]}


@router.post("/users")
async def create_user(
    body: UserCreateBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    username = body.username.strip()
    if not NAME_RE.fullmatch(username):
        raise HTTPException(status_code=400, detail="Invalid username")
    if body.password in {"admin", "password", "changeme", "change-me"}:
        raise HTTPException(status_code=400, detail="Choose a stronger password")
    if body.is_superadmin and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="Only Super Admin can create Super Admins")
    role = await db.get(Role, body.role_id)
    if not role:
        raise HTTPException(status_code=400, detail="Role not found")
    exists = await db.execute(select(User).where(User.username == username))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        display_name=(body.display_name or username)[:128],
        role_id=role.id,
        is_active=body.is_active,
        is_superadmin=bool(body.is_superadmin),
    )
    db.add(user)
    await db.commit()
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user.id)
    )
    user = result.scalar_one()
    return {"ok": True, "user": _public_user(user)}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdateBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.is_superadmin is not None:
        if body.is_superadmin and not principal.is_superadmin:
            raise HTTPException(status_code=403, detail="Only Super Admin can grant Super Admin")
        if user.is_superadmin and not body.is_superadmin:
            if await _count_superadmins(db, exclude_id=user.id) < 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last Super Admin")
        user.is_superadmin = body.is_superadmin

    if body.is_active is not None:
        if user.is_superadmin and not body.is_active:
            if await _count_superadmins(db, exclude_id=user.id) < 1:
                raise HTTPException(status_code=400, detail="Cannot disable the last Super Admin")
        user.is_active = body.is_active

    if body.display_name is not None:
        user.display_name = body.display_name[:128]
    if body.password:
        if body.password in {"admin", "password", "changeme", "change-me"}:
            raise HTTPException(status_code=400, detail="Choose a stronger password")
        user.password_hash = hash_password(body.password)
    if body.role_id is not None:
        role = await db.get(Role, body.role_id)
        if not role:
            raise HTTPException(status_code=400, detail="Role not found")
        user.role_id = role.id

    await db.commit()
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.id == user_id)
    )
    return {"ok": True, "user": _public_user(result.scalar_one())}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == principal.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if user.is_superadmin and await _count_superadmins(db, exclude_id=user.id) < 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last Super Admin")
    await db.delete(user)
    await db.commit()
    return {"ok": True}


# ── API keys ─────────────────────────────────────────────────────────


@router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "read")),
):
    q = select(ApiKey).order_by(ApiKey.created_at.desc())
    if not principal.is_superadmin and not principal.can("settings_access", "full"):
        q = q.where(ApiKey.user_id == principal.user_id)
    rows = (await db.execute(q)).scalars().all()
    return {"keys": [_public_key(k) for k in rows]}


@router.post("/api-keys")
async def create_api_key(
    body: ApiKeyCreateBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    target_user_id = body.user_id or principal.user_id
    if target_user_id != principal.user_id and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="Only Super Admin can create keys for other users")
    user = await db.get(User, target_user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Target user not found or inactive")

    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f"lnx_{prefix}_{secret}"
    expires = None
    if body.expires_days:
        expires = datetime.now(timezone.utc) + timedelta(days=body.expires_days)

    perms = None
    if body.permissions:
        perms = {k: normalize_level(v) for k, v in body.permissions.items()}

    key = ApiKey(
        user_id=user.id,
        name=body.name.strip()[:128],
        key_prefix=prefix,
        key_hash=hash_api_key(raw),
        permissions=perms,
        expires_at=expires,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {
        "ok": True,
        "key": _public_key(key),
        "token": raw,
        "warning": "Copy this token now — it will not be shown again.",
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("settings_access", "full")),
):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    if key.user_id != principal.user_id and not principal.is_superadmin:
        raise HTTPException(status_code=403, detail="Cannot revoke another user's key")
    key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
