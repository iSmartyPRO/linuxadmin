from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.principal import Principal, require_module
from app.core.db import get_db
from app.models import MetricSnapshot, PgMetricSnapshot, SshConnectionEvent, SshTunnelSnapshot

router = APIRouter(prefix="/api/history", tags=["history"], dependencies=[Depends(require_module("history", "read"))])


@router.get("/metrics")
async def history_metrics(
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    to_ts = to_ts or now
    from_ts = from_ts or (now - timedelta(hours=6))
    q = (
        select(MetricSnapshot)
        .where(MetricSnapshot.recorded_at >= from_ts, MetricSnapshot.recorded_at <= to_ts)
        .order_by(MetricSnapshot.recorded_at.asc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "recorded_at": r.recorded_at,
            "cpu_percent": r.cpu_percent,
            "memory_percent": r.memory_percent,
            "swap_percent": r.swap_percent,
            "load_1": r.load_1,
            "load_5": r.load_5,
            "load_15": r.load_15,
            "disk_percent": r.disk_percent,
            "net_bytes_sent_rate": r.net_bytes_sent_rate,
            "net_bytes_recv_rate": r.net_bytes_recv_rate,
        }
        for r in rows
    ]


@router.get("/postgres")
async def history_postgres(
    database: Optional[str] = None,
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    to_ts = to_ts or now
    from_ts = from_ts or (now - timedelta(hours=6))
    q = select(PgMetricSnapshot).where(
        PgMetricSnapshot.recorded_at >= from_ts,
        PgMetricSnapshot.recorded_at <= to_ts,
    )
    if database:
        q = q.where(PgMetricSnapshot.database_name == database)
    q = q.order_by(PgMetricSnapshot.recorded_at.asc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "recorded_at": r.recorded_at,
            "database_name": r.database_name,
            "connections": r.connections,
            "max_connections": r.max_connections,
            "cache_hit_ratio": r.cache_hit_ratio,
            "size_bytes": r.size_bytes,
            "commits": r.commits,
            "rollbacks": r.rollbacks,
            "deadlocks": r.deadlocks,
        }
        for r in rows
    ]


@router.get("/ssh-tunnel")
async def history_ssh_tunnel(
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=2000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Time series of active SSH tunnel session counts."""
    now = datetime.now(timezone.utc)
    to_ts = to_ts or now
    from_ts = from_ts or (now - timedelta(hours=6))
    q = (
        select(SshTunnelSnapshot)
        .where(SshTunnelSnapshot.recorded_at >= from_ts, SshTunnelSnapshot.recorded_at <= to_ts)
        .order_by(SshTunnelSnapshot.recorded_at.asc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    out = []
    for r in rows:
        payload = r.payload or {}
        out.append(
            {
                "recorded_at": r.recorded_at,
                "active_count": r.active_count,
                "users_connected": r.users_connected,
                "bytes_sent_total": payload.get("bytes_sent_total"),
                "bytes_recv_total": payload.get("bytes_recv_total"),
                "bytes_sent_rate_total": payload.get("bytes_sent_rate_total"),
                "bytes_recv_rate_total": payload.get("bytes_recv_rate_total"),
            }
        )
    return out


@router.get("/ssh-tunnel/connections")
async def history_ssh_connections(
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    username: Optional[str] = None,
    status: Optional[str] = Query(default=None, description="active|closed"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """Connection log (connect/disconnect) for analysis."""
    now = datetime.now(timezone.utc)
    to_ts = to_ts or now
    from_ts = from_ts or (now - timedelta(hours=24))
    q = select(SshConnectionEvent).where(
        SshConnectionEvent.started_at >= from_ts,
        SshConnectionEvent.started_at <= to_ts,
    )
    if username:
        q = q.where(SshConnectionEvent.username == username)
    if status in ("active", "closed"):
        q = q.where(SshConnectionEvent.status == status)
    q = q.order_by(SshConnectionEvent.started_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    result = []
    for r in rows:
        payload = r.payload or {}
        duration = r.duration_seconds
        if r.status == "active" and r.started_at is not None:
            try:
                started = r.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                duration = max(0, int((now - started).total_seconds()))
            except Exception:
                pass
        result.append(
            {
                "id": r.id,
                "session_key": r.session_key,
                "username": r.username,
                "remote_ip": r.remote_ip,
                "remote_port": r.remote_port,
                "pid": r.pid,
                "status": r.status,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "duration_seconds": duration,
                "forwards_count": r.forwards_count,
                "forwards": payload.get("forwards") or [],
                "remote": payload.get("remote")
                or (f"{r.remote_ip}:{r.remote_port}" if r.remote_ip else None),
                "bytes_sent": payload.get("bytes_sent"),
                "bytes_recv": payload.get("bytes_recv"),
                "bytes_sent_rate": payload.get("bytes_sent_rate"),
                "bytes_recv_rate": payload.get("bytes_recv_rate"),
            }
        )
    return result
