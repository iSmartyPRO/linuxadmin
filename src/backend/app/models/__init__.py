from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    cpu_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    memory_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    swap_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    load_1: Mapped[Optional[float]] = mapped_column(nullable=True)
    load_5: Mapped[Optional[float]] = mapped_column(nullable=True)
    load_15: Mapped[Optional[float]] = mapped_column(nullable=True)
    disk_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    net_bytes_sent_rate: Mapped[Optional[float]] = mapped_column(nullable=True)
    net_bytes_recv_rate: Mapped[Optional[float]] = mapped_column(nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class PgMetricSnapshot(Base):
    __tablename__ = "pg_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    database_name: Mapped[str] = mapped_column(String(128), index=True)
    connections: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_connections: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_hit_ratio: Mapped[Optional[float]] = mapped_column(nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    commits: Mapped[Optional[int]] = mapped_column(nullable=True)
    rollbacks: Mapped[Optional[int]] = mapped_column(nullable=True)
    deadlocks: Mapped[Optional[int]] = mapped_column(nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SshTunnelSnapshot(Base):
    """Periodic count of active SSH tunnel sessions (for History charts)."""

    __tablename__ = "ssh_tunnel_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    active_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    users_connected: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SshConnectionEvent(Base):
    """Connect/disconnect log for tunnel sessions (for analysis in History)."""

    __tablename__ = "ssh_connection_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(256), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    remote_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    remote_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|closed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    forwards_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
