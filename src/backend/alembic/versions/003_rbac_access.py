"""RBAC roles, API keys, extend panel users

Revision ID: 003_rbac_access
Revises: 002_ssh_tunnel_history
Create Date: 2026-07-23
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_rbac_access"
down_revision: Union[str, None] = "002_ssh_tunnel_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODULES = [
    "overview",
    "history",
    "fail2ban",
    "firewall",
    "docker",
    "network",
    "disks",
    "users",
    "services",
    "postgres",
    "ssh_tunnel",
    "wireguard",
    "openvpn",
    "settings",
    "settings_modules",
    "settings_connection",
    "settings_access",
]


def _all(level: str) -> dict[str, str]:
    return {k: level for k in _MODULES}


def _operator() -> dict[str, str]:
    p = _all("none")
    for k in (
        "overview",
        "history",
        "fail2ban",
        "firewall",
        "docker",
        "network",
        "disks",
        "users",
        "services",
        "postgres",
        "ssh_tunnel",
        "wireguard",
        "openvpn",
    ):
        p[k] = "full"
    p["settings"] = "read"
    p["settings_modules"] = "read"
    return p


def _viewer() -> dict[str, str]:
    p = _all("none")
    for k in _MODULES:
        if not k.startswith("settings"):
            p[k] = "read"
    p["settings"] = "read"
    return p


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_roles_slug", "roles", ["slug"])

    op.add_column("users", sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("users", sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_foreign_key("fk_users_role_id", "users", "roles", ["role_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    conn = op.get_bind()
    roles = [
        ("Super Admin", "superadmin", "Full access to all modules and administration", True, _all("full")),
        ("Operator", "operator", "Operate host modules; limited settings", True, _operator()),
        ("Viewer", "viewer", "Read-only access to monitoring modules", True, _viewer()),
    ]
    for name, slug, desc, is_system, perms in roles:
        conn.execute(
            sa.text(
                "INSERT INTO roles (name, slug, description, is_system, permissions) "
                "VALUES (:name, :slug, :desc, :is_system, CAST(:perms AS jsonb)) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "name": name,
                "slug": slug,
                "desc": desc,
                "is_system": is_system,
                "perms": json.dumps(perms),
            },
        )

    row = conn.execute(sa.text("SELECT id FROM roles WHERE slug = 'superadmin'")).fetchone()
    if row:
        conn.execute(
            sa.text(
                "UPDATE users SET is_superadmin = true, role_id = :rid, "
                "display_name = CASE WHEN display_name = '' THEN username ELSE display_name END"
            ),
            {"rid": row[0]},
        )


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "role_id")
    op.drop_column("users", "is_superadmin")
    op.drop_column("users", "display_name")
    op.drop_index("ix_roles_slug", table_name="roles")
    op.drop_table("roles")
