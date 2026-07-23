from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import create_access_token, verify_password
from app.core.config import get_settings
from app.core.db import get_db
from app.core.principal import Principal, get_principal, principal_from_user
from app.core.rate_limit import client_ip, login_limiter
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    user: dict | None = None


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    ip = client_ip(request, trust_proxy=settings.trust_proxy)
    key = f"login:{ip}"
    login_limiter.check(key)

    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()
    ok = bool(
        user is not None
        and user.is_active
        and verify_password(body.password, user.password_hash)
    )
    if not ok:
        login_limiter.hit(key)
        await asyncio.sleep(0.35)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    login_limiter.clear(key)
    token = create_access_token(user.username, settings)  # type: ignore[union-attr]
    principal = principal_from_user(user)  # type: ignore[arg-type]
    return TokenResponse(
        access_token=token,
        username=user.username,  # type: ignore[union-attr]
        user=principal.public_dict(),
    )


@router.get("/me")
async def me(principal: Principal = Depends(get_principal)):
    return principal.public_dict()
