"""RBAC: module permission levels none | read | full."""

from __future__ import annotations

from typing import Any, Literal

PermLevel = Literal["none", "read", "full"]
LEVEL_RANK = {"none": 0, "read": 1, "full": 2}

# Modules that can be granted on roles (panel areas)
ACCESS_MODULES: list[dict[str, str]] = [
    {"key": "overview", "label": "Overview", "group": "Monitoring"},
    {"key": "history", "label": "History", "group": "Monitoring"},
    {"key": "fail2ban", "label": "Fail2ban", "group": "Security"},
    {"key": "firewall", "label": "Firewall", "group": "Security"},
    {"key": "docker", "label": "Docker", "group": "Runtime"},
    {"key": "network", "label": "Network", "group": "Runtime"},
    {"key": "disks", "label": "Disks", "group": "Runtime"},
    {"key": "users", "label": "OS Users", "group": "Runtime"},
    {"key": "services", "label": "Services", "group": "Runtime"},
    {"key": "postgres", "label": "PostgreSQL", "group": "Data"},
    {"key": "ssh_tunnel", "label": "SSH Tunnel", "group": "VPN / Access"},
    {"key": "wireguard", "label": "WireGuard", "group": "VPN / Access"},
    {"key": "openvpn", "label": "OpenVPN", "group": "VPN / Access"},
    {"key": "settings", "label": "Settings (view)", "group": "Administration"},
    {"key": "settings_modules", "label": "Settings → Modules", "group": "Administration"},
    {"key": "settings_connection", "label": "Settings → Connection", "group": "Administration"},
    {"key": "settings_access", "label": "Settings → Users / Roles / API", "group": "Administration"},
]

MODULE_KEYS = [m["key"] for m in ACCESS_MODULES]


def normalize_level(value: Any) -> PermLevel:
    v = str(value or "none").strip().lower()
    if v in {"full", "write", "rw", "admin"}:
        return "full"
    if v in {"read", "ro", "viewer", "view"}:
        return "read"
    return "none"


def level_at_least(have: PermLevel | str, need: PermLevel | str) -> bool:
    return LEVEL_RANK.get(normalize_level(have), 0) >= LEVEL_RANK.get(normalize_level(need), 0)


def all_full_permissions() -> dict[str, PermLevel]:
    return {k: "full" for k in MODULE_KEYS}


def all_none_permissions() -> dict[str, PermLevel]:
    return {k: "none" for k in MODULE_KEYS}


def merge_permissions(base: dict[str, Any] | None) -> dict[str, PermLevel]:
    out = all_none_permissions()
    if not base:
        return out
    for key, value in base.items():
        if key in out:
            out[key] = normalize_level(value)
    return out


def default_operator_permissions() -> dict[str, PermLevel]:
    p = all_none_permissions()
    for key in (
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
        p[key] = "full"
    p["settings"] = "read"
    p["settings_modules"] = "read"
    return p


def default_viewer_permissions() -> dict[str, PermLevel]:
    p = all_none_permissions()
    for key in MODULE_KEYS:
        if key.startswith("settings"):
            continue
        p[key] = "read"
    p["settings"] = "read"
    return p
