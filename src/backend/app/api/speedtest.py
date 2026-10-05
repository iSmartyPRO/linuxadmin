from __future__ import annotations

import shutil
import socket
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import speedtest as st
from app.core.config import get_settings
from app.core.db import get_db
from app.core.principal import Principal, require_module
from app.core.rate_limit import client_ip
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/speedtest", tags=["speedtest"])

NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}


async def _mod(db: AsyncSession) -> dict:
    return (await get_modules(db)).get("speedtest", {})


def _require_enabled(mod: dict) -> None:
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="Speedtest module is disabled in settings")


def _require_iperf(mod: dict) -> None:
    _require_enabled(mod)
    if not mod.get("allow_iperf", True):
        raise HTTPException(status_code=403, detail="iperf3 is disabled in Speedtest settings")


def _require_ticket(ticket: Optional[str]) -> None:
    if not st.verify_ticket(get_settings().jwt_secret, ticket):
        raise HTTPException(status_code=401, detail="Speedtest ticket missing or expired")


def _job_or_404(job_id: str) -> st.Job:
    job = st.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Info / session ───────────────────────────────────────────────────


@router.get("/info")
async def speedtest_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "read")),
):
    mod = await _mod(db)
    _require_enabled(mod)
    cfg = get_settings()
    return {
        "hostname": socket.gethostname(),
        "client_ip": client_ip(request, trust_proxy=cfg.trust_proxy),
        "server_ip": request.url.hostname,
        "tools": await st.tools_status(),
        "addresses": st.local_addresses(),
        "congestion": {"available": st.congestion_algorithms(), "current": st.current_congestion()},
        "options": mod,
        "can_run": principal.can("speedtest", "full"),
        "jobs": [j.summary() for j in st.jobs.list() if j.active],
    }


@router.post("/session")
async def speedtest_session(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "read")),
):
    """Issue a short-lived ticket for ping/download/upload (no DB hit per request)."""
    _require_enabled(await _mod(db))
    return st.issue_ticket(get_settings().jwt_secret, principal.username)


# ── Browser ↔ panel endpoints (ticket auth) ─────────────────────────


@router.get("/ping")
async def speedtest_ping(x_speedtest_ticket: Optional[str] = Header(default=None)):
    _require_ticket(x_speedtest_ticket)
    return JSONResponse({"t": time.time()}, headers=NO_STORE)


@router.get("/download")
async def speedtest_download(
    bytes_: int = Query(default=25 * 1024 * 1024, alias="bytes", ge=1, le=1024 * 1024 * 1024),
    x_speedtest_ticket: Optional[str] = Header(default=None),
):
    _require_ticket(x_speedtest_ticket)
    headers = {**NO_STORE, "Content-Length": str(bytes_)}
    return StreamingResponse(st.payload_stream(bytes_), media_type="application/octet-stream", headers=headers)


@router.post("/upload")
async def speedtest_upload(request: Request, x_speedtest_ticket: Optional[str] = Header(default=None)):
    _require_ticket(x_speedtest_ticket)
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > 1024 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Upload chunk too large")
    return JSONResponse({"bytes": total, "t": time.time()}, headers=NO_STORE)


class BrowserResultBody(BaseModel):
    ping_ms: Optional[float] = Field(default=None, ge=0, le=100000)
    jitter_ms: Optional[float] = Field(default=None, ge=0, le=100000)
    download_bps: Optional[float] = Field(default=None, ge=0)
    upload_bps: Optional[float] = Field(default=None, ge=0)
    loaded_latency_ms: Optional[float] = Field(default=None, ge=0, le=100000)
    streams: Optional[int] = Field(default=None, ge=1, le=64)
    duration: Optional[float] = Field(default=None, ge=1, le=600)
    user_agent: Optional[str] = Field(default=None, max_length=300)


@router.post("/browser/result")
async def save_browser_result(
    body: BrowserResultBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "read")),
):
    mod = await _mod(db)
    _require_enabled(mod)
    st.append_history(
        mod,
        {
            "kind": "browser",
            "target": socket.gethostname(),
            "client_ip": client_ip(request, trust_proxy=get_settings().trust_proxy),
            "by": principal.username,
            **body.model_dump(exclude_none=True),
        },
    )
    return {"ok": True}


# ── Host ↔ Internet ─────────────────────────────────────────────────


class InternetBody(BaseModel):
    duration: float = Field(default=10, ge=3, le=60)
    streams: int = Field(default=6, ge=1, le=16)
    ping_count: int = Field(default=20, ge=3, le=100)
    download: bool = True
    upload: bool = True
    ip_version: Optional[Literal[4, 6]] = 4


@router.post("/internet/start")
async def internet_start(
    body: InternetBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "full")),
):
    mod = await _mod(db)
    _require_enabled(mod)
    if not mod.get("allow_internet_test", True):
        raise HTTPException(status_code=403, detail="Host ↔ Internet test is disabled in Speedtest settings")
    if st.jobs.active("internet"):
        raise HTTPException(status_code=409, detail="An Internet speed test is already running")
    params = body.model_dump()
    params["duration"] = min(params["duration"], float(mod.get("max_duration_seconds") or 60))
    job = st.jobs.create("internet", principal.username, params)
    st.spawn(job, lambda: st.run_internet_test(job, mod))
    return job.snapshot()


# ── iperf3 ───────────────────────────────────────────────────────────


@router.post("/iperf/install")
async def iperf_install(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("speedtest", "full")),
):
    mod = await _mod(db)
    _require_iperf(mod)
    return await st.install_iperf(mod)


class IperfClientBody(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(default=5201, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    direction: Literal["upload", "download", "bidir"] = "upload"
    duration: int = Field(default=10, ge=1, le=3600)
    parallel: int = Field(default=4, ge=1, le=128)
    interval: float = Field(default=0.5, ge=0.1, le=60)
    omit: int = Field(default=1, ge=0, le=60)
    bitrate: Optional[str] = Field(default=None, max_length=16)
    window: Optional[str] = Field(default=None, max_length=16)
    length: Optional[str] = Field(default=None, max_length=16)
    mss: Optional[int] = Field(default=None, ge=88, le=9216)
    congestion: Optional[str] = Field(default=None, max_length=32)
    no_delay: bool = False
    zerocopy: bool = False
    ip_version: Optional[Literal[4, 6]] = None
    bind: Optional[str] = Field(default=None, max_length=64)
    tos: Optional[int] = Field(default=None, ge=0, le=255)
    connect_timeout_ms: Optional[int] = Field(default=5000, ge=100, le=120000)

    @field_validator("host", "bind")
    @classmethod
    def _host_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if not st.valid_host(v):
            raise ValueError("invalid host name or address")
        return v

    @field_validator("bitrate")
    @classmethod
    def _bitrate_ok(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip()
        if not st._BITRATE_RE.match(v):
            raise ValueError("bitrate must look like 100M, 1G, 500K or 0 (unlimited)")
        return v

    @field_validator("window", "length")
    @classmethod
    def _size_ok(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip()
        if not st._SIZE_RE.match(v):
            raise ValueError("size must look like 128K, 4M or 1460")
        return v

    @field_validator("congestion")
    @classmethod
    def _cc_ok(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if v not in st.congestion_algorithms():
            raise ValueError(f"congestion algorithm not available on this host: {v}")
        return v


def _iperf_binary() -> str:
    binary = shutil.which("iperf3")
    if not binary:
        raise HTTPException(status_code=412, detail="iperf3 is not installed")
    return binary


@router.post("/iperf/client")
async def iperf_client_start(
    body: IperfClientBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "full")),
):
    mod = await _mod(db)
    _require_iperf(mod)
    binary = _iperf_binary()
    max_dur = int(mod.get("max_duration_seconds") or 60)
    if body.duration > max_dur:
        raise HTTPException(status_code=400, detail=f"Duration is limited to {max_dur} s (Settings → Speedtest)")
    max_par = int(mod.get("max_parallel") or 32)
    if body.parallel > max_par:
        raise HTTPException(status_code=400, detail=f"Parallel streams are limited to {max_par} (Settings → Speedtest)")
    if st.jobs.active("iperf_client"):
        raise HTTPException(status_code=409, detail="An iperf3 client test is already running — stop it first")
    job = st.jobs.create("iperf_client", principal.username, body.model_dump())
    st.spawn(job, lambda: st.run_iperf_client(job, binary, mod))
    return job.snapshot()


class IperfServerBody(BaseModel):
    port: int = Field(default=5201, ge=1, le=65535)
    bind: Optional[str] = Field(default=None, max_length=64)
    interval: float = Field(default=0.5, ge=0.1, le=60)
    one_off: bool = False
    ip_version: Optional[Literal[4, 6]] = None
    idle_timeout: Optional[int] = Field(default=None, ge=1, le=86400)
    max_lifetime: Optional[int] = Field(default=3600, ge=0, le=7 * 86400)

    @field_validator("bind")
    @classmethod
    def _bind_ok(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip()
        if not st.valid_host(v):
            raise ValueError("invalid bind address")
        return v


@router.post("/iperf/server")
async def iperf_server_start(
    body: IperfServerBody,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_module("speedtest", "full")),
):
    mod = await _mod(db)
    _require_iperf(mod)
    binary = _iperf_binary()
    running = st.jobs.active("iperf_server")
    if any(j.params.get("port") == body.port for j in running):
        raise HTTPException(status_code=409, detail=f"An iperf3 server is already running on port {body.port}")
    if len(running) >= 4:
        raise HTTPException(status_code=409, detail="Up to 4 iperf3 servers can run at once")
    job = st.jobs.create("iperf_server", principal.username, body.model_dump())
    st.spawn(job, lambda: st.run_iperf_server(job, binary))
    return job.snapshot()


# ── Jobs ─────────────────────────────────────────────────────────────


@router.get("/jobs")
async def list_jobs(_: Principal = Depends(require_module("speedtest", "read"))):
    return {"jobs": [j.summary() for j in st.jobs.list()]}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    since: int = Query(default=0, ge=0),
    log_since: int = Query(default=0, ge=0),
    _: Principal = Depends(require_module("speedtest", "read")),
):
    return _job_or_404(job_id).snapshot(since=since, log_since=log_since)


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str, _: Principal = Depends(require_module("speedtest", "full"))):
    job = _job_or_404(job_id)
    await st.jobs.stop(job)
    return job.summary()


# ── History ──────────────────────────────────────────────────────────


@router.get("/history")
async def get_history(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("speedtest", "read")),
):
    return {"items": st.load_history(await _mod(db))}


@router.delete("/history")
async def clear_history(
    entry_id: Optional[str] = Query(default=None, alias="id", max_length=32),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("speedtest", "full")),
):
    return {"removed": st.delete_history(await _mod(db), entry_id)}
