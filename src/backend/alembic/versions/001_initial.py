"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("memory_percent", sa.Float(), nullable=True),
        sa.Column("swap_percent", sa.Float(), nullable=True),
        sa.Column("load_1", sa.Float(), nullable=True),
        sa.Column("load_5", sa.Float(), nullable=True),
        sa.Column("load_15", sa.Float(), nullable=True),
        sa.Column("disk_percent", sa.Float(), nullable=True),
        sa.Column("net_bytes_sent_rate", sa.Float(), nullable=True),
        sa.Column("net_bytes_recv_rate", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_snapshots_recorded_at", "metric_snapshots", ["recorded_at"])

    op.create_table(
        "pg_metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("database_name", sa.String(length=128), nullable=False),
        sa.Column("connections", sa.Integer(), nullable=True),
        sa.Column("max_connections", sa.Integer(), nullable=True),
        sa.Column("cache_hit_ratio", sa.Float(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("commits", sa.Integer(), nullable=True),
        sa.Column("rollbacks", sa.Integer(), nullable=True),
        sa.Column("deadlocks", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pg_metric_snapshots_recorded_at", "pg_metric_snapshots", ["recorded_at"])
    op.create_index("ix_pg_metric_snapshots_database_name", "pg_metric_snapshots", ["database_name"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    op.drop_table("app_settings")
    op.drop_index("ix_pg_metric_snapshots_database_name", table_name="pg_metric_snapshots")
    op.drop_index("ix_pg_metric_snapshots_recorded_at", table_name="pg_metric_snapshots")
    op.drop_table("pg_metric_snapshots")
    op.drop_index("ix_metric_snapshots_recorded_at", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
