from __future__ import annotations

import secrets
from typing import Any

from app.core.config import ENV_FILE, ROOT, get_settings
from app.core.envfile import read_env_file, upsert_env_file

SETUP_FLAG = "LNXADMIN_SETUP_COMPLETE"


def is_setup_complete() -> bool:
    """True when first-run wizard has finished (or legacy install with DB password)."""
    env = read_env_file(ENV_FILE)
    flag = (env.get(SETUP_FLAG) or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    # Legacy installs: treat as configured if JWT looks set and DB password exists
    cfg = get_settings()
    if flag in {"0", "false", "no", "off"}:
        return False
    if ENV_FILE.is_file() and cfg.db_password and len(cfg.jwt_secret) >= 32:
        if cfg.jwt_secret not in {"change-me", "lnxadmin-dev-secret-change-in-production-7t5E"}:
            return True
    return False


def mark_setup_complete() -> None:
    upsert_env_file(ENV_FILE, {SETUP_FLAG: "true"})
    get_settings.cache_clear()


def generate_jwt_secret() -> str:
    return secrets.token_hex(32)


def apply_bootstrap(updates: dict[str, Any]) -> None:
    """Persist bootstrap keys to `.env` and refresh settings cache."""
    payload: dict[str, str | int | bool] = {}
    mapping = {
        "app_env": "LNXADMIN_ENV",
        "db_host": "LNXADMIN_DB_HOST",
        "db_port": "LNXADMIN_DB_PORT",
        "db_user": "LNXADMIN_DB_USER",
        "db_password": "LNXADMIN_DB_PASSWORD",
        "db_name": "LNXADMIN_DB_NAME",
        "jwt_secret": "LNXADMIN_JWT_SECRET",
        "admin_user": "LNXADMIN_ADMIN_USER",
        "admin_password": "LNXADMIN_ADMIN_PASSWORD",
        "bind_host": "LNXADMIN_BIND_HOST",
        "bind_port": "LNXADMIN_BIND_PORT",
        "cors_origins": "LNXADMIN_CORS_ORIGINS",
        "setup_complete": SETUP_FLAG,
    }
    for src, env_key in mapping.items():
        if src in updates and updates[src] is not None:
            payload[env_key] = updates[src]
    if payload:
        upsert_env_file(ENV_FILE, payload)
        get_settings.cache_clear()


def public_connection_view() -> dict[str, Any]:
    cfg = get_settings()
    return {
        "configured": is_setup_complete(),
        "env": cfg.app_env,
        "db_host": cfg.db_host,
        "db_port": cfg.db_port,
        "db_user": cfg.db_user,
        "db_name": cfg.db_name,
        "db_password_set": bool(cfg.db_password),
        "admin_user": cfg.admin_user,
        "bind_host": cfg.bind_host,
        "bind_port": cfg.bind_port,
        "cors_origins": cfg.cors_origins,
        "jwt_secret_set": bool(cfg.jwt_secret) and len(cfg.jwt_secret) >= 32,
        "env_file": str(ENV_FILE.relative_to(ROOT)) if ENV_FILE.is_relative_to(ROOT) else str(ENV_FILE),
    }
