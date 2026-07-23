"""ssh tunnel history tables

Revision ID: 002_ssh_tunnel_history
Revises: 001_initial
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_ssh_tunnel_history"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ssh_tunnel_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("active_count", sa.Integer(), nullable=True),
        sa.Column("users_connected", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssh_tunnel_snapshots_recorded_at", "ssh_tunnel_snapshots", ["recorded_at"])

    op.create_table(
        "ssh_connection_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.String(length=256), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("remote_ip", sa.String(length=64), nullable=True),
        sa.Column("remote_port", sa.Integer(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("forwards_count", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssh_connection_events_session_key", "ssh_connection_events", ["session_key"])
    op.create_index("ix_ssh_connection_events_username", "ssh_connection_events", ["username"])
    op.create_index("ix_ssh_connection_events_remote_ip", "ssh_connection_events", ["remote_ip"])
    op.create_index("ix_ssh_connection_events_status", "ssh_connection_events", ["status"])
    op.create_index("ix_ssh_connection_events_started_at", "ssh_connection_events", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ssh_connection_events_started_at", table_name="ssh_connection_events")
    op.drop_index("ix_ssh_connection_events_status", table_name="ssh_connection_events")
    op.drop_index("ix_ssh_connection_events_remote_ip", table_name="ssh_connection_events")
    op.drop_index("ix_ssh_connection_events_username", table_name="ssh_connection_events")
    op.drop_index("ix_ssh_connection_events_session_key", table_name="ssh_connection_events")
    op.drop_table("ssh_connection_events")
    op.drop_index("ix_ssh_tunnel_snapshots_recorded_at", table_name="ssh_tunnel_snapshots")
    op.drop_table("ssh_tunnel_snapshots")
