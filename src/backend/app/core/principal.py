"""Authenticated principal (JWT user or API key) with RBAC permissions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.permissions import (
    LEVEL_RANK,
    PermLevel,
    all_full_permissions,
    level_at_least,
    merge_permissions,
    normalize_level,
)
from app.models import ApiKey, User

security = HTTPBearer(auto_error=False)
Need = Literal["read", "full"]


def hash_api_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _min_level(a: PermLevel, b: PermLevel) -> PermLevel:
    return a if LEVEL_RANK[normalize_level(a)] <= LEVEL_RANK[normalize_level(b)] else b


@dataclass
class Principal:
    user_id: int
    username: str
    display_name: str
    is_superadmin: bool
    role_id: int | None
    role_name: str | None
    role_slug: str | None
    permissions: dict[str, PermLevel] = field(default_factory=dict)
    auth_via: str = "jwt"  # jwt | api_key
    api_key_id: int | None = None

    def can(self, module: str, need: Need = "read") -> bool:
        if self.is_superadmin:
            return True
        have = normalize_level(self.permissions.get(module, "none"))
        return level_at_least(have, need)

    def require(self, module: str, need: Need = "read") -> None:
        if not self.can(module, need):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {module}:{need}",
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "is_superadmin": self.is_superadmin,
            "role": (
                {"id": self.role_id, "name": self.role_name, "slug": self.role_slug}
                if self.role_id
                else None
            ),
            "permissions": self.permissions,
            "auth_via": self.auth_via,
            "api_key_id": self.api_key_id,
        }


def principal_from_user(
    user: User,
    *,
    auth_via: str = "jwt",
    api_key_id: int | None = None,
    key_perms: dict[str, Any] | None = None,
) -> Principal:
    if user.is_superadmin:
        perms = all_full_permissions()
    else:
        role_perms = (user.role.permissions if user.role else {}) or {}
        perms = merge_permissions(role_perms)
        if key_perms:
            # API key may only narrow permissions, never expand
            perms = {
                k: _min_level(perms[k], normalize_level(key_perms[k])) if k in key_perms else perms[k]
                for k in perms
            }
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or "",
        is_superadmin=bool(user.is_superadmin),
        role_id=user.role_id,
        role_name=user.role.name if user.role else None,
        role_slug=user.role.slug if user.role else None,
        permissions=perms,
        auth_via=auth_via,
        api_key_id=api_key_id,
    )


async def resolve_bearer(
    token: str,
    db: AsyncSession,
    settings: Settings,
) -> Principal:
    if token.startswith("lnx_"):
        parts = token.split("_", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise HTTPException(status_code=401, detail="Invalid API key")
        prefix = parts[1][:12]
        digest = hash_api_key(token)
        result = await db.execute(
            select(ApiKey)
            .options(selectinload(ApiKey.user).selectinload(User.role))
            .where(
                ApiKey.key_prefix == prefix,
                ApiKey.key_hash == digest,
                ApiKey.revoked_at.is_(None),
            )
        )
        matched = result.scalar_one_or_none()
        if matched is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        now = datetime.now(timezone.utc)
        exp = matched.expires_at
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                raise HTTPException(status_code=401, detail="API key expired")
        user = matched.user
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="API key user inactive")
        matched.last_used_at = now
        await db.commit()
        return principal_from_user(
            user,
            auth_via="api_key",
            api_key_id=matched.id,
            key_perms=matched.permissions,
        )

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.username == str(sub))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or not found")
    return principal_from_user(user, auth_via="jwt")


async def get_principal(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif x_api_key:
        token = x_api_key.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await resolve_bearer(token, db, settings)


def require_module(module: str, need: Need = "read"):
    async def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        principal.require(module, need)
        return principal

    return _dep


async def get_current_user(principal: Principal = Depends(get_principal)) -> str:
    """Back-compat: returns username string."""
    return principal.username
