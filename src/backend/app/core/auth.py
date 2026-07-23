from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings, get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings | None = None) -> str:
    """Decode JWT and return subject; raises JWTError on failure."""
    settings = settings or get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    sub = payload.get("sub")
    if not sub:
        raise JWTError("missing sub")
    return str(sub)


# Re-export RBAC auth helpers so existing `from app.core.auth import get_current_user` keeps working.
from app.core.principal import get_current_user, get_principal, require_module  # noqa: E402

__all__ = [
    "verify_password",
    "hash_password",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "get_principal",
    "require_module",
]
