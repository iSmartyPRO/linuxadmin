from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import fail2ban as f2b
from app.collectors import firewall as fw
from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.principal import Principal, get_principal, require_module
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/security", tags=["security"])


async def _require_any_security(principal: Principal = Depends(get_principal)) -> Principal:
    if not (principal.can("fail2ban", "read") or principal.can("firewall", "read")):
        raise HTTPException(status_code=403, detail="Missing permission: fail2ban|firewall:read")
    return principal


class Fail2banActionBody(BaseModel):
    action: str = Field(
        ...,
        description=(
            "ban|unban|reload|reload-jail|start|stop|restart|"
            "set-params|add-ignoreip|del-ignoreip"
        ),
    )
    jail: Optional[str] = None
    ip: Optional[str] = None
    bantime: Optional[str] = Field(default=None, description="seconds or 10m/1h/1d/-1")
    findtime: Optional[str] = Field(default=None, description="seconds or 10m/1h")
    maxretry: Optional[int] = Field(default=None, ge=1, le=100000)
    persist: bool = Field(
        default=True,
        description="Persist bantime/findtime/maxretry under /etc/fail2ban/jail.d/",
    )


class FirewallActionBody(BaseModel):
    action: str = Field(
        ...,
        description="enable|disable|reload|allow|deny|reject|limit|delete|add-port|remove-port|add-service|remove-service",
    )
    rule: Optional[str] = None
    number: Optional[int] = None
    port: Optional[str] = None
    proto: str = "tcp"
    zone: Optional[str] = None
    source: Optional[str] = None


async def _mod(db: AsyncSession, key: str) -> dict:
    modules = await get_modules(db)
    return modules.get(key, {})


def _require_enabled(mod: dict, label: str) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail=f"{label} module is disabled in settings")


def _require_mutations(mod: dict, label: str) -> None:
    _require_enabled(mod, label)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail=f"{label} management is forbidden (enable “Allow management” in Settings)",
        )


@router.get("/overview")
async def security_overview(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(_require_any_security),
):
    modules = await get_modules(db)
    fail2ban = (
        await f2b.collect_fail2ban_overview()
        if principal.can("fail2ban", "read") and modules.get("fail2ban", {}).get("enabled", True)
        else {"installed": False, "active": False, "disabled": True, "jails_count": 0}
    )
    firewall = (
        await fw.collect_firewall_overview()
        if principal.can("firewall", "read") and modules.get("firewall", {}).get("enabled", True)
        else {"backend": "none", "enabled": False, "disabled": True}
    )
    return {"fail2ban": fail2ban, "firewall": firewall}


@router.get("/fail2ban")
async def fail2ban_details(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("fail2ban", "read")),
):
    mod = await _mod(db, "fail2ban")
    if not mod.get("enabled", True):
        return {
            "installed": False,
            "disabled": True,
            "error": "Fail2ban module is disabled in settings",
            "allow_mutations": False,
        }
    data = await f2b.collect_fail2ban_details(log_lines=int(mod.get("log_lines") or 80))
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/fail2ban/action")
async def fail2ban_action(
    body: Fail2banActionBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("fail2ban", "full")),
):
    mod = await _mod(db, "fail2ban")
    _require_mutations(mod, "Fail2ban")
    return await f2b.fail2ban_action(
        body.action,
        jail=body.jail,
        ip=body.ip,
        bantime=body.bantime,
        findtime=body.findtime,
        maxretry=body.maxretry,
        persist=body.persist,
    )


@router.get("/firewall")
async def firewall_details(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("firewall", "read")),
):
    mod = await _mod(db, "firewall")
    if not mod.get("enabled", True):
        return {
            "backend": "none",
            "disabled": True,
            "error": "Firewall module is disabled in settings",
            "allow_mutations": False,
        }
    data = await fw.collect_firewall_details(log_lines=int(mod.get("log_lines") or 80))
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/firewall/action")
async def firewall_action(
    body: FirewallActionBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("firewall", "full")),
):
    mod = await _mod(db, "firewall")
    _require_mutations(mod, "Firewall")
    return await fw.firewall_action(
        body.action,
        rule=body.rule,
        number=body.number,
        port=body.port,
        proto=body.proto,
        zone=body.zone,
        source=body.source,
    )
