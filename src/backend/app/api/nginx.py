"""REST API for Nginx Edge Proxy module."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import nginx as ngx
from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.principal import Principal, require_module
from app.services.persistence import get_modules

router = APIRouter(
    prefix="/api/nginx",
    tags=["nginx"],
    dependencies=[Depends(require_module("nginx", "read"))],
)


class BackendBody(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=80, ge=1, le=65535)
    weight: int = Field(default=1, ge=1, le=1000)
    max_fails: int = Field(default=3, ge=0, le=100)
    fail_timeout: str = Field(default="10s", max_length=16)


class HeaderBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    value: str = Field(default="", max_length=512)


class RouteBody(BaseModel):
    id: Optional[str] = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=64)
    domain: Optional[str] = Field(default="", max_length=253)
    aliases: Optional[List[str]] = None
    proxy_type: str = Field(default="http_reverse", max_length=32)
    frontend_ip: Optional[str] = Field(default="0.0.0.0", max_length=64)
    frontend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backend_host: Optional[str] = Field(default=None, max_length=253)
    backend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backends: Optional[List[BackendBody]] = None
    backend_proto: Optional[str] = Field(default="http", max_length=8)
    lb_method: Optional[str] = Field(default="round_robin", max_length=32)
    connect_timeout: Optional[int] = Field(default=60, ge=1, le=86400)
    send_timeout: Optional[int] = Field(default=300, ge=1, le=86400)
    read_timeout: Optional[int] = Field(default=300, ge=1, le=86400)
    client_max_body_size: Optional[str] = Field(default="100m", max_length=16)
    websocket: Optional[bool] = True
    http2: Optional[bool] = True
    headers: Optional[List[HeaderBody]] = None
    verify_backend_tls: Optional[bool] = False
    allow_ips: Optional[List[str]] = None
    deny_ips: Optional[List[str]] = None
    cert_id: Optional[str] = Field(default=None, max_length=40)
    enabled: Optional[bool] = True
    logging: Optional[bool] = True
    tcp_keepalive: Optional[int] = Field(default=60, ge=0, le=86400)
    session_timeout: Optional[int] = Field(default=3600, ge=1, le=604800)
    apply: bool = False


class CertUploadBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    certificate_pem: Optional[str] = Field(default=None, max_length=200_000)
    fullchain_pem: Optional[str] = Field(default=None, max_length=200_000)
    private_key_pem: str = Field(min_length=32, max_length=200_000)
    chain_pem: Optional[str] = Field(default=None, max_length=200_000)


class PfxBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    pfx_base64: str = Field(min_length=16, max_length=2_000_000)
    password: Optional[str] = Field(default="", max_length=256)


class CsrBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    cn: str = Field(min_length=1, max_length=253)
    domain: Optional[str] = Field(default=None, max_length=253)
    sans: Optional[List[str]] = None


class AcmeIssueBody(BaseModel):
    domains: List[str] = Field(min_length=1)
    email: Optional[str] = Field(default=None, max_length=253)
    challenge: str = Field(default="http-01", max_length=16)
    dns_provider_id: Optional[str] = Field(default=None, max_length=40)
    dry_run: bool = False
    manual_dns: bool = False
    skip_public_check: bool = False


class AcmeRenewBody(BaseModel):
    dry_run: bool = False
    test: bool = False
    force: bool = False


class AcmeSettingsBody(BaseModel):
    email: Optional[str] = Field(default=None, max_length=253)
    environment: Optional[str] = Field(default=None, max_length=32)
    directory_url: Optional[str] = Field(default=None, max_length=512)
    auto_renew: Optional[bool] = None
    renew_days_before: Optional[int] = Field(default=None, ge=1, le=90)


class DnsProviderBody(BaseModel):
    id: Optional[str] = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    token: Optional[str] = Field(default=None, max_length=4096)
    api_token: Optional[str] = Field(default=None, max_length=4096)


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    return modules.get("nginx", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="Nginx module is disabled in Settings")


def _require_mutations(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_mutations", False):
        raise HTTPException(
            status_code=403,
            detail="Changes are disabled (enable “Allow changes” for Nginx in Settings)",
        )


@router.get("")
@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    if not mod.get("enabled", True):
        return {
            "available": False,
            "disabled": True,
            "error": "Nginx module is disabled in Settings",
            "routes": [],
            "allow_mutations": False,
        }
    data = await ngx.collect_overview(mod)
    data["allow_mutations"] = bool(mod.get("allow_mutations", False))
    return data


@router.post("/install")
async def install(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.install_tools(mod)


@router.post("/service/{action}")
async def service(
    action: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.service_action(action, mod)


class RouteValidateBody(BaseModel):
    """Loose validate payload (fields optional so templates can be checked early)."""
    id: Optional[str] = Field(default=None, max_length=40)
    name: Optional[str] = Field(default=None, max_length=64)
    domain: Optional[str] = Field(default=None, max_length=253)
    aliases: Optional[List[str]] = None
    proxy_type: Optional[str] = Field(default=None, max_length=32)
    frontend_ip: Optional[str] = Field(default=None, max_length=64)
    frontend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backend_host: Optional[str] = Field(default=None, max_length=253)
    backend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backends: Optional[List[BackendBody]] = None
    backend_proto: Optional[str] = Field(default=None, max_length=8)
    lb_method: Optional[str] = Field(default=None, max_length=32)
    connect_timeout: Optional[int] = Field(default=None, ge=1, le=86400)
    send_timeout: Optional[int] = Field(default=None, ge=1, le=86400)
    read_timeout: Optional[int] = Field(default=None, ge=1, le=86400)
    client_max_body_size: Optional[str] = Field(default=None, max_length=16)
    websocket: Optional[bool] = None
    http2: Optional[bool] = None
    headers: Optional[List[HeaderBody]] = None
    verify_backend_tls: Optional[bool] = None
    allow_ips: Optional[List[str]] = None
    deny_ips: Optional[List[str]] = None
    cert_id: Optional[str] = Field(default=None, max_length=40)
    enabled: Optional[bool] = None
    logging: Optional[bool] = None
    tcp_keepalive: Optional[int] = Field(default=None, ge=0, le=86400)
    session_timeout: Optional[int] = Field(default=None, ge=1, le=604800)
    template_id: Optional[str] = Field(default=None, max_length=64)


class FromTemplateBody(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    name: Optional[str] = Field(default=None, max_length=64)
    domain: Optional[str] = Field(default=None, max_length=253)
    aliases: Optional[List[str]] = None
    frontend_ip: Optional[str] = Field(default=None, max_length=64)
    frontend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backend_host: Optional[str] = Field(default=None, max_length=253)
    backend_port: Optional[int] = Field(default=None, ge=1, le=65535)
    backend_proto: Optional[str] = Field(default=None, max_length=8)
    cert_id: Optional[str] = Field(default=None, max_length=40)
    allow_ips: Optional[List[str]] = None
    deny_ips: Optional[List[str]] = None
    enabled: Optional[bool] = None
    apply: bool = False
    # Allow full override of any route field
    overrides: Optional[dict[str, Any]] = None


@router.get("/templates")
async def templates(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return ngx.list_templates()


@router.get("/routes")
async def routes(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.list_routes(mod)


@router.post("/routes/validate")
async def validate_route(
    body: RouteValidateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    payload = body.model_dump(exclude_unset=True)
    template_id = payload.pop("template_id", None)
    if body.backends is not None:
        payload["backends"] = [b.model_dump() for b in body.backends]
    if body.headers is not None:
        payload["headers"] = [h.model_dump() for h in body.headers]
    # name optional on pure validate — fill placeholder if missing
    if not payload.get("name"):
        payload["name"] = "validate-tmp"
    return await ngx.validate_route(payload, mod, template_id=template_id)


@router.post("/routes/from-template")
async def from_template(
    body: FromTemplateBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    overrides = dict(body.overrides or {})
    for key in (
        "name",
        "domain",
        "aliases",
        "frontend_ip",
        "frontend_port",
        "backend_host",
        "backend_port",
        "backend_proto",
        "cert_id",
        "allow_ips",
        "deny_ips",
        "enabled",
        "apply",
    ):
        val = getattr(body, key)
        if val is not None:
            overrides[key] = val
    return await ngx.create_from_template(body.template_id, overrides, mod)


@router.post("/routes")
async def upsert_route(
    body: RouteBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    payload = body.model_dump(exclude_unset=True)
    if body.backends is not None:
        payload["backends"] = [b.model_dump() for b in body.backends]
    if body.headers is not None:
        payload["headers"] = [h.model_dump() for h in body.headers]
    # Validate first so UI gets structured errors
    check = await ngx.validate_route(payload, mod)
    if not check["ok"]:
        return {
            "ok": False,
            "error": "; ".join(e["message"] for e in check["errors"]) or "Validation failed",
            "errors": check["errors"],
            "warnings": check["warnings"],
        }
    result = await ngx.upsert_route(payload, mod)
    result["warnings"] = check.get("warnings") or []
    return result


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: str,
    apply: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.delete_route(route_id, mod, apply=apply)


@router.get("/config/preview")
async def config_preview(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.generate_config_preview(mod)


@router.post("/config/apply")
async def config_apply(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.apply_config(mod)


@router.get("/backups")
async def backups(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.list_backups(mod)


@router.post("/backups")
async def create_backup(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.create_backup(mod)


@router.post("/backups/{backup_id}/rollback")
async def rollback(
    backup_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.rollback_backup(backup_id, mod)


@router.get("/certificates")
async def certificates(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.list_certificates(mod)


@router.post("/certificates")
async def upload_cert(
    body: CertUploadBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.upload_certificate(body.model_dump(), mod)


@router.post("/certificates/pfx")
async def import_pfx(
    body: PfxBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.import_pfx(body.model_dump(), mod)


@router.post("/certificates/csr")
async def generate_csr(
    body: CsrBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.generate_key_csr(body.model_dump(exclude_unset=True), mod)


@router.delete("/certificates/{cert_id}")
async def delete_cert(
    cert_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.delete_certificate(cert_id, mod)


@router.post("/acme/issue")
async def acme_issue(
    body: AcmeIssueBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.acme_issue(body.model_dump(), mod)


@router.get("/acme/dns-challenge")
async def acme_dns_challenge_status(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.acme_manual_dns_status(mod)


@router.post("/acme/dns-challenge/confirm")
async def acme_dns_challenge_confirm(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.acme_manual_dns_confirm(mod)


@router.post("/acme/renew")
async def acme_renew(
    body: AcmeRenewBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.acme_renew(body.model_dump(), mod)


@router.get("/acme/logs")
async def acme_logs(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.acme_logs(mod, limit=limit)


@router.put("/acme/settings")
async def acme_settings(
    body: AcmeSettingsBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.update_acme_settings(body.model_dump(exclude_unset=True), mod)


@router.get("/dns-providers")
async def dns_providers(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.list_dns_providers(mod)


@router.post("/dns-providers")
async def upsert_dns(
    body: DnsProviderBody,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.upsert_dns_provider(body.model_dump(exclude_unset=True), mod)


@router.delete("/dns-providers/{provider_id}")
async def delete_dns(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.delete_dns_provider(provider_id, mod)


@router.post("/dns-providers/{provider_id}/test")
async def test_dns(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
    _write: Principal = Depends(require_module("nginx", "full")),
):
    mod = await _mod(db)
    _require_mutations(mod)
    return await ngx.test_dns_provider(provider_id, mod)


@router.get("/logs")
async def logs(
    kind: str = Query(default="error"),
    lines: Optional[int] = Query(default=None, ge=10, le=2000),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.read_logs(kind, mod, lines=lines)


@router.get("/backends/health")
async def backends_health(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    return await ngx.probe_backends(mod)


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_db), _: str = Depends(get_current_user)):
    mod = await _mod(db)
    _require_enabled(mod)
    text = await ngx.prometheus_metrics(mod)
    return Response(content=text, media_type="text/plain; version=0.0.4")
