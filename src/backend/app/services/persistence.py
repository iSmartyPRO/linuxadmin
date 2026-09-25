from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import postgres as pg_collector
from app.collectors import ssh_tunnel as ssh_tunnel_collector
from app.collectors.system import collect_system_metrics
from app.core.config import get_settings
from app.collectors import wireguard as wireguard_collector
from app.models import (
    AppSetting,
    MetricSnapshot,
    PgMetricSnapshot,
    SshConnectionEvent,
    SshTunnelSnapshot,
    User,
    WireGuardConnectionEvent,
    WireGuardSnapshot,
)
from app.core.auth import hash_password


DEFAULT_PG_SETTINGS = {
    "enabled": True,
    "record_history": True,
    "databases": [],
    "interval_seconds": 30,
    "collect_statements": True,
    # Monitor connection (empty = fall back to LNXADMIN_DB_* / app DB)
    "host": "",
    "port": None,
    "username": "",
    "password": "",
    "database": "",
}

# Project-level tunables (DB overrides env defaults when set)
DEFAULT_APP_CONFIG = {
    "name": "Linux Admin",
    "metrics_interval_seconds": 1.5,
    "history_interval_seconds": 15,
    "retention_days": 30,
}

# Monitoring modules — all enabled by default; fine options per module
DEFAULT_MODULES = {
    "overview": {
        "enabled": True,
        "live_metrics": True,
        "gauges": True,
        "charts": True,
        "disks": True,
        "processes": True,
        "temperatures": True,
    },
    "history": {
        "enabled": True,
        "record": True,
    },
    "fail2ban": {
        "enabled": True,
        "show_logs": True,
        "log_lines": 80,
        "allow_mutations": False,
        "allow_install": True,
    },
    "firewall": {
        "enabled": True,
        "show_raw": True,
        "show_logs": True,
        "log_lines": 80,
        "allow_mutations": False,
    },
    "docker": {
        "enabled": True,
        "collect_stats": True,
        "collect_disk": True,
        "collect_info": True,
        "show_info_raw": True,
    },
    "network": {
        "enabled": True,
        "show_listening": True,
        "show_established": True,
        "show_other": True,
        "show_interfaces": True,
        "include_localhost": True,
        "max_rows": 500,
        "allow_mutations": False,
        "allow_kill": True,
    },
    "disks": {
        "enabled": True,
        "allow_browse": True,
        "include_pseudo": False,
        "max_entries": 500,
        "scan_timeout_seconds": 25,
    },
    "users": {
        "enabled": True,
        "allow_mutations": False,
        "show_system_accounts": False,
        "allow_system_mutations": False,
        "min_uid": 1000,
    },
    "services": {
        "enabled": True,
        "allow_mutations": False,
        "show_inactive": True,
        "log_lines": 80,
        "denied_units": [],
    },
    "postgres": {
        "enabled": True,
    },
    "ssh_tunnel": {
        "enabled": True,
        "allow_mutations": False,
        "username_prefix": "tun-",
        "group": "lnxadmin-tunnel",
        "data_dir": "/var/lib/lnxadmin/ssh-tunnels",
        "home_base": "/var/lib/lnxadmin/ssh-homes",
        "sshd_dropin": "/etc/ssh/sshd_config.d/99-lnxadmin-tunnels.conf",
        "public_hostname": "",
        "public_port": 22,
        "listen_port": 22,
        "show_sessions": True,
        "record_history": True,
        "history_interval_seconds": 15,
    },
    "wireguard": {
        "enabled": True,
        "allow_mutations": False,
        "allow_install": True,
        "data_dir": "/var/lib/lnxadmin/wireguard",
        "wg_conf_dir": "/etc/wireguard",
        "interface": "wg0",
        "default_address": "10.66.0.1/24",
        "default_listen_port": 51820,
        "default_dns": "1.1.1.1, 8.8.8.8",
        "endpoint_host": "",
        # Monitoring / load controls
        "show_live_peers": True,  # parse wg dump + show online panel (cheap)
        "show_ip_map": True,  # phpIPAM-style address grid on the page
        "record_history": False,  # opt-in: write connect/disconnect archive to DB
        "history_interval_seconds": 30,
        "online_handshake_seconds": 180,  # peer considered online if handshake newer than this
    },
    "openvpn": {
        "enabled": True,
        "allow_mutations": False,
        "allow_install": True,
        "data_dir": "/var/lib/lnxadmin/openvpn",
        "conf_dir": "/etc/openvpn/server",
        "instance": "lnxadmin",
        "default_network": "10.8.0.0/24",
        "default_port": 1194,
        "default_proto": "udp",
        "default_dns": "1.1.1.1, 8.8.8.8",
        "endpoint_host": "",
    },
    "nginx": {
        "enabled": True,
        "allow_mutations": False,
        "allow_install": True,
        "data_dir": "/var/lib/lnxadmin/nginx",
        "managed_dir": "/etc/nginx/lnxadmin",
        "nginx_conf": "/etc/nginx/nginx.conf",
        "http_include": "/etc/nginx/conf.d/00-lnxadmin.conf",
        "acme_email": "",
        "acme_environment": "production",
        "acme_directory_url": "",
        "renew_days_before": 30,
        "log_lines": 120,
    },
    "files": {
        "enabled": True,
        "allow_mutations": False,
        "show_hidden": False,
        "max_preview_mb": 2,
        "max_upload_mb": 50,
        "roots": [],
    },
}


def deep_merge(default: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively merge stored JSON over defaults (nested dicts only)."""
    result: dict[str, Any] = dict(default)
    if not stored:
        return result
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def get_app_config(session: AsyncSession) -> dict[str, Any]:
    env = get_settings()
    base = {
        **DEFAULT_APP_CONFIG,
        "name": DEFAULT_APP_CONFIG["name"],
        "metrics_interval_seconds": float(env.metrics_interval),
        "history_interval_seconds": float(env.history_interval),
        "retention_days": int(env.retention_days),
    }
    stored = await get_setting(session, "app_config", {})
    return deep_merge(base, stored)


async def get_modules(session: AsyncSession) -> dict[str, Any]:
    stored = await get_setting(session, "modules", {})
    return deep_merge(DEFAULT_MODULES, stored)


async def ensure_admin_user(session: AsyncSession) -> None:
    """Create admin from .env on first boot only (as Super Admin).

    Existing DB password hashes are never overwritten from `.env` on restart
    (change password via Settings → Connection, which updates both DB and `.env`).
    """
    from app.models import Role

    settings = get_settings()
    role_id = None
    role_row = await session.execute(select(Role).where(Role.slug == "superadmin"))
    role = role_row.scalar_one_or_none()
    if role:
        role_id = role.id

    result = await session.execute(select(User).where(User.username == settings.admin_user))
    user = result.scalar_one_or_none()
    if user is None:
        session.add(
            User(
                username=settings.admin_user,
                password_hash=hash_password(settings.admin_password),
                display_name=settings.admin_user,
                is_active=True,
                is_superadmin=True,
                role_id=role_id,
            )
        )
        await session.commit()
        return

    # Ensure bootstrap admin keeps Super Admin flags if role table exists
    changed = False
    if role_id and user.role_id is None:
        user.role_id = role_id
        changed = True
    if not user.is_superadmin and role_id and user.role_id == role_id:
        # only auto-promote the configured bootstrap username when it already has superadmin role
        pass
    if not user.is_superadmin and user.username == settings.admin_user and role_id:
        # First bootstrap account: keep elevated if somehow demoted without other superadmins
        others = await session.execute(
            select(User).where(User.is_superadmin.is_(True), User.id != user.id)
        )
        if others.scalars().first() is None:
            user.is_superadmin = True
            user.role_id = role_id
            changed = True
    if changed:
        await session.commit()


async def get_setting(session: AsyncSession, key: str, default: dict[str, Any]) -> dict[str, Any]:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return deep_merge(default, None) if default else {}
    # Flat keys (postgres_monitor) keep shallow merge; nested use deep_merge when
    # default values themselves contain dicts.
    if any(isinstance(v, dict) for v in default.values()):
        return deep_merge(default, row.value or {})
    return {**default, **(row.value or {})}


async def set_setting(session: AsyncSession, key: str, value: dict[str, Any]) -> dict[str, Any]:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    await session.refresh(row)
    return row.value


async def persist_system_snapshot(session: AsyncSession, metrics: dict[str, Any] | None = None) -> None:
    metrics = metrics or collect_system_metrics()
    summary = metrics.get("summary", {})
    session.add(
        MetricSnapshot(
            cpu_percent=summary.get("cpu_percent"),
            memory_percent=summary.get("memory_percent"),
            swap_percent=summary.get("swap_percent"),
            load_1=summary.get("load_1"),
            load_5=summary.get("load_5"),
            load_15=summary.get("load_15"),
            disk_percent=summary.get("disk_percent"),
            net_bytes_sent_rate=summary.get("net_bytes_sent_rate"),
            net_bytes_recv_rate=summary.get("net_bytes_recv_rate"),
            payload=metrics,
        )
    )
    await session.commit()


async def persist_pg_snapshots(session: AsyncSession) -> None:
    modules = await get_modules(session)
    if not modules.get("postgres", {}).get("enabled", True):
        return
    pg_settings = await get_setting(session, "postgres_monitor", DEFAULT_PG_SETTINGS)
    if not pg_settings.get("enabled") or not pg_settings.get("record_history"):
        return
    status = await pg_collector.check_postgres_available(pg_settings)
    if not status.get("available"):
        return
    databases = pg_settings.get("databases") or []
    if not databases:
        databases = [resolve_db_name(pg_settings)]
    for db_name in databases:
        try:
            data = await pg_collector.collect_pg_metric_for_db(db_name, pg_settings)
            if data.get("missing"):
                continue
            session.add(
                PgMetricSnapshot(
                    database_name=data["database_name"],
                    connections=data.get("connections"),
                    max_connections=data.get("max_connections"),
                    cache_hit_ratio=data.get("cache_hit_ratio"),
                    size_bytes=data.get("size_bytes"),
                    commits=data.get("commits"),
                    rollbacks=data.get("rollbacks"),
                    deadlocks=data.get("deadlocks"),
                    payload=data.get("payload") or {},
                )
            )
        except Exception:
            continue
    await session.commit()


def resolve_db_name(pg_settings: dict[str, Any]) -> str:
    name = (pg_settings.get("database") or "").strip()
    if name:
        return name
    return get_settings().db_name


async def persist_ssh_tunnel_history(session: AsyncSession) -> None:
    """Snapshot active session counts + open/close connection events."""
    modules = await get_modules(session)
    tun = modules.get("ssh_tunnel", {})
    if not tun.get("enabled", True) or not tun.get("record_history", True):
        return

    data = await asyncio.to_thread(ssh_tunnel_collector.collect_active_sessions, tun)
    if not data.get("available"):
        return

    now = datetime.now(timezone.utc)
    sessions = data.get("sessions") or []
    usernames = data.get("usernames") or []
    session.add(
        SshTunnelSnapshot(
            recorded_at=now,
            active_count=int(data.get("active_count") or 0),
            users_connected=len(usernames),
            payload={
                "sessions": sessions,
                "usernames": usernames,
                "public_port": data.get("public_port"),
                "listen_port": data.get("listen_port"),
                "bytes_sent_total": data.get("bytes_sent_total"),
                "bytes_recv_total": data.get("bytes_recv_total"),
                "bytes_sent_rate_total": data.get("bytes_sent_rate_total"),
                "bytes_recv_rate_total": data.get("bytes_recv_rate_total"),
            },
        )
    )

    live_keys = {str(s.get("session_key")) for s in sessions if s.get("session_key")}
    open_q = await session.execute(
        select(SshConnectionEvent).where(SshConnectionEvent.status == "active")
    )
    open_rows = list(open_q.scalars().all())
    open_by_key = {r.session_key: r for r in open_rows}

    for s in sessions:
        key = str(s.get("session_key") or "")
        if not key:
            continue
        if key in open_by_key:
            # refresh live fields
            row = open_by_key[key]
            row.pid = s.get("pid")
            row.forwards_count = s.get("forwards_count")
            row.payload = s
            try:
                row.duration_seconds = max(0, int((now - row.started_at).total_seconds()))
            except Exception:
                dur = s.get("duration_seconds")
                row.duration_seconds = int(dur) if isinstance(dur, (int, float)) else row.duration_seconds
            continue

        started = now
        ts = s.get("started_ts")
        if isinstance(ts, (int, float)) and ts > 0:
            started = datetime.fromtimestamp(ts, tz=timezone.utc)
        duration = s.get("duration_seconds")
        if not isinstance(duration, (int, float)):
            try:
                duration = max(0, int((now - started).total_seconds()))
            except Exception:
                duration = None
        session.add(
            SshConnectionEvent(
                session_key=key,
                username=str(s.get("username") or ""),
                remote_ip=s.get("remote_ip"),
                remote_port=s.get("remote_port"),
                pid=s.get("pid"),
                status="active",
                started_at=started,
                ended_at=None,
                duration_seconds=int(duration) if duration is not None else None,
                forwards_count=s.get("forwards_count"),
                payload=s,
            )
        )

    for key, row in open_by_key.items():
        if key in live_keys:
            continue
        row.status = "closed"
        row.ended_at = now
        try:
            row.duration_seconds = max(0, int((now - row.started_at).total_seconds()))
        except Exception:
            row.duration_seconds = None
        # Keep last known traffic counters in payload (already refreshed while active)

    await session.commit()


async def persist_wireguard_history(session: AsyncSession) -> None:
    """Snapshot online peer counts + open/close events from handshake freshness."""
    modules = await get_modules(session)
    wg_mod = modules.get("wireguard", {})
    if not wg_mod.get("enabled", True) or not wg_mod.get("record_history", False):
        return

    data = await wireguard_collector.collect_live_peers(wg_mod)
    if not data.get("available"):
        return

    now = datetime.now(timezone.utc)
    online_peers = data.get("online_peers") or [
        p for p in (data.get("peers") or []) if p.get("online")
    ]
    session.add(
        WireGuardSnapshot(
            recorded_at=now,
            online_count=int(data.get("online_count") or len(online_peers)),
            peer_count=int(data.get("peer_count") or 0),
            payload={
                "interface": data.get("interface"),
                "peers": [
                    {
                        "name": p.get("name"),
                        "public_key": p.get("public_key"),
                        "remote_ip": p.get("remote_ip"),
                        "vpn_address": p.get("address"),
                        "transfer_rx": p.get("transfer_rx"),
                        "transfer_tx": p.get("transfer_tx"),
                    }
                    for p in online_peers
                ],
            },
        )
    )

    live_keys = {str(p.get("public_key")) for p in online_peers if p.get("public_key")}
    open_q = await session.execute(
        select(WireGuardConnectionEvent).where(WireGuardConnectionEvent.status == "active")
    )
    open_rows = list(open_q.scalars().all())
    open_by_key = {r.session_key: r for r in open_rows}

    for p in online_peers:
        key = str(p.get("public_key") or "")
        if not key:
            continue
        if key in open_by_key:
            row = open_by_key[key]
            row.peer_id = p.get("peer_id") or row.peer_id
            row.peer_name = str(p.get("name") or row.peer_name)
            row.vpn_address = p.get("address") or row.vpn_address
            row.remote_ip = p.get("remote_ip")
            row.remote_port = p.get("remote_port")
            row.transfer_rx = p.get("transfer_rx")
            row.transfer_tx = p.get("transfer_tx")
            row.payload = p
            try:
                row.duration_seconds = max(0, int((now - row.started_at).total_seconds()))
            except Exception:
                pass
            continue

        handshake = p.get("latest_handshake")
        started = now
        if isinstance(handshake, (int, float)) and handshake > 0:
            try:
                started = datetime.fromtimestamp(int(handshake), tz=timezone.utc)
            except Exception:
                started = now
        try:
            duration = max(0, int((now - started).total_seconds()))
        except Exception:
            duration = None
        session.add(
            WireGuardConnectionEvent(
                session_key=key,
                peer_id=p.get("peer_id"),
                peer_name=str(p.get("name") or key[:12]),
                public_key=key,
                vpn_address=p.get("address"),
                remote_ip=p.get("remote_ip"),
                remote_port=p.get("remote_port"),
                status="active",
                started_at=started,
                ended_at=None,
                duration_seconds=duration,
                transfer_rx=p.get("transfer_rx"),
                transfer_tx=p.get("transfer_tx"),
                payload=p,
            )
        )

    for key, row in open_by_key.items():
        if key in live_keys:
            continue
        row.status = "closed"
        row.ended_at = now
        try:
            row.duration_seconds = max(0, int((now - row.started_at).total_seconds()))
        except Exception:
            row.duration_seconds = None

    await session.commit()


async def cleanup_old_metrics(session: AsyncSession) -> None:
    app_cfg = await get_app_config(session)
    days = int(app_cfg.get("retention_days") or get_settings().retention_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    await session.execute(delete(MetricSnapshot).where(MetricSnapshot.recorded_at < cutoff))
    await session.execute(delete(PgMetricSnapshot).where(PgMetricSnapshot.recorded_at < cutoff))
    await session.execute(delete(SshTunnelSnapshot).where(SshTunnelSnapshot.recorded_at < cutoff))
    await session.execute(delete(SshConnectionEvent).where(SshConnectionEvent.started_at < cutoff))
    await session.execute(delete(WireGuardSnapshot).where(WireGuardSnapshot.recorded_at < cutoff))
    await session.execute(
        delete(WireGuardConnectionEvent).where(WireGuardConnectionEvent.started_at < cutoff)
    )
    await session.commit()
