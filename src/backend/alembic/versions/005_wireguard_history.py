"""wireguard connection history tables

Revision ID: 005_wireguard_history
Revises: 004_files_module
Create Date: 2026-09-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_wireguard_history"
down_revision: Union[str, None] = "004_files_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wireguard_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("online_count", sa.Integer(), nullable=True),
        sa.Column("peer_count", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wireguard_snapshots_recorded_at", "wireguard_snapshots", ["recorded_at"])

    op.create_table(
        "wireguard_connection_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.String(length=256), nullable=False),
        sa.Column("peer_id", sa.String(length=64), nullable=True),
        sa.Column("peer_name", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("vpn_address", sa.String(length=64), nullable=True),
        sa.Column("remote_ip", sa.String(length=64), nullable=True),
        sa.Column("remote_port", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("transfer_rx", sa.BigInteger(), nullable=True),
        sa.Column("transfer_tx", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wireguard_connection_events_session_key", "wireguard_connection_events", ["session_key"])
    op.create_index("ix_wireguard_connection_events_peer_name", "wireguard_connection_events", ["peer_name"])
    op.create_index("ix_wireguard_connection_events_public_key", "wireguard_connection_events", ["public_key"])
    op.create_index("ix_wireguard_connection_events_remote_ip", "wireguard_connection_events", ["remote_ip"])
    op.create_index("ix_wireguard_connection_events_status", "wireguard_connection_events", ["status"])
    op.create_index("ix_wireguard_connection_events_started_at", "wireguard_connection_events", ["started_at"])
    op.create_index("ix_wireguard_connection_events_peer_id", "wireguard_connection_events", ["peer_id"])


def downgrade() -> None:
    op.drop_table("wireguard_connection_events")
    op.drop_table("wireguard_snapshots")
