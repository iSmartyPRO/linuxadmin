from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    role_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Optional[Role]] = relationship(back_populates="users")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(Text)
    # Optional subset of permissions; empty/null = inherit user's role
    permissions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="api_keys")


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
