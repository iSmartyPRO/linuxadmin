"""Nginx Edge Proxy management: routes, TLS, stream/SNI, certs, ACME, safe apply."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.collectors._exec import run_cmd, run_privileged

DEFAULT_DATA_DIR = "/var/lib/lnxadmin/nginx"
DEFAULT_NGINX_CONF = "/etc/nginx/nginx.conf"
DEFAULT_HTTP_INCLUDE = "/etc/nginx/conf.d/00-lnxadmin.conf"
DEFAULT_MANAGED_DIR = "/etc/nginx/lnxadmin"
MANAGED_MARKER = "# managed-by: lnxadmin-nginx"
STREAM_BEGIN = "# BEGIN lnxadmin-stream"
STREAM_END = "# END lnxadmin-stream"

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
SAFE_VALUE_RE = re.compile(r"^[\x20-\x7E]{0,512}$")
# Block nginx directive injection in free-text fields
FORBIDDEN_CHARS_RE = re.compile(r"[;{}\n\r]")

PROXY_TYPES = {
    "http_reverse": {"label": "HTTP Reverse Proxy", "layer": "http"},
    "https_reverse": {"label": "HTTPS Reverse Proxy (TLS termination)", "layer": "http"},
    "tls_passthrough": {"label": "TLS Passthrough (SNI / stream)", "layer": "stream"},
    "tcp": {"label": "TCP Proxy", "layer": "stream"},
    "udp": {"label": "UDP Proxy", "layer": "stream"},
    "static_http": {"label": "Static directory (HTTP)", "layer": "http"},
    "static_https": {"label": "Static directory (HTTPS)", "layer": "http"},
}

LB_METHODS = ("round_robin", "least_conn", "ip_hash")
ACME_ENVIRONMENTS = ("production", "staging", "custom")

# Pre-filled route templates for common publish scenarios.
# Fields under "defaults" are applied first; user overrides merge on top.
# "hints" = UI tips; "required_overrides" = fields user should usually change.
ROUTE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "static_directory",
        "title": "Static directory",
        "category": "Web",
        "icon": "folder",
        "summary": "Serve a folder from disk over HTTP or HTTPS. No backend host.",
        "hints": [
            "static_root must be an absolute path on this host, for example /projects/site.",
            "Use Static directory (HTTP) on port 80 and Static directory (HTTPS) on 443 for the same folder.",
            "HTTPS needs a certificate that covers the domain.",
        ],
        "required_overrides": ["domain", "name", "static_root"],
        "defaults": {
            "name": "static-site",
            "domain": "files.example.com",
            "aliases": [],
            "proxy_type": "static_https",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "static_root": "/var/www/site",
            "index": "index.html index.htm",
            "client_max_body_size": "100m",
            "http2": True,
            "logging": True,
            "enabled": True,
            "cert_id": None,
        },
    },
    {
        "id": "nextcloud_docker",
        "title": "Nextcloud (Docker)",
        "category": "Collaboration",
        "icon": "cloud",
        "summary": "HTTPS reverse proxy to a local Nextcloud container — large uploads, WebDAV, CalDAV.",
        "hints": [
            "Set OVERWRITEPROTOCOL=https and trusted proxies in Nextcloud.",
            "Default backend: 127.0.0.1:8080 (or docker:nextcloud).",
            "Assign a TLS certificate before Apply for HTTPS.",
        ],
        "required_overrides": ["domain", "name"],
        "defaults": {
            "name": "nextcloud",
            "domain": "cloud.example.com",
            "aliases": [],
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 8080,
            "backend_proto": "http",
            "lb_method": "round_robin",
            "client_max_body_size": "10G",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "websocket": True,
            "http2": True,
            "logging": True,
            "enabled": True,
            "verify_backend_tls": False,
            "headers": [
                {"name": "X-Forwarded-Host", "value": "$host"},
                {"name": "X-Forwarded-Port", "value": "$server_port"},
            ],
        },
    },
    {
        "id": "onlyoffice_docker",
        "title": "OnlyOffice Document Server",
        "category": "Collaboration",
        "icon": "file",
        "summary": "Proxy OnlyOffice DS (often paired with Nextcloud) with WebSocket and long sessions.",
        "hints": [
            "Backend default 127.0.0.1:8081 matches common docker publish.",
            "Keep WebSocket enabled for collaborative editing.",
        ],
        "required_overrides": ["domain", "name"],
        "defaults": {
            "name": "onlyoffice",
            "domain": "office.example.com",
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 8081,
            "backend_proto": "http",
            "client_max_body_size": "200m",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "websocket": True,
            "http2": True,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "carbonio_web",
        "title": "Carbonio Web",
        "category": "Collaboration",
        "icon": "mail",
        "summary": "HTTPS reverse proxy to Zextras Carbonio webmail / Files / Chats (public UI on :443).",
        "hints": [
            "Backend must be the Carbonio host (e.g. 192.168.22.5), NOT this Nginx Edge IP — that causes a loop.",
            "Carbonio sends large cookies — template enables large_headers buffers.",
            "WebSocket must stay enabled for Carbonio Chats.",
            "Set Public Server Host Name / Service Port (443) in Carbonio Admin after publish.",
            "If you see 400 Request Header Or Cookie Too Large — clear site cookies or keep large_headers on.",
        ],
        "required_overrides": ["domain", "backend_host"],
        "defaults": {
            "name": "carbonio-web",
            "domain": "mail.example.com",
            "aliases": [],
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "192.168.22.5",
            "backend_port": 443,
            "backend_proto": "https",
            "verify_backend_tls": False,
            "lb_method": "round_robin",
            "client_max_body_size": "200m",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "websocket": True,
            "http2": True,
            "large_headers": True,
            "logging": True,
            "enabled": True,
            "headers": [
                {"name": "X-Forwarded-Host", "value": "$host"},
                {"name": "X-Forwarded-Port", "value": "$server_port"},
            ],
        },
    },
    {
        "id": "carbonio_admin",
        "title": "Carbonio Admin",
        "category": "Collaboration",
        "icon": "setting",
        "summary": "HTTPS reverse proxy to Carbonio Admin Panel (native port 6071).",
        "hints": [
            "Backend = Carbonio node :6071 (e.g. 192.168.22.5), not the Edge proxy itself.",
            "Official Admin URL is https://<proxy-node>:6071/ — keep WebSocket if UI needs it.",
            "Do not expose Admin to the whole internet: set allow_ips or put it behind VPN.",
            "Use a separate admin subdomain (e.g. admin.mail.example.com) and its own certificate.",
        ],
        "required_overrides": ["domain", "backend_host", "allow_ips"],
        "defaults": {
            "name": "carbonio-admin",
            "domain": "admin.mail.example.com",
            "aliases": [],
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "192.168.22.5",
            "backend_port": 6071,
            "backend_proto": "https",
            "verify_backend_tls": False,
            "lb_method": "round_robin",
            "client_max_body_size": "50m",
            "connect_timeout": 60,
            "send_timeout": 1800,
            "read_timeout": 1800,
            "websocket": True,
            "http2": True,
            "large_headers": True,
            "logging": True,
            "enabled": True,
            "allow_ips": ["10.0.0.0/8", "192.168.0.0/16"],
            "headers": [
                {"name": "X-Forwarded-Host", "value": "$host"},
                {"name": "X-Forwarded-Port", "value": "$server_port"},
            ],
        },
    },
    {
        "id": "webapp_https",
        "title": "Web application (HTTPS)",
        "category": "Web",
        "icon": "global",
        "summary": "Generic HTTPS reverse proxy for a web UI / API with sensible timeouts.",
        "hints": ["Change domain, backend host/port, and attach a certificate."],
        "required_overrides": ["domain", "name", "backend_host", "backend_port"],
        "defaults": {
            "name": "webapp",
            "domain": "app.example.com",
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 3000,
            "backend_proto": "http",
            "client_max_body_size": "50m",
            "connect_timeout": 60,
            "send_timeout": 300,
            "read_timeout": 300,
            "websocket": True,
            "http2": True,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "webapp_http",
        "title": "Web application (HTTP)",
        "category": "Web",
        "icon": "global",
        "summary": "Plain HTTP reverse proxy — useful behind another TLS terminator or for LAN.",
        "hints": ["Prefer HTTPS template for internet-facing services."],
        "required_overrides": ["domain", "name", "backend_host"],
        "defaults": {
            "name": "webapp-http",
            "domain": "app.example.com",
            "proxy_type": "http_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 80,
            "backend_host": "127.0.0.1",
            "backend_port": 3000,
            "backend_proto": "http",
            "client_max_body_size": "50m",
            "websocket": True,
            "http2": False,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "websocket_app",
        "title": "WebSocket / realtime app",
        "category": "Web",
        "icon": "api",
        "summary": "Long-lived WebSocket / SSE backends (chat, dashboards, Vite HMR-style apps).",
        "hints": ["Read/send timeouts set to 1 hour for idle connections."],
        "required_overrides": ["domain", "backend_host", "backend_port"],
        "defaults": {
            "name": "ws-app",
            "domain": "ws.example.com",
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 8080,
            "backend_proto": "http",
            "client_max_body_size": "10m",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "websocket": True,
            "http2": True,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "ms_rd_gateway",
        "title": "Microsoft RD Gateway / RD Web",
        "category": "Remote Desktop",
        "icon": "desktop",
        "summary": "HTTPS reverse proxy for RD Gateway / RD Web Access (RPC over HTTP + WebSocket).",
        "hints": [
            "Point backend to the RD Gateway IIS host (often :443 with HTTPS backend).",
            "Very long timeouts required for remote desktop sessions.",
            "Alternatively use the RDP TCP or TLS Passthrough templates.",
        ],
        "required_overrides": ["domain", "backend_host"],
        "defaults": {
            "name": "rd-gateway",
            "domain": "rds.example.com",
            "proxy_type": "https_reverse",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "192.168.1.50",
            "backend_port": 443,
            "backend_proto": "https",
            "verify_backend_tls": False,
            "client_max_body_size": "100m",
            "connect_timeout": 60,
            "send_timeout": 7200,
            "read_timeout": 7200,
            "websocket": True,
            "http2": False,
            "logging": True,
            "enabled": True,
            "headers": [
                {"name": "X-Forwarded-For", "value": "$proxy_add_x_forwarded_for"},
            ],
        },
    },
    {
        "id": "ms_rdp_tcp",
        "title": "Microsoft RDP (TCP 3389)",
        "category": "Remote Desktop",
        "icon": "desktop",
        "summary": "Raw TCP proxy for classic RDP to a Windows host.",
        "hints": [
            "Exposes TCP 3389 publicly — restrict with allow_ips / firewall.",
            "For TLS-wrapped RDP prefer TLS Passthrough.",
        ],
        "required_overrides": ["name", "backend_host"],
        "defaults": {
            "name": "rdp",
            "domain": "",
            "proxy_type": "tcp",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 3389,
            "backend_host": "192.168.1.50",
            "backend_port": 3389,
            "backend_proto": "tcp",
            "session_timeout": 7200,
            "tcp_keepalive": 60,
            "logging": True,
            "enabled": True,
            "allow_ips": [],
        },
    },
    {
        "id": "ms_rds_passthrough",
        "title": "Microsoft RDS (TLS Passthrough)",
        "category": "Remote Desktop",
        "icon": "desktop",
        "summary": "SNI-based TLS passthrough — certificate stays on the RDS / IIS backend.",
        "hints": [
            "Backend must present a cert matching the public domain (SNI).",
            "Nginx does not terminate TLS; renew certs on Windows.",
        ],
        "required_overrides": ["domain", "backend_host"],
        "defaults": {
            "name": "rds-passthrough",
            "domain": "rds.example.com",
            "proxy_type": "tls_passthrough",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 443,
            "backend_host": "192.168.1.50",
            "backend_port": 443,
            "backend_proto": "tcp",
            "session_timeout": 7200,
            "tcp_keepalive": 60,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "portainer",
        "title": "Portainer",
        "category": "DevOps",
        "icon": "docker",
        "summary": "HTTPS proxy to Portainer UI (Docker management).",
        "hints": ["Default backend 127.0.0.1:9000 or 9443 if Portainer serves TLS locally."],
        "required_overrides": ["domain"],
        "defaults": {
            "name": "portainer",
            "domain": "portainer.example.com",
            "proxy_type": "https_reverse",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 9000,
            "backend_proto": "http",
            "websocket": True,
            "http2": True,
            "client_max_body_size": "100m",
            "read_timeout": 600,
            "send_timeout": 600,
            "enabled": True,
            "logging": True,
        },
    },
    {
        "id": "grafana",
        "title": "Grafana",
        "category": "DevOps",
        "icon": "chart",
        "summary": "HTTPS reverse proxy for Grafana dashboards and Live WebSocket.",
        "hints": ["Set GF_SERVER_ROOT_URL to the public HTTPS URL."],
        "required_overrides": ["domain"],
        "defaults": {
            "name": "grafana",
            "domain": "grafana.example.com",
            "proxy_type": "https_reverse",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 3000,
            "backend_proto": "http",
            "websocket": True,
            "http2": True,
            "client_max_body_size": "20m",
            "read_timeout": 600,
            "enabled": True,
            "logging": True,
        },
    },
    {
        "id": "proxmox",
        "title": "Proxmox VE",
        "category": "Infrastructure",
        "icon": "server",
        "summary": "HTTPS proxy or sticky sessions to Proxmox web UI (SPICE/noVNC websockets).",
        "hints": ["Backend usually https://pve:8006 — disable verify if using self-signed."],
        "required_overrides": ["domain", "backend_host"],
        "defaults": {
            "name": "proxmox",
            "domain": "pve.example.com",
            "proxy_type": "https_reverse",
            "frontend_port": 443,
            "backend_host": "192.168.1.10",
            "backend_port": 8006,
            "backend_proto": "https",
            "verify_backend_tls": False,
            "websocket": True,
            "http2": True,
            "client_max_body_size": "100m",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "lb_method": "ip_hash",
            "enabled": True,
            "logging": True,
        },
    },
    {
        "id": "homeassistant",
        "title": "Home Assistant",
        "category": "IoT",
        "icon": "home",
        "summary": "HTTPS proxy for Home Assistant with WebSocket for the UI.",
        "hints": ["Add the public URL to http.use_x_forwarded_for / trusted_proxies."],
        "required_overrides": ["domain"],
        "defaults": {
            "name": "homeassistant",
            "domain": "ha.example.com",
            "proxy_type": "https_reverse",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 8123,
            "backend_proto": "http",
            "websocket": True,
            "http2": True,
            "client_max_body_size": "20m",
            "read_timeout": 3600,
            "send_timeout": 3600,
            "enabled": True,
            "logging": True,
        },
    },
    {
        "id": "postgres_tcp",
        "title": "PostgreSQL (TCP)",
        "category": "Databases",
        "icon": "database",
        "summary": "TCP stream proxy to PostgreSQL — prefer VPN; lock down with allow_ips.",
        "hints": ["Do not expose Postgres to the internet without IP allow-lists."],
        "required_overrides": ["backend_host", "allow_ips"],
        "defaults": {
            "name": "postgres",
            "domain": "",
            "proxy_type": "tcp",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 5432,
            "backend_host": "127.0.0.1",
            "backend_port": 5432,
            "backend_proto": "tcp",
            "session_timeout": 3600,
            "tcp_keepalive": 60,
            "logging": True,
            "enabled": True,
            "allow_ips": ["10.0.0.0/8", "192.168.0.0/16"],
        },
    },
    {
        "id": "wireguard_udp",
        "title": "WireGuard (UDP)",
        "category": "VPN",
        "icon": "safety",
        "summary": "UDP stream proxy for WireGuard listen port.",
        "hints": ["Frontend and backend ports usually both 51820."],
        "required_overrides": ["backend_host"],
        "defaults": {
            "name": "wireguard-udp",
            "domain": "",
            "proxy_type": "udp",
            "frontend_ip": "0.0.0.0",
            "frontend_port": 51820,
            "backend_host": "127.0.0.1",
            "backend_port": 51820,
            "backend_proto": "udp",
            "session_timeout": 300,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "tls_passthrough_generic",
        "title": "TLS Passthrough (generic)",
        "category": "TLS",
        "icon": "lock",
        "summary": "SNI routing without decryption — cert lives on the backend.",
        "hints": ["Certificate must be installed/renewed on the backend host."],
        "required_overrides": ["domain", "backend_host"],
        "defaults": {
            "name": "tls-pass",
            "domain": "secure.example.com",
            "proxy_type": "tls_passthrough",
            "frontend_port": 443,
            "backend_host": "192.168.1.20",
            "backend_port": 443,
            "backend_proto": "tcp",
            "session_timeout": 3600,
            "tcp_keepalive": 60,
            "logging": True,
            "enabled": True,
        },
    },
    {
        "id": "minio_s3",
        "title": "MinIO / S3 API",
        "category": "Storage",
        "icon": "hdd",
        "summary": "HTTPS proxy for MinIO API/console with large uploads.",
        "hints": ["Use path-style or configure MINIO_SERVER_URL to the public domain."],
        "required_overrides": ["domain", "backend_port"],
        "defaults": {
            "name": "minio",
            "domain": "s3.example.com",
            "proxy_type": "https_reverse",
            "frontend_port": 443,
            "backend_host": "127.0.0.1",
            "backend_port": 9000,
            "backend_proto": "http",
            "client_max_body_size": "0",
            "connect_timeout": 60,
            "send_timeout": 3600,
            "read_timeout": 3600,
            "websocket": True,
            "http2": True,
            "enabled": True,
            "logging": True,
        },
    },
]


def _opts(options: dict[str, Any] | None) -> dict[str, Any]:
    o = options or {}
    return {
        "data_dir": o.get("data_dir") or DEFAULT_DATA_DIR,
        "nginx_conf": o.get("nginx_conf") or DEFAULT_NGINX_CONF,
        "http_include": o.get("http_include") or DEFAULT_HTTP_INCLUDE,
        "managed_dir": o.get("managed_dir") or DEFAULT_MANAGED_DIR,
        "allow_install": bool(o.get("allow_install", True)),
        "acme_email": (o.get("acme_email") or "").strip(),
        "acme_environment": o.get("acme_environment") or "production",
        "acme_directory_url": (o.get("acme_directory_url") or "").strip(),
        "renew_days_before": int(o.get("renew_days_before") or 30),
        "log_lines": int(o.get("log_lines") or 120),
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _data(opts: dict[str, Any]) -> Path:
    return Path(opts["data_dir"])


def _state_path(opts: dict[str, Any]) -> Path:
    return _data(opts) / "state.json"


def _certs_meta_dir(opts: dict[str, Any]) -> Path:
    return _data(opts) / "certs"


def _certs_files_dir(opts: dict[str, Any]) -> Path:
    return _data(opts) / "certs" / "files"


def _backups_dir(opts: dict[str, Any]) -> Path:
    return _data(opts) / "backups"


def _acme_log_path(opts: dict[str, Any]) -> Path:
    return _data(opts) / "acme" / "operations.jsonl"


def _audit_log_path(opts: dict[str, Any]) -> Path:
    return _data(opts) / "audit.jsonl"


def _managed(opts: dict[str, Any]) -> Path:
    return Path(opts["managed_dir"])


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "routes": [],
        "dns_providers": [],
        "acme": {
            "environment": "production",
            "email": "",
            "directory_url": "",
            "auto_renew": True,
            "renew_days_before": 30,
        },
        "last_apply": None,
        "last_reload": None,
        "updated_at": None,
    }


def _load_state(opts: dict[str, Any]) -> dict[str, Any]:
    raw = _load_json(_state_path(opts))
    if not raw:
        return _default_state()
    base = _default_state()
    base.update({k: v for k, v in raw.items() if k in base or k in {"routes", "dns_providers", "acme", "last_apply", "last_reload", "updated_at", "version"}})
    base["routes"] = list(raw.get("routes") or [])
    base["dns_providers"] = list(raw.get("dns_providers") or [])
    if isinstance(raw.get("acme"), dict):
        base["acme"] = {**base["acme"], **raw["acme"]}
    return base


async def _write_file_priv(path: str, content: str, mode: str = "644") -> tuple[bool, str]:
    # Write via temp + install to avoid partial configs
    tmp = f"/tmp/lnxadmin-nginx-{secrets.token_hex(8)}"
    try:
        Path(tmp).write_text(content, encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    code, _, err = await run_privileged(["install", "-m", mode, tmp, path], timeout=15.0)
    Path(tmp).unlink(missing_ok=True)
    if code != 0:
        # fallback: try direct write when already root-owned writable
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            await run_privileged(["chmod", mode, path])
            return True, ""
        except OSError as exc2:
            return False, err or str(exc2)
    return True, ""


async def _ensure_dirs(opts: dict[str, Any]) -> tuple[bool, str]:
    paths = [
        str(_data(opts)),
        str(_certs_meta_dir(opts)),
        str(_certs_files_dir(opts)),
        str(_backups_dir(opts)),
        str(_data(opts) / "acme"),
        str(_managed(opts) / "http.d"),
        str(_managed(opts) / "stream.d"),
        str(_managed(opts) / "ssl"),
        str(_managed(opts) / "acme-webroot"),
    ]
    for p in paths:
        code, _, err = await run_privileged(["mkdir", "-p", p], timeout=10.0)
        if code != 0:
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return False, err or str(exc)
    # Restrict private material
    await run_privileged(["chmod", "700", str(_certs_files_dir(opts))])
    return True, ""


async def _save_state(opts: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    state["updated_at"] = _now()
    ok, err = await _ensure_dirs(opts)
    if not ok:
        return False, err
    return await _write_file_priv(str(_state_path(opts)), json.dumps(state, indent=2, ensure_ascii=False), "600")


async def _audit(opts: dict[str, Any], action: str, detail: dict[str, Any] | None = None) -> None:
    line = json.dumps({"ts": _now(), "action": action, "detail": detail or {}}, ensure_ascii=False)
    path = _audit_log_path(opts)
    try:
        await _ensure_dirs(opts)
        # append via shell to keep simple under privilege
        code, _, _ = await run_privileged(["bash", "-c", f"printf '%s\\n' {json.dumps(line)} >> {path}"], timeout=5.0)
        if code != 0:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass


def _detect_pkg_manager() -> str | None:
    for pm in ("apt-get", "dnf", "yum", "apk", "pacman", "zypper"):
        if shutil.which(pm):
            return pm
    return None


def tools_status() -> dict[str, Any]:
    nginx = shutil.which("nginx")
    openssl = shutil.which("openssl")
    certbot = shutil.which("certbot")
    stream_mod = False
    if nginx:
        # dynamic module or built-in
        for candidate in (
            "/usr/lib/nginx/modules/ngx_stream_module.so",
            "/usr/lib64/nginx/modules/ngx_stream_module.so",
        ):
            if Path(candidate).is_file():
                stream_mod = True
                break
        # check binary help / version for stream
        if not stream_mod:
            stream_mod = True  # assume available; apply will validate
    return {
        "nginx": bool(nginx),
        "openssl": bool(openssl),
        "certbot": bool(certbot),
        "stream_module": stream_mod,
        "pkg_manager": _detect_pkg_manager(),
        "nginx_bin": nginx or "",
    }


async def _nginx_version() -> str:
    code, out, err = await run_cmd(["nginx", "-v"], timeout=5.0)
    text = (err or out or "").strip()
    return text or "unknown"


async def _service_status() -> dict[str, Any]:
    code, out, _ = await run_cmd(["systemctl", "is-active", "nginx"], timeout=5.0)
    active = (out or "").strip() == "active"
    code2, out2, _ = await run_cmd(["systemctl", "show", "nginx", "-p", "ActiveEnterTimestamp", "--value"], timeout=5.0)
    return {
        "active": active,
        "state": (out or "unknown").strip(),
        "since": (out2 or "").strip() if code2 == 0 else "",
    }


async def _stub_status() -> dict[str, Any]:
    """Parse nginx stub_status if enabled on localhost."""
    code, out, _ = await run_cmd(
        ["curl", "-fsS", "--max-time", "2", "http://127.0.0.1/lnxadmin-nginx-status"],
        timeout=4.0,
    )
    if code != 0 or not out:
        return {"available": False}
    # Active connections: 1 \n server accepts handled requests \n 1 1 1 \n Reading: 0 Writing: 1 Waiting: 0
    active = accepts = handled = requests = reading = writing = waiting = 0
    m = re.search(r"Active connections:\s*(\d+)", out)
    if m:
        active = int(m.group(1))
    m = re.search(r"(\d+)\s+(\d+)\s+(\d+)", out)
    if m:
        accepts, handled, requests = int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"Reading:\s*(\d+)\s+Writing:\s*(\d+)\s+Waiting:\s*(\d+)", out)
    if m:
        reading, writing, waiting = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return {
        "available": True,
        "active_connections": active,
        "accepts": accepts,
        "handled": handled,
        "requests": requests,
        "reading": reading,
        "writing": writing,
        "waiting": waiting,
    }


def _valid_domain(name: str) -> bool:
    n = (name or "").strip().lower().rstrip(".")
    if not n or len(n) > 253:
        return False
    if n.startswith("*."):
        return DOMAIN_RE.match(n[2:]) is not None
    return DOMAIN_RE.match(n) is not None


def _valid_host(host: str) -> bool:
    h = (host or "").strip()
    if not h or len(h) > 253 or FORBIDDEN_CHARS_RE.search(h):
        return False
    if h.startswith("docker:"):
        return NAME_RE.match(h[7:]) is not None
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    return _valid_domain(h) or bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", h))


def _valid_cidr_or_ip(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _sanitize_header_value(value: str) -> str | None:
    v = (value or "").strip()
    if not SAFE_VALUE_RE.match(v) or FORBIDDEN_CHARS_RE.search(v):
        return None
    return v


def _new_id(prefix: str = "r") -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _normalize_route(body: dict[str, Any], existing: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
    base = dict(existing or {})
    proxy_type = str(body.get("proxy_type") or base.get("proxy_type") or "http_reverse")
    if proxy_type not in PROXY_TYPES:
        return None, f"Unsupported proxy_type: {proxy_type}"

    name = str(body.get("name") or base.get("name") or "").strip()
    if not name or not NAME_RE.match(name):
        return None, "Invalid route name (alnum, ._- , max 64)"

    domain = str(body.get("domain") or base.get("domain") or "").strip().lower()
    aliases = body.get("aliases") if "aliases" in body else base.get("aliases") or []
    if not isinstance(aliases, list):
        return None, "aliases must be a list"
    aliases = [str(a).strip().lower() for a in aliases if str(a).strip()]
    layer = PROXY_TYPES[proxy_type]["layer"]

    if layer == "http" or proxy_type == "tls_passthrough":
        if not _valid_domain(domain):
            return None, "Invalid domain"
        for a in aliases:
            if not _valid_domain(a):
                return None, f"Invalid alias domain: {a}"

    frontend_ip = str(body.get("frontend_ip") if "frontend_ip" in body else base.get("frontend_ip") or "0.0.0.0").strip()
    if frontend_ip not in ("0.0.0.0", "::", "*"):
        try:
            ipaddress.ip_address(frontend_ip)
        except ValueError:
            return None, "Invalid frontend_ip"

    try:
        frontend_port = int(body.get("frontend_port") if "frontend_port" in body else base.get("frontend_port") or (443 if proxy_type != "http_reverse" else 80))
    except (TypeError, ValueError):
        return None, "Invalid frontend_port"
    if frontend_port < 1 or frontend_port > 65535:
        return None, "frontend_port out of range"

    is_static = proxy_type in ("static_http", "static_https")
    static_root = ""
    index_files = "index.html index.htm"
    if is_static:
        raw_root = str(body.get("static_root") if "static_root" in body else base.get("static_root") or "").strip()
        if not raw_root.startswith("/") or ".." in raw_root or any(c in raw_root for c in ";{}\\\n\r"):
            return None, "static_root must be an absolute directory path"
        static_root = raw_root
        raw_index = str(body.get("index") if "index" in body else base.get("index") or "index.html index.htm").strip()
        if not raw_index or any(c in raw_index for c in ";{}\\\n\r"):
            return None, "Invalid index"
        index_files = raw_index
        norm_backends = []
    # Prefer explicit backends[]; if backend_host/port are sent, rebuild from them
    # so updates don't keep a stale backends[] from a previous save.
    elif "backends" in body and body.get("backends"):
        backends = body.get("backends")
    elif "backend_host" in body or "backend_port" in body or not base.get("backends"):
        prev = (base.get("backends") or [{}])[0] if isinstance(base.get("backends"), list) else {}
        host = str(body.get("backend_host") if "backend_host" in body else (prev.get("host") or base.get("backend_host") or "")).strip()
        try:
            port = int(
                body.get("backend_port")
                if "backend_port" in body
                else (prev.get("port") or base.get("backend_port") or 80)
            )
        except (TypeError, ValueError):
            return None, "Invalid backend_port"
        if not host:
            return None, "backend_host required"
        backends = [{"host": host, "port": port, "weight": 1}]
    else:
        backends = base.get("backends")
    if not is_static:
        if not isinstance(backends, list) or not backends:
            return None, "At least one backend is required"

        norm_backends = []
        for b in backends:
            if not isinstance(b, dict):
                return None, "Invalid backend entry"
            host = str(b.get("host") or "").strip()
            try:
                port = int(b.get("port") or 80)
                weight = int(b.get("weight") or 1)
            except (TypeError, ValueError):
                return None, "Invalid backend port/weight"
            if not _valid_host(host) or port < 1 or port > 65535 or weight < 1 or weight > 1000:
                return None, f"Invalid backend: {host}:{port}"
            # prevent pointing backend at this edge listener (proxy loop → 400/502)
            if port == frontend_port and host in (frontend_ip, "127.0.0.1", "localhost", "::1"):
                return None, "Backend must not point at the same frontend listener (loop risk)"
            if port == frontend_port and frontend_ip in ("0.0.0.0", "*", "::"):
                try:
                    import socket as _socket

                    local_ips = {"127.0.0.1", "::1"}
                    for _info in _socket.getaddrinfo(_socket.gethostname(), None):
                        local_ips.add(_info[4][0])
                    # hostname -I lists assigned addresses (sync; normalize_route is not async)
                    import subprocess as _sp

                    hi = _sp.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
                    if hi.returncode == 0:
                        local_ips.update(hi.stdout.split())
                    if host in local_ips:
                        return None, "Backend must not point at this host's own IP on the frontend port (loop risk)"
                except Exception:
                    pass
            norm_backends.append({
                "host": host,
                "port": port,
                "weight": weight,
                "max_fails": int(b.get("max_fails") or 3),
                "fail_timeout": str(b.get("fail_timeout") or "10s"),
            })

    lb = str(body.get("lb_method") or base.get("lb_method") or "round_robin")
    if lb not in LB_METHODS:
        return None, "Invalid lb_method"

    allow_ips = body.get("allow_ips") if "allow_ips" in body else base.get("allow_ips") or []
    deny_ips = body.get("deny_ips") if "deny_ips" in body else base.get("deny_ips") or []
    for lst, label in ((allow_ips, "allow_ips"), (deny_ips, "deny_ips")):
        if not isinstance(lst, list):
            return None, f"{label} must be a list"
        for item in lst:
            if not _valid_cidr_or_ip(str(item)):
                return None, f"Invalid {label} entry: {item}"

    headers_in = body.get("headers") if "headers" in body else base.get("headers") or []
    headers: list[dict[str, str]] = []
    if headers_in:
        if not isinstance(headers_in, list):
            return None, "headers must be a list of {name,value}"
        for h in headers_in:
            if not isinstance(h, dict):
                return None, "Invalid header"
            hn = str(h.get("name") or "").strip()
            hv = _sanitize_header_value(str(h.get("value") or ""))
            if not HEADER_NAME_RE.match(hn) or hv is None:
                return None, f"Unsafe or invalid header: {hn}"
            # prevent injecting nginx directives via header names that look like directives
            if hn.lower() in {"include", "lua", "perl", "add_header"} and ";" in str(h.get("value")):
                return None, "Rejected header"
            headers.append({"name": hn, "value": hv})

    cert_id = body.get("cert_id") if "cert_id" in body else base.get("cert_id")
    if proxy_type in ("https_reverse", "static_https") and not cert_id:
        # allow empty until cert assigned; apply will warn
        cert_id = base.get("cert_id")

    try:
        connect_timeout = int(body.get("connect_timeout") if "connect_timeout" in body else base.get("connect_timeout") or 60)
        send_timeout = int(body.get("send_timeout") if "send_timeout" in body else base.get("send_timeout") or 300)
        read_timeout = int(body.get("read_timeout") if "read_timeout" in body else base.get("read_timeout") or 300)
        client_max_body = str(body.get("client_max_body_size") if "client_max_body_size" in body else base.get("client_max_body_size") or "100m")
    except (TypeError, ValueError):
        return None, "Invalid timeout values"
    if not re.fullmatch(r"\d+[kKmMgG]?", client_max_body):
        return None, "Invalid client_max_body_size"

    websocket = bool(body.get("websocket") if "websocket" in body else base.get("websocket", True))
    http2 = bool(body.get("http2") if "http2" in body else base.get("http2", True))
    large_headers = bool(body.get("large_headers") if "large_headers" in body else base.get("large_headers", False))
    # Carbonio / Zimbra-style apps need big header buffers by default
    if not large_headers and ("carbonio" in name.lower() or "zimbra" in name.lower()):
        large_headers = True
    enabled = bool(body.get("enabled") if "enabled" in body else base.get("enabled", True))
    logging = bool(body.get("logging") if "logging" in body else base.get("logging", True))
    verify_backend_tls = bool(body.get("verify_backend_tls") if "verify_backend_tls" in body else base.get("verify_backend_tls", False))
    backend_proto = str(body.get("backend_proto") or base.get("backend_proto") or ("https" if verify_backend_tls else "http"))
    if backend_proto not in ("http", "https", "tcp", "udp"):
        return None, "Invalid backend_proto"

    keepalive = int(body.get("tcp_keepalive") if "tcp_keepalive" in body else base.get("tcp_keepalive") or 60)
    session_timeout = int(body.get("session_timeout") if "session_timeout" in body else base.get("session_timeout") or 3600)

    route = {
        "id": base.get("id") or _new_id("r"),
        "name": name,
        "domain": domain,
        "aliases": aliases,
        "proxy_type": proxy_type,
        "frontend_ip": frontend_ip,
        "frontend_port": frontend_port,
        "backends": norm_backends,
        "backend_host": norm_backends[0]["host"] if norm_backends else "",
        "backend_port": norm_backends[0]["port"] if norm_backends else 0,
        "static_root": static_root,
        "index": index_files,
        "backend_proto": backend_proto,
        "lb_method": lb,
        "connect_timeout": max(1, min(connect_timeout, 86400)),
        "send_timeout": max(1, min(send_timeout, 86400)),
        "read_timeout": max(1, min(read_timeout, 86400)),
        "client_max_body_size": client_max_body,
        "websocket": websocket,
        "http2": http2,
        "large_headers": large_headers,
        "headers": headers,
        "verify_backend_tls": verify_backend_tls,
        "allow_ips": [str(x) for x in allow_ips],
        "deny_ips": [str(x) for x in deny_ips],
        "cert_id": cert_id,
        "enabled": enabled,
        "logging": logging,
        "tcp_keepalive": max(0, min(keepalive, 86400)),
        "session_timeout": max(1, min(session_timeout, 86400 * 7)),
        "updated_at": _now(),
        "created_at": base.get("created_at") or _now(),
    }
    return route, ""


def _conflict_check(routes: list[dict[str, Any]], candidate: dict[str, Any]) -> str | None:
    cid = candidate.get("id")
    layer = PROXY_TYPES[candidate["proxy_type"]]["layer"]
    domains = set()
    if candidate.get("domain"):
        domains.add(candidate["domain"].lower())
    for a in candidate.get("aliases") or []:
        domains.add(str(a).lower())

    for r in routes:
        if r.get("id") == cid:
            continue
        if not r.get("enabled", True):
            continue
        # port+ip conflict for stream / same frontend
        same_bind = (
            r.get("frontend_ip") == candidate.get("frontend_ip")
            and int(r.get("frontend_port") or 0) == int(candidate.get("frontend_port") or 0)
        )
        r_layer = PROXY_TYPES.get(r.get("proxy_type", ""), {}).get("layer")
        if same_bind and r_layer == "stream" and layer == "stream":
            # tcp/udp/tls_passthrough share listeners carefully
            if r.get("proxy_type") == "udp" and candidate.get("proxy_type") == "udp":
                return f"UDP port conflict with route '{r.get('name')}'"
            if r.get("proxy_type") != "udp" and candidate.get("proxy_type") != "udp":
                # SNI multiplex OK on same 443 for tls_passthrough only
                if not (r.get("proxy_type") == "tls_passthrough" and candidate.get("proxy_type") == "tls_passthrough"):
                    if r.get("proxy_type") == candidate.get("proxy_type") == "tls_passthrough":
                        pass  # domain uniqueness below
                    else:
                        return f"Frontend bind conflict with route '{r.get('name')}'"
        if domains and (layer == "http" or candidate["proxy_type"] == "tls_passthrough"):
            other = set()
            if r.get("domain"):
                other.add(str(r["domain"]).lower())
            for a in r.get("aliases") or []:
                other.add(str(a).lower())
            overlap = domains & other
            if overlap and same_bind:
                return f"Domain conflict ({', '.join(sorted(overlap))}) with route '{r.get('name')}'"
            if overlap and r_layer == layer and int(r.get("frontend_port") or 0) == int(candidate.get("frontend_port") or 0):
                return f"Domain conflict ({', '.join(sorted(overlap))}) with route '{r.get('name')}'"
    return None


def _upstream_name(route: dict[str, Any]) -> str:
    return "up_" + re.sub(r"[^a-zA-Z0-9_]", "_", route["id"])


def _listen_addr(ip: str, port: int, udp: bool = False) -> str:
    suffix = " udp" if udp else ""
    if ip in ("0.0.0.0", "*", ""):
        return f"{port}{suffix}"
    if ":" in ip and not ip.startswith("["):
        return f"[{ip}]:{port}{suffix}"
    return f"{ip}:{port}{suffix}"


def _acl_lines(route: dict[str, Any], indent: str = "    ") -> list[str]:
    lines: list[str] = []
    for ip in route.get("allow_ips") or []:
        lines.append(f"{indent}allow {ip};")
    for ip in route.get("deny_ips") or []:
        lines.append(f"{indent}deny {ip};")
    if route.get("allow_ips"):
        lines.append(f"{indent}deny all;")
    return lines


def _render_upstream(route: dict[str, Any]) -> str:
    name = _upstream_name(route)
    lines = [f"upstream {name} {{"]
    if route.get("lb_method") == "least_conn":
        lines.append("    least_conn;")
    elif route.get("lb_method") == "ip_hash" and PROXY_TYPES[route["proxy_type"]]["layer"] == "http":
        lines.append("    ip_hash;")
    for b in route["backends"]:
        host = b["host"]
        if host.startswith("docker:"):
            host = host[7:]
        lines.append(
            f"    server {host}:{b['port']} weight={b['weight']} "
            f"max_fails={b.get('max_fails', 3)} fail_timeout={b.get('fail_timeout', '10s')};"
        )
    lines.append("}")
    return "\n".join(lines)


def _cert_paths(opts: dict[str, Any], cert_id: str) -> tuple[Path, Path]:
    root = _certs_files_dir(opts) / cert_id
    return root / "fullchain.pem", root / "privkey.pem"


def _list_cert_meta(opts: dict[str, Any]) -> list[dict[str, Any]]:
    meta_dir = _certs_meta_dir(opts)
    out: list[dict[str, Any]] = []
    if not meta_dir.is_dir():
        return out
    for p in sorted(meta_dir.glob("*.json")):
        data = _load_json(p)
        if data and "id" in data:
            # never expose private key material
            pub = {k: v for k, v in data.items() if k not in {"private_key_pem", "pfx_password"}}
            out.append(pub)
    return out


def _get_cert_meta(opts: dict[str, Any], cert_id: str) -> dict[str, Any] | None:
    return _load_json(_certs_meta_dir(opts) / f"{cert_id}.json")


async def _openssl(*args: str, input_text: str | None = None) -> tuple[int, str, str]:
    openssl = shutil.which("openssl") or "openssl"
    try:
        proc = await __import__("asyncio").create_subprocess_exec(
            openssl,
            *args,
            stdin=__import__("asyncio").subprocess.PIPE if input_text is not None else None,
            stdout=__import__("asyncio").subprocess.PIPE,
            stderr=__import__("asyncio").subprocess.PIPE,
        )
        stdout, stderr = await __import__("asyncio").wait_for(
            proc.communicate(input=input_text.encode() if input_text is not None else None),
            timeout=30.0,
        )
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


async def _parse_cert_pem(pem: str) -> dict[str, Any]:
    code, out, err = await _openssl("x509", "-noout", "-subject", "-issuer", "-dates", "-ext", "subjectAltName", input_text=pem)
    if code != 0:
        return {"ok": False, "error": err or "invalid certificate"}
    subject = issuer = not_before = not_after = ""
    sans: list[str] = []
    for line in out.splitlines():
        if line.startswith("subject="):
            subject = line[8:].strip()
        elif line.startswith("issuer="):
            issuer = line[7:].strip()
        elif line.startswith("notBefore="):
            not_before = line[10:].strip()
        elif line.startswith("notAfter="):
            not_after = line[9:].strip()
        elif "DNS:" in line or "IP Address:" in line:
            for part in line.split(","):
                part = part.strip()
                if part.startswith("DNS:"):
                    sans.append(part[4:].strip())
                elif part.startswith("IP Address:"):
                    sans.append(part[11:].strip())
    days_left = None
    if not_after:
        code2, epoch, _ = await _openssl("x509", "-noout", "-enddate", input_text=pem)
        # parse with openssl -checkend
        code3, _, _ = await _openssl("x509", "-noout", "-checkend", "0", input_text=pem)
        expired = code3 != 0
        # approximate days via checkend steps
        for days in (0, 7, 14, 30, 60, 90, 180, 365, 730, 1095):
            c, _, _ = await _openssl("x509", "-noout", "-checkend", str(days * 86400), input_text=pem)
            if c != 0:
                days_left = days
                break
        else:
            days_left = 1095 if not expired else 0
        if expired:
            days_left = 0
    return {
        "ok": True,
        "subject": subject,
        "issuer": issuer,
        "not_before": not_before,
        "not_after": not_after,
        "sans": sans,
        "days_left": days_left,
        "expired": days_left == 0,
    }


async def _verify_cert_key(cert_pem: str, key_pem: str) -> tuple[bool, str]:
    """Match certificate to private key for RSA and ECDSA (LE defaults to ECDSA)."""
    code_pub, pub_cert, err_pub = await _openssl("x509", "-noout", "-pubkey", input_text=cert_pem)
    code_key, pub_key, err_key = await _openssl("pkey", "-pubout", input_text=key_pem)
    if code_pub == 0 and code_key == 0 and pub_cert.strip() and pub_cert.strip() == pub_key.strip():
        return True, ""
    # Fallback: RSA modulus compare
    code1, mod1, err1 = await _openssl("x509", "-noout", "-modulus", input_text=cert_pem)
    code2, mod2, err2 = await _openssl("rsa", "-noout", "-modulus", input_text=key_pem)
    if code1 == 0 and code2 == 0 and mod1.strip() and mod1.strip() == mod2.strip():
        return True, ""
    return False, err_key or err_pub or err2 or err1 or "certificate/key mismatch"


def _render_http_route(opts: dict[str, Any], route: dict[str, Any]) -> str:
    is_static = route["proxy_type"] in ("static_http", "static_https")
    up = "" if is_static else _upstream_name(route)
    names = [route["domain"]] + list(route.get("aliases") or [])
    server_name = " ".join(names) if names else "_"
    port = int(route["frontend_port"])
    ssl = route["proxy_type"] in ("https_reverse", "static_https")
    # nginx 1.24 (Ubuntu) uses "listen ... http2"; "http2 on;" needs >= 1.25.1
    http2 = bool(route.get("http2")) and ssl
    listen = _listen_addr(route["frontend_ip"], port)
    if ssl:
        listen = f"{listen} ssl"
    if http2:
        listen = f"{listen} http2"
    proto = route.get("backend_proto") or "http"
    lines = [MANAGED_MARKER]
    if not is_static:
        lines.extend([_render_upstream(route), ""])
    lines.extend(["server {", f"    listen {listen};"])
    if route["frontend_ip"] in ("0.0.0.0", "*"):
        v6 = f"    listen [::]:{port}"
        if ssl:
            v6 += " ssl"
        if http2:
            v6 += " http2"
        lines.append(f"{v6};")
    lines.append(f"    server_name {server_name};")
    lines.extend(_acl_lines(route))

    if ssl:
        cert_id = route.get("cert_id")
        if cert_id:
            fullchain, privkey = _cert_paths(opts, cert_id)
            lines.append(f"    ssl_certificate {fullchain};")
            lines.append(f"    ssl_certificate_key {privkey};")
            lines.append("    ssl_session_cache shared:SSL:10m;")
            lines.append("    ssl_protocols TLSv1.2 TLSv1.3;")

    if route.get("logging"):
        lines.append(f"    access_log /var/log/nginx/lnxadmin-{route['id']}.access.log;")
        lines.append(f"    error_log /var/log/nginx/lnxadmin-{route['id']}.error.log warn;")
    else:
        lines.append("    access_log off;")

    lines.append(f"    client_max_body_size {route.get('client_max_body_size', '100m')};")
    if route.get("large_headers"):
        # Fixes nginx 400 "Request Header Or Cookie Too Large" (Carbonio/Zimbra cookies)
        # On nginx 1.24+, http2_max_* are obsolete — large_client_header_buffers is enough.
        lines.append("    client_header_buffer_size 64k;")
        lines.append("    large_client_header_buffers 8 64k;")
    # Keep ACME reachable even when this vhost owns the hostname on :80
    if int(route.get("frontend_port") or 0) == 80 or route.get("proxy_type") == "http_reverse":
        lines.append(_render_acme_location(opts).rstrip())

    if is_static:
        root = route.get("static_root") or "/var/www/html"
        index = route.get("index") or "index.html index.htm"
        lines.extend(
            [
                f"    root {root};",
                f"    index {index};",
                "    location ~* \\.(ps1|psm1|psd1|sh)$ {",
                "        default_type text/plain;",
                "    }",
                "    location / {",
                "        try_files $uri $uri/ =404;",
                "    }",
                "}",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "    location / {",
            f"        proxy_pass {proto}://{up};",
            "        proxy_http_version 1.1;",
            "        proxy_set_header Host $host;",
            "        proxy_set_header X-Real-IP $remote_addr;",
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "        proxy_set_header X-Forwarded-Proto $scheme;",
            f"        proxy_connect_timeout {route.get('connect_timeout', 60)}s;",
            f"        proxy_send_timeout {route.get('send_timeout', 300)}s;",
            f"        proxy_read_timeout {route.get('read_timeout', 300)}s;",
            "        proxy_buffering off;",
            "        proxy_request_buffering off;",
        ]
    )
    if route.get("large_headers"):
        lines.extend(
            [
                "        proxy_buffer_size 128k;",
                "        proxy_buffers 8 128k;",
                "        proxy_busy_buffers_size 256k;",
            ]
        )
    for h in route.get("headers") or []:
        lines.append(f"        proxy_set_header {h['name']} {h['value']};")
    if route.get("websocket"):
        lines.extend(
            [
                "        proxy_set_header Upgrade $http_upgrade;",
                '        proxy_set_header Connection $connection_upgrade;',
            ]
        )
    if route.get("verify_backend_tls") is False and proto == "https":
        lines.append("        proxy_ssl_verify off;")
    elif route.get("verify_backend_tls") and proto == "https":
        lines.append("        proxy_ssl_verify on;")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_stream_route(route: dict[str, Any]) -> str:
    up = _upstream_name(route)
    udp = route["proxy_type"] == "udp"
    lines = [MANAGED_MARKER, _render_upstream(route), "", "server {"]
    listen = _listen_addr(route["frontend_ip"], int(route["frontend_port"]), udp=udp)
    lines.append(f"    listen {listen};")
    if route["proxy_type"] == "tls_passthrough":
        lines.append("    ssl_preread on;")
        # map is generated globally; here filter by SNI via server name isn't native —
        # we use a shared map + one listener. Per-route files for non-SNI tcp/udp.
    lines.extend(_acl_lines(route))
    if route.get("logging"):
        lines.append(f"    access_log /var/log/nginx/lnxadmin-{route['id']}.stream.log;")
        lines.append(f"    error_log /var/log/nginx/lnxadmin-{route['id']}.stream-error.log warn;")
    lines.append(f"    proxy_timeout {route.get('session_timeout', 3600)}s;")
    if route.get("tcp_keepalive"):
        lines.append(f"    proxy_socket_keepalive on;")
    lines.append(f"    proxy_pass {up};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_tls_passthrough_bundle(routes: list[dict[str, Any]]) -> str:
    """One shared SSL preread listener + map by SNI."""
    by_bind: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in routes:
        if r.get("proxy_type") != "tls_passthrough" or not r.get("enabled", True):
            continue
        key = (r.get("frontend_ip") or "0.0.0.0", int(r["frontend_port"]))
        by_bind.setdefault(key, []).append(r)
    if not by_bind:
        return ""

    chunks = [MANAGED_MARKER, "# TLS Passthrough via ssl_preread + SNI map"]
    for (ip, port), group in by_bind.items():
        map_var = f"lnxadmin_sni_{port}"
        for r in group:
            chunks.append(_render_upstream(r))
            chunks.append("")
        chunks.append(f"map $ssl_preread_server_name ${map_var} {{")
        for r in group:
            up = _upstream_name(r)
            names = [r["domain"]] + list(r.get("aliases") or [])
            for n in names:
                if n:
                    chunks.append(f"    {n} {up};")
        chunks.append(f"    default {_upstream_name(group[0])};")
        chunks.append("}")
        chunks.append("")
        chunks.append("server {")
        chunks.append(f"    listen {_listen_addr(ip, port)};")
        if ip in ("0.0.0.0", "*"):
            chunks.append(f"    listen [::]:{port};")
        chunks.append("    ssl_preread on;")
        chunks.append(f"    proxy_pass ${map_var};")
        chunks.append(f"    proxy_timeout {group[0].get('session_timeout', 3600)}s;")
        chunks.append("    proxy_socket_keepalive on;")
        chunks.append("}")
        chunks.append("")
    return "\n".join(chunks)


def _acme_webroot(opts: dict[str, Any]) -> str:
    return str(_managed(opts) / "acme-webroot")


def _render_acme_location(opts: dict[str, Any], indent: str = "    ") -> str:
    root = _acme_webroot(opts)
    return (
        f"{indent}location ^~ /.well-known/acme-challenge/ {{\n"
        f"{indent}    root {root};\n"
        f"{indent}    default_type text/plain;\n"
        f"{indent}    try_files $uri =404;\n"
        f"{indent}}}\n"
    )


def _foreign_default_server(port: int) -> bool:
    """True when a non-managed nginx file already has default_server on this port."""
    root = Path("/etc/nginx")
    managed = Path(DEFAULT_MANAGED_DIR)
    if not root.is_dir():
        return False
    needle = re.compile(rf"listen\s+[^\n;]*default_server[^\n;]*:{port}\b|listen\s+[^\n;]*:{port}[^\n;]*default_server|listen\s+[^\n;]*\b{port}\b[^\n;]*default_server")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(managed.resolve())
            continue
        except ValueError:
            pass
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle.search(text):
            return True
    return False


def _render_map_upgrade(
    opts: dict[str, Any] | None = None,
    extra_server_names: list[str] | None = None,
    *,
    public_http: bool = True,
) -> str:
    """Core maps + localhost stub_status + public :80 ACME HTTP-01 server."""
    o = _opts(opts)
    names: list[str] = []
    for n in extra_server_names or []:
        n = str(n).strip().lower().rstrip(".")
        if n and n not in names and _valid_domain(n) and not n.startswith("*."):
            names.append(n)
    # Also include domains from existing HTTP(S) routes so renewals keep working
    state = _load_state(o)
    for r in state.get("routes") or []:
        if not r.get("enabled", True):
            continue
        if r.get("proxy_type") not in ("http_reverse", "https_reverse", "static_http", "static_https"):
            continue
        for n in [r.get("domain"), *(r.get("aliases") or [])]:
            n = str(n or "").strip().lower().rstrip(".")
            if n and n not in names and _valid_domain(n) and not n.startswith("*."):
                names.append(n)
    # "_" never matches real Host headers; without domains use default_server for ACME only.
    # Skip it when the distro site (sites-enabled/default) already owns default_server on :80.
    use_default = not names and not _foreign_default_server(80)
    server_name = " ".join(names) if names else "_"
    listen_extra = " default_server" if use_default else ""
    text = f"""{MANAGED_MARKER}
# WebSocket Connection header helper
map $http_upgrade $connection_upgrade {{
    default upgrade;
    ''      close;
}}

# Local-only stub_status
server {{
    listen 127.0.0.1:8088;
    server_name localhost;
    location /lnxadmin-nginx-status {{
        stub_status;
        allow 127.0.0.1;
        deny all;
    }}
}}
"""
    if not public_http:
        return text + "\n# Public :80 is already taken by another process; ACME listener omitted.\n"
    return text + f"""
# HTTP-01 ACME challenges — must be reachable from the public Internet on :80
server {{
    listen 80{listen_extra};
    listen [::]:80{listen_extra};
    server_name {server_name};

{_render_acme_location(o)}
    location / {{
        return 404;
    }}
}}
"""


async def _ensure_acme_http(opts: dict[str, Any], domains: list[str]) -> dict[str, Any]:
    """Write/reload public :80 ACME server and verify challenge path locally."""
    await _ensure_dirs(opts)
    ok, err = await _ensure_nginx_includes(opts)
    if not ok:
        return {"ok": False, "error": f"nginx include setup failed: {err}"}

    webroot = Path(_acme_webroot(opts))
    challenge_dir = webroot / ".well-known" / "acme-challenge"
    await run_privileged(["mkdir", "-p", str(challenge_dir)])
    await run_privileged(["chmod", "-R", "a+rX", str(webroot)])

    # Keep shared http.d pieces: write ACME/bootstrap without wiping user routes.conf
    bootstrap = _render_map_upgrade(opts, extra_server_names=domains)
    acme_path = str(_managed(opts) / "http.d" / "00-acme.conf")
    ok, err = await _write_file_priv(acme_path, bootstrap, "644")
    if not ok:
        return {"ok": False, "error": f"Failed to write ACME config: {err}"}

    # Ensure empty placeholder so include glob never fails oddly
    routes_path = _managed(opts) / "http.d" / "routes.conf"
    if not routes_path.is_file():
        await _write_file_priv(str(routes_path), f"{MANAGED_MARKER}\n# routes applied via Config / Apply\n", "644")

    stream_path = _managed(opts) / "stream.d" / "routes.conf"
    if not stream_path.is_file():
        await _write_file_priv(str(stream_path), f"{MANAGED_MARKER}\n# no stream routes\n", "644")

    test_ok, test_msg = await _nginx_test()
    if not test_ok:
        return {"ok": False, "error": f"nginx -t failed after ACME config: {test_msg}"}
    reload_ok, reload_msg = await _nginx_reload()
    if not reload_ok:
        return {"ok": False, "error": f"nginx reload failed: {reload_msg}"}

    # Local probe with Host header for each domain (retry — reload can race briefly)
    token = "lnxadmin-acme-probe"
    probe_file = challenge_dir / token
    try:
        probe_file.write_text("ok-lnxadmin-acme\n", encoding="utf-8")
    except OSError:
        await _write_file_priv(str(probe_file), "ok-lnxadmin-acme\n", "644")

    probes = []
    any_ok = False
    for d in domains:
        local_ok = False
        detail = ""
        for _attempt in range(5):
            code, out, err = await run_cmd(
                [
                    "curl", "-fsS", "--max-time", "5",
                    "-H", f"Host: {d}",
                    f"http://127.0.0.1/.well-known/acme-challenge/{token}",
                ],
                timeout=8.0,
            )
            detail = (err or out or "")[:200]
            local_ok = code == 0 and "ok-lnxadmin-acme" in (out or "")
            if local_ok:
                break
            await __import__("asyncio").sleep(0.4)

        # Public path as Let's Encrypt sees it (do not follow redirects)
        pub_code, pub_out, pub_err = await run_cmd(
            [
                "curl", "-sS", "--max-time", "8",
                "-o", "/tmp/lnxadmin-acme-pub-body",
                "-w", "%{http_code}|%{redirect_url}",
                "--path-as-is",
                f"http://{d}/.well-known/acme-challenge/{token}",
            ],
            timeout=12.0,
        )
        pub_body = ""
        try:
            pub_body = Path("/tmp/lnxadmin-acme-pub-body").read_text(encoding="utf-8", errors="replace")[:300]
        except OSError:
            pub_body = ""
        meta = (pub_out or "").strip()
        pub_status = meta.split("|")[0] if meta else ""
        redirect_url = meta.split("|")[1] if "|" in meta else ""
        hairpin_ok = pub_code == 0 and "ok-lnxadmin-acme" in pub_body and pub_status == "200"
        public_redirect = pub_status.startswith("30") or bool(redirect_url)

        # Hairpin NAT can make public-IP checks succeed from THIS host while the
        # Internet (Let's Encrypt) still cannot connect. Probe external openness.
        ext_open: bool | None = None
        ext_detail = ""
        code_a, out_a, _ = await run_cmd(["dig", "+short", "A", d], timeout=10.0)
        ip = ""
        for line in (out_a or "").splitlines():
            line = line.strip()
            if line and not line.endswith("."):
                try:
                    ipaddress.ip_address(line)
                    ip = line
                    break
                except ValueError:
                    continue
        if ip:
            # yougetsignal-style check (best-effort)
            code_e, out_e, err_e = await run_cmd(
                [
                    "curl", "-sS", "--max-time", "12",
                    "-d", f"remoteAddress={ip}&portNumber=80",
                    "https://ports.yougetsignal.com/check-port.php",
                ],
                timeout=15.0,
            )
            text = (out_e or err_e or "").lower()
            if "is open" in text:
                ext_open = True
            elif "is closed" in text:
                ext_open = False
            ext_detail = (out_e or err_e or "")[:240]

        public_ok = bool(hairpin_ok and ext_open is not False)
        if hairpin_ok and ext_open is False:
            public_ok = False

        probes.append(
            {
                "domain": d,
                "local_ok": local_ok,
                "detail": detail,
                "hairpin_ok": hairpin_ok,
                "public_ok": public_ok,
                "public_status": pub_status,
                "public_redirect": public_redirect,
                "public_redirect_url": redirect_url,
                "public_detail": (pub_err or pub_body or "")[:240],
                "resolved_ip": ip,
                "external_port80_open": ext_open,
                "external_port80_detail": ext_detail,
            }
        )
        any_ok = any_ok or local_ok

    # Cleanup probe
    try:
        probe_file.unlink(missing_ok=True)
    except OSError:
        await run_privileged(["rm", "-f", str(probe_file)])

    if not any_ok:
        return {
            "ok": False,
            "error": (
                "ACME HTTP-01 path is not served by local nginx on :80. "
                "Another server block may be catching the request (check sites-enabled/default). "
                f"Probes: {probes}"
            ),
            "probes": probes,
        }

    # Hard-fail early when public HTTP does not reach THIS nginx (common with Carbonio / other edge)
    public_problems = [p for p in probes if not p.get("public_ok")]
    if public_problems:
        bits = []
        for p in public_problems:
            if p.get("external_port80_open") is False:
                bits.append(
                    f"{p['domain']}: TCP port 80 is CLOSED on public IP {p.get('resolved_ip')} from the Internet "
                    f"(local/hairpin check may still work). Open/forward WAN TCP/80 → this host, or use DNS-01."
                )
            elif p.get("public_redirect"):
                bits.append(
                    f"{p['domain']}: public :80 redirects to {p.get('public_redirect_url') or 'HTTPS'} "
                    "(another reverse proxy owns the public IP — often Carbonio). "
                    "HTTP-01 must be answered in plain HTTP without redirect, or use DNS-01."
                )
            elif p.get("public_status"):
                bits.append(
                    f"{p['domain']}: public HTTP returned {p.get('public_status')} "
                    "(not this Nginx ACME webroot). Forward TCP/80 to this host or use DNS-01."
                )
            else:
                bits.append(
                    f"{p['domain']}: cannot fetch http://{p['domain']}/.well-known/acme-challenge/ "
                    "from this host via public DNS — open/forward TCP/80 or use DNS-01."
                )
        return {
            "ok": False,
            "error": " ".join(bits),
            "probes": probes,
            "hint": (
                "Nginx ACME works locally, but Let's Encrypt validators are on the public Internet. "
                "On the router/firewall for 95.x / your WAN IP: allow and DNAT TCP/80 (and usually 443) "
                "to this server. Hairpin/NAT from inside the LAN is not enough. "
                "Or use DNS-01 Manual at your registrar."
            ),
        }
    return {"ok": True, "probes": probes, "acme_path": acme_path}


def _friendly_acme_error(log: str) -> str:
    low = (log or "").lower()
    if "timeout during connect" in low or "likely firewall problem" in low:
        return (
            "Let's Encrypt could not connect to this host on TCP port 80 (timeout). "
            "Open inbound TCP/80 on your edge firewall/router/NAT to this server's public IP, "
            "and ensure DNS A/AAAA for the domain points here. "
            "HTTP-01 cannot succeed while port 80 is blocked from the Internet."
        )
    if "connection refused" in low:
        return (
            "Let's Encrypt reached the IP but connection was refused on port 80. "
            "Ensure nginx listens on 0.0.0.0:80 and no firewall rejects the CA validators."
        )
    if "unauthorized" in low or "invalid response" in low:
        return (
            "Let's Encrypt connected but the ACME challenge file was missing or wrong. "
            "Apply Nginx config, keep HTTP-01 webroot enabled, and retry."
        )
    if "dns problem" in low or "nxdomain" in low or "no valid a records" in low:
        return "DNS problem: the domain does not resolve to this server from the public Internet."
    if "too many certificates" in low or "rate limit" in low or "too many failed authorizations" in low:
        return (
            "Let's Encrypt rate limit hit for this domain. "
            "Wait for the retry time in the error (usually up to 1 hour after failed attempts), then retry. "
            "Use DNS-01 or fix connectivity before retrying to avoid another lockout."
        )
    return ""


async def generate_config_preview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    bootstrap = _render_map_upgrade(opts)
    route_parts: list[str] = []
    stream_tcp: list[str] = []
    passthrough = [r for r in state["routes"] if r.get("enabled", True) and r.get("proxy_type") == "tls_passthrough"]
    for r in state["routes"]:
        if not r.get("enabled", True):
            continue
        pt = r.get("proxy_type")
        if pt in ("http_reverse", "https_reverse", "static_http", "static_https"):
            if pt in ("https_reverse", "static_https") and not r.get("cert_id"):
                return {"ok": False, "error": f"Route '{r.get('name')}' (HTTPS) has no certificate assigned"}
            route_parts.append(_render_http_route(opts, r))
        elif pt in ("tcp", "udp"):
            stream_tcp.append(_render_stream_route(r))
    stream_parts = []
    if passthrough:
        stream_parts.append(_render_tls_passthrough_bundle(passthrough))
    stream_parts.extend(stream_tcp)
    routes_http = "\n".join(route_parts) if route_parts else f"{MANAGED_MARKER}\n# no http routes\n"
    return {
        "ok": True,
        "bootstrap": bootstrap,
        "http": bootstrap + "\n" + routes_http,  # combined for UI preview
        "routes_http": routes_http,
        "stream": "\n".join(stream_parts) if stream_parts else f"{MANAGED_MARKER}\n# no stream routes\n",
        "route_count": sum(1 for r in state["routes"] if r.get("enabled", True)),
    }


async def _ensure_nginx_includes(opts: dict[str, Any]) -> tuple[bool, str]:
    http_include = (
        f"{MANAGED_MARKER}\n"
        f"include {opts['managed_dir']}/http.d/*.conf;\n"
    )
    ok, err = await _write_file_priv(opts["http_include"], http_include, "644")
    if not ok:
        return False, err

    # Ensure stream block in main nginx.conf
    conf_path = Path(opts["nginx_conf"])
    try:
        text = conf_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Cannot read nginx.conf: {exc}"

    stream_block = (
        f"\n{STREAM_BEGIN}\n"
        f"stream {{\n"
        f"    include {opts['managed_dir']}/stream.d/*.conf;\n"
        f"}}\n"
        f"{STREAM_END}\n"
    )
    if STREAM_BEGIN in text and STREAM_END in text:
        # refresh inner content
        pattern = re.compile(re.escape(STREAM_BEGIN) + r".*?" + re.escape(STREAM_END), re.S)
        new_text = pattern.sub(stream_block.strip(), text)
    else:
        new_text = text.rstrip() + "\n" + stream_block

    if new_text != text:
        # backup then write
        bak = str(conf_path) + f".lnxadmin-bak-{int(time.time())}"
        await run_privileged(["cp", "-a", str(conf_path), bak])
        ok, err = await _write_file_priv(str(conf_path), new_text, "644")
        if not ok:
            return False, err
    return True, ""


async def _nginx_test() -> tuple[bool, str]:
    code, out, err = await run_privileged(["nginx", "-t"], timeout=20.0)
    msg = ((out or "") + (err or "")).strip()
    return code == 0, msg


async def _port_holder(port: int) -> str:
    """Process name listening on TCP port, or empty if the port is free."""
    code, out, _err = await run_cmd(["ss", "-ltnp", f"sport = :{port}"], timeout=8.0)
    if code != 0:
        return ""
    for line in (out or "").splitlines():
        if f":{port}" not in line:
            continue
        match = re.search(r'users:\(\("([^"]+)"', line)
        if match:
            return match.group(1)
    return ""


async def _host_nginx_can_bind_public() -> tuple[bool, str]:
    """Host nginx cannot bind :80/:443 when another process already holds them."""
    holders = []
    for port in (80, 443):
        name = await _port_holder(port)
        if name and name not in ("nginx",):
            holders.append(f"{port} ({name})")
    if holders:
        return False, ", ".join(holders)
    return True, ""


def _park_distro_default_site() -> None:
    """Drop Debian's sites-enabled/default so host nginx does not listen on :80.

    The parked symlink must leave sites-enabled: nginx includes every file in that directory.
    """
    link = Path("/etc/nginx/sites-enabled/default")
    parked = Path("/etc/nginx/sites-available/default.disabled-by-lnxadmin")
    leftover = Path("/etc/nginx/sites-enabled/default.disabled-by-lnxadmin")
    if leftover.is_symlink() or leftover.is_file():
        leftover.unlink()
    if link.is_symlink() and not parked.exists():
        link.rename(parked)
    elif link.is_symlink():
        link.unlink()


async def _nginx_reload() -> tuple[bool, str]:
    """Reload a running nginx, or start the systemd unit if it is inactive."""
    code, out, _err = await run_privileged(["systemctl", "is-active", "nginx"], timeout=15.0)
    active = code == 0 and (out or "").strip() == "active"
    if not active:
        pid_path = Path("/run/nginx.pid")
        if pid_path.is_file() and pid_path.stat().st_size == 0:
            await run_privileged(["rm", "-f", str(pid_path)], timeout=10.0)
        code_s, out_s, err_s = await run_privileged(["systemctl", "start", "nginx"], timeout=25.0)
        msg = ((out_s or "") + (err_s or "")).strip()
        if code_s != 0:
            return False, msg or "nginx is not running and systemctl start failed"
        return True, "started"
    code_r, out_r, err_r = await run_privileged(["systemctl", "reload", "nginx"], timeout=20.0)
    msg = ((out_r or "") + (err_r or "")).strip()
    return code_r == 0, msg or "reloaded"


async def apply_config(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    if not tools["nginx"]:
        return {"ok": False, "error": "Nginx is not installed"}

    preview = await generate_config_preview(opts)
    if not preview.get("ok"):
        return preview

    ok, err = await _ensure_dirs(opts)
    if not ok:
        return {"ok": False, "error": err}
    ok, err = await _ensure_nginx_includes(opts)
    if not ok:
        return {"ok": False, "error": err}

    # Backup current managed configs
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_root = _backups_dir(opts) / ts
    await run_privileged(["mkdir", "-p", str(backup_root)])
    await run_privileged(["cp", "-a", str(_managed(opts) / "http.d"), str(backup_root / "http.d")])
    await run_privileged(["cp", "-a", str(_managed(opts) / "stream.d"), str(backup_root / "stream.d")])
    state = _load_state(opts)
    await _write_file_priv(str(backup_root / "state.json"), json.dumps(state, indent=2), "600")

    acme_path = str(_managed(opts) / "http.d" / "00-acme.conf")
    http_path = str(_managed(opts) / "http.d" / "routes.conf")
    stream_path = str(_managed(opts) / "stream.d" / "routes.conf")
    ok, err = await _write_file_priv(acme_path, preview.get("bootstrap") or _render_map_upgrade(opts), "644")
    if not ok:
        return {"ok": False, "error": f"Write ACME/bootstrap config failed: {err}"}
    ok, err = await _write_file_priv(http_path, preview.get("routes_http") or f"{MANAGED_MARKER}\n", "644")
    if not ok:
        return {"ok": False, "error": f"Write http config failed: {err}"}
    ok, err = await _write_file_priv(stream_path, preview["stream"], "644")
    if not ok:
        return {"ok": False, "error": f"Write stream config failed: {err}"}

    can_bind, held = await _host_nginx_can_bind_public()
    if not can_bind:
        _park_distro_default_site()
        ok, err = await _write_file_priv(
            acme_path,
            _render_map_upgrade(opts, public_http=False),
            "644",
        )
        if not ok:
            return {"ok": False, "error": f"Write ACME/bootstrap config failed: {err}"}

    test_ok, test_msg = await _nginx_test()
    if not test_ok:
        # rollback managed files from backup
        await run_privileged(["rm", "-rf", str(_managed(opts) / "http.d")])
        await run_privileged(["rm", "-rf", str(_managed(opts) / "stream.d")])
        await run_privileged(["cp", "-a", str(backup_root / "http.d"), str(_managed(opts) / "http.d")])
        await run_privileged(["cp", "-a", str(backup_root / "stream.d"), str(_managed(opts) / "stream.d")])
        await _audit(opts, "apply_failed", {"error": test_msg, "backup": ts})
        return {"ok": False, "error": f"nginx -t failed: {test_msg}", "backup": ts, "rolled_back": True}

    reload_ok, reload_msg = await _nginx_reload()
    if reload_ok and not can_bind:
        reload_msg = (
            f"{reload_msg}; public {held} stays with the process already listening there"
        )
    if not reload_ok:
        await run_privileged(["rm", "-rf", str(_managed(opts) / "http.d")])
        await run_privileged(["rm", "-rf", str(_managed(opts) / "stream.d")])
        await run_privileged(["cp", "-a", str(backup_root / "http.d"), str(_managed(opts) / "http.d")])
        await run_privileged(["cp", "-a", str(backup_root / "stream.d"), str(_managed(opts) / "stream.d")])
        await _nginx_reload()
        await _audit(opts, "reload_failed", {"error": reload_msg, "backup": ts})
        return {"ok": False, "error": f"reload failed: {reload_msg}", "backup": ts, "rolled_back": True}

    state["last_apply"] = {"at": _now(), "backup": ts, "ok": True}
    state["last_reload"] = _now()
    await _save_state(opts, state)
    await _audit(opts, "apply_ok", {"backup": ts, "routes": preview.get("route_count")})
    return {
        "ok": True,
        "backup": ts,
        "tested": test_msg,
        "reloaded": reload_msg,
        "route_count": preview.get("route_count"),
        "last_reload": state["last_reload"],
    }


async def rollback_backup(backup_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}", backup_id or ""):
        return {"ok": False, "error": "Invalid backup id"}
    root = _backups_dir(opts) / backup_id
    if not root.is_dir():
        return {"ok": False, "error": "Backup not found"}
    await run_privileged(["rm", "-rf", str(_managed(opts) / "http.d")])
    await run_privileged(["rm", "-rf", str(_managed(opts) / "stream.d")])
    await run_privileged(["cp", "-a", str(root / "http.d"), str(_managed(opts) / "http.d")])
    await run_privileged(["cp", "-a", str(root / "stream.d"), str(_managed(opts) / "stream.d")])
    st = root / "state.json"
    if st.is_file():
        await run_privileged(["cp", "-a", str(st), str(_state_path(opts))])
    test_ok, test_msg = await _nginx_test()
    if not test_ok:
        return {"ok": False, "error": f"Rolled files but nginx -t failed: {test_msg}"}
    reload_ok, reload_msg = await _nginx_reload()
    await _audit(opts, "rollback", {"backup": backup_id, "ok": reload_ok})
    return {"ok": reload_ok, "tested": test_msg, "reloaded": reload_msg, "error": None if reload_ok else reload_msg}


async def list_backups(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    root = _backups_dir(opts)
    items = []
    if root.is_dir():
        for p in sorted(root.iterdir(), reverse=True):
            if p.is_dir():
                items.append({"id": p.name, "path": str(p)})
    return {"ok": True, "backups": items[:50]}


async def create_backup(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_root = _backups_dir(opts) / f"manual-{ts}"
    await _ensure_dirs(opts)
    await run_privileged(["mkdir", "-p", str(backup_root)])
    await run_privileged(["cp", "-a", str(_managed(opts)), str(backup_root / "lnxadmin")])
    await run_privileged(["cp", "-a", str(_data(opts)), str(backup_root / "data")])
    await _audit(opts, "backup_manual", {"id": backup_root.name})
    return {"ok": True, "backup": backup_root.name}


# ---- Templates & validation ----

def list_templates() -> dict[str, Any]:
    items = []
    for t in ROUTE_TEMPLATES:
        items.append(
            {
                "id": t["id"],
                "title": t["title"],
                "category": t.get("category") or "Other",
                "icon": t.get("icon") or "global",
                "summary": t.get("summary") or "",
                "hints": list(t.get("hints") or []),
                "required_overrides": list(t.get("required_overrides") or []),
                "defaults": dict(t.get("defaults") or {}),
                "proxy_type": (t.get("defaults") or {}).get("proxy_type"),
            }
        )
    categories = sorted({i["category"] for i in items})
    return {"ok": True, "templates": items, "categories": categories}


def get_template(template_id: str) -> dict[str, Any] | None:
    for t in ROUTE_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def _merge_template(template: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    body = dict(template.get("defaults") or {})
    ov = dict(overrides or {})
    # Drop empty strings so defaults can remain unless explicitly cleared where allowed
    for key, value in list(ov.items()):
        if value is None:
            ov.pop(key, None)
        elif isinstance(value, str) and value.strip() == "" and key not in ("domain", "aliases", "allow_ips", "deny_ips"):
            # keep explicit empty domain for TCP/UDP templates
            if key != "domain":
                ov.pop(key, None)
    body.update(ov)
    body.pop("template_id", None)
    body.pop("id", None)  # always create new from template unless caller re-adds
    return body


def _cycle_errors(routes: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for b in route.get("backends") or []:
        for r in routes:
            if r.get("id") == route.get("id"):
                continue
            if b["host"] == r.get("domain") and int(b["port"]) == int(r.get("frontend_port") or -1):
                errors.append(
                    {
                        "field": "backend_host",
                        "message": (
                            f"Possible proxy cycle: backend {b['host']}:{b['port']} "
                            f"points at route '{r.get('name')}'"
                        ),
                    }
                )
    return errors


def _template_placeholder_warnings(route: dict[str, Any], template: dict[str, Any] | None) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    domain = (route.get("domain") or "").lower()
    if domain.endswith(".example.com") or domain == "example.com":
        warnings.append({"field": "domain", "message": "Replace example.com with your real domain before applying"})
    name = route.get("name") or ""
    if template and name == (template.get("defaults") or {}).get("name"):
        # soft — only if domain still placeholder
        if domain.endswith(".example.com"):
            warnings.append({"field": "name", "message": "Consider a unique route name for this deployment"})
    if route.get("proxy_type") == "https_reverse" and not route.get("cert_id"):
        warnings.append({"field": "cert_id", "message": "HTTPS route needs a certificate before Apply will succeed"})
    if route.get("proxy_type") == "tls_passthrough":
        warnings.append(
            {
                "field": "proxy_type",
                "message": "TLS Passthrough: install and renew the certificate on the backend, not in Nginx",
            }
        )
    backend = (route.get("backends") or [{}])[0]
    host = str(backend.get("host") or "")
    if host.startswith("192.168.1.") and template and template["id"].startswith("ms_"):
        warnings.append({"field": "backend_host", "message": "Update backend_host to your real RDS / Windows server IP"})
    return warnings


async def validate_route(
    body: dict[str, Any],
    options: dict[str, Any] | None = None,
    *,
    template_id: str | None = None,
) -> dict[str, Any]:
    """Dry-run validation: normalize + conflicts + cycles + template warnings. Does not save."""
    opts = _opts(options)
    state = _load_state(opts)
    template = get_template(template_id) if template_id else None
    if template_id and not template:
        return {"ok": False, "errors": [{"field": "template_id", "message": f"Unknown template: {template_id}"}]}

    payload = _merge_template(template, body) if template else dict(body)
    rid = body.get("id")
    existing = next((r for r in state["routes"] if r.get("id") == rid), None) if rid else None

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    route, err = _normalize_route(payload, existing)
    if not route:
        errors.append({"field": "route", "message": err or "Invalid route"})
        return {"ok": False, "errors": errors, "warnings": warnings, "route": None}

    # HTTPS without cert is a hard error when apply requested; soft warning on validate
    conflict = _conflict_check(state["routes"], route)
    if conflict:
        errors.append({"field": "conflict", "message": conflict})
    errors.extend(_cycle_errors(state["routes"], route))

    if template:
        for field in template.get("required_overrides") or []:
            default_val = (template.get("defaults") or {}).get(field)
            current = route.get(field)
            if field == "backend_host":
                current = (route.get("backends") or [{}])[0].get("host")
            if field == "backend_port":
                current = (route.get("backends") or [{}])[0].get("port")
            if field == "allow_ips" and not route.get("allow_ips"):
                warnings.append({"field": "allow_ips", "message": "Recommended: set allow_ips for this template"})
                continue
            if field in ("domain", "name") and isinstance(current, str):
                if current == default_val or (isinstance(current, str) and current.endswith(".example.com")):
                    warnings.append({"field": field, "message": f"Update '{field}' from the template default"})
            elif field in ("backend_host",) and current == default_val:
                warnings.append({"field": field, "message": f"Update '{field}' from the template default"})

    warnings.extend(_template_placeholder_warnings(route, template))

    # Extra field checks
    if route.get("proxy_type") in ("http_reverse", "https_reverse", "static_http", "static_https", "tls_passthrough"):
        if not route.get("domain") and route.get("proxy_type") != "tcp":
            if route["proxy_type"] != "tcp":
                errors.append({"field": "domain", "message": "Domain is required for this proxy type"})

    if route.get("client_max_body_size") == "0":
        # nginx accepts 0 as unlimited — warn only
        warnings.append({"field": "client_max_body_size", "message": "0 means unlimited upload size"})

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "route": route,
        "template_id": template_id,
    }


async def create_from_template(
    template_id: str,
    overrides: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = get_template(template_id)
    if not template:
        return {"ok": False, "error": f"Unknown template: {template_id}", "errors": [{"field": "template_id", "message": "Unknown template"}]}
    body = _merge_template(template, overrides)
    # Force validation before save
    check = await validate_route(body, options, template_id=template_id)
    # Block save on hard errors; allow warnings
    if not check["ok"]:
        return {
            "ok": False,
            "error": "; ".join(e["message"] for e in check["errors"]) or "Validation failed",
            "errors": check["errors"],
            "warnings": check["warnings"],
            "route": check.get("route"),
        }
    # Strip id — new route
    save_body = dict(check["route"] or body)
    save_body.pop("id", None)
    save_body["apply"] = bool((overrides or {}).get("apply"))
    # Re-map backends into upsert shape
    if save_body.get("backends"):
        b0 = save_body["backends"][0]
        save_body.setdefault("backend_host", b0.get("host"))
        save_body.setdefault("backend_port", b0.get("port"))
    result = await upsert_route(save_body, options)
    result["warnings"] = check.get("warnings") or []
    result["template_id"] = template_id
    return result


# ---- Routes CRUD ----

async def list_routes(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    return {
        "ok": True,
        "routes": state["routes"],
        "proxy_types": PROXY_TYPES,
        "lb_methods": list(LB_METHODS),
        "templates": list_templates()["templates"],
    }


async def upsert_route(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    rid = body.get("id")
    existing = next((r for r in state["routes"] if r.get("id") == rid), None) if rid else None
    route, err = _normalize_route(body, existing)
    if not route:
        return {"ok": False, "error": err, "errors": [{"field": "route", "message": err or "Invalid route"}]}
    conflict = _conflict_check(state["routes"], route)
    if conflict:
        return {"ok": False, "error": conflict, "errors": [{"field": "conflict", "message": conflict}]}
    cycle = _cycle_errors(state["routes"], route)
    if cycle:
        return {"ok": False, "error": cycle[0]["message"], "errors": cycle}

    if existing:
        state["routes"] = [route if r.get("id") == route["id"] else r for r in state["routes"]]
    else:
        state["routes"].append(route)
    ok, err = await _save_state(opts, state)
    if not ok:
        return {"ok": False, "error": err}
    await _audit(opts, "route_upsert", {"id": route["id"], "name": route["name"]})
    apply_now = bool(body.get("apply"))
    result: dict[str, Any] = {"ok": True, "route": route}
    if apply_now:
        # Pre-check HTTPS cert
        if route.get("proxy_type") in ("https_reverse", "static_https") and not route.get("cert_id"):
            result["apply"] = {"ok": False, "error": "HTTPS route has no certificate assigned"}
        else:
            result["apply"] = await apply_config(opts)
    return result


async def delete_route(route_id: str, options: dict[str, Any] | None = None, apply: bool = False) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    before = len(state["routes"])
    state["routes"] = [r for r in state["routes"] if r.get("id") != route_id]
    if len(state["routes"]) == before:
        return {"ok": False, "error": "Route not found"}
    ok, err = await _save_state(opts, state)
    if not ok:
        return {"ok": False, "error": err}
    await _audit(opts, "route_delete", {"id": route_id})
    result: dict[str, Any] = {"ok": True}
    if apply:
        result["apply"] = await apply_config(opts)
    return result


# ---- Certificates ----

async def list_certificates(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    certs = _list_cert_meta(opts)
    # refresh days_left lightly from files
    refreshed = []
    for c in certs:
        fullchain, _ = _cert_paths(opts, c["id"])
        if fullchain.is_file():
            try:
                pem = fullchain.read_text(encoding="utf-8")
                info = await _parse_cert_pem(pem)
                if info.get("ok"):
                    c = {
                        **c,
                        "not_after": info.get("not_after"),
                        "days_left": info.get("days_left"),
                        "expired": info.get("expired"),
                        "sans": info.get("sans") or c.get("sans") or [],
                    }
            except OSError:
                pass
        refreshed.append(c)
    return {"ok": True, "certificates": refreshed}


async def upload_certificate(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    name = str(body.get("name") or "certificate").strip()
    if not NAME_RE.match(name):
        return {"ok": False, "error": "Invalid certificate name"}
    cert_pem = str(body.get("certificate_pem") or body.get("fullchain_pem") or "").strip()
    key_pem = str(body.get("private_key_pem") or "").strip()
    chain_pem = str(body.get("chain_pem") or "").strip()
    if not cert_pem or "BEGIN CERTIFICATE" not in cert_pem:
        return {"ok": False, "error": "certificate_pem required"}
    if not key_pem or "PRIVATE KEY" not in key_pem:
        return {"ok": False, "error": "private_key_pem required"}
    # never log key
    ok_match, err = await _verify_cert_key(cert_pem, key_pem)
    if not ok_match:
        return {"ok": False, "error": err}
    info = await _parse_cert_pem(cert_pem)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "invalid certificate"}
    fullchain = cert_pem if "BEGIN CERTIFICATE" in cert_pem else cert_pem
    if chain_pem and chain_pem not in fullchain:
        fullchain = fullchain.rstrip() + "\n" + chain_pem.strip() + "\n"

    await _ensure_dirs(opts)
    cert_id = _new_id("c")
    files_dir = _certs_files_dir(opts) / cert_id
    await run_privileged(["mkdir", "-p", str(files_dir)])
    ok, err = await _write_file_priv(str(files_dir / "fullchain.pem"), fullchain + ("\n" if not fullchain.endswith("\n") else ""), "644")
    if not ok:
        return {"ok": False, "error": err}
    ok, err = await _write_file_priv(str(files_dir / "privkey.pem"), key_pem + ("\n" if not key_pem.endswith("\n") else ""), "600")
    if not ok:
        return {"ok": False, "error": err}

    history = []
    meta = {
        "id": cert_id,
        "name": name,
        "source": "upload",
        "subject": info.get("subject"),
        "issuer": info.get("issuer"),
        "not_before": info.get("not_before"),
        "not_after": info.get("not_after"),
        "sans": info.get("sans") or [],
        "days_left": info.get("days_left"),
        "created_at": _now(),
        "history": history,
    }
    await _write_file_priv(str(_certs_meta_dir(opts) / f"{cert_id}.json"), json.dumps(meta, indent=2), "600")
    await _audit(opts, "cert_upload", {"id": cert_id, "name": name, "sans": meta["sans"]})
    return {"ok": True, "certificate": meta}


async def import_pfx(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    name = str(body.get("name") or "pfx").strip()
    pfx_b64 = str(body.get("pfx_base64") or "").strip()
    password = str(body.get("password") or "")
    if not pfx_b64:
        return {"ok": False, "error": "pfx_base64 required"}
    import base64
    import tempfile

    try:
        raw = base64.b64decode(pfx_b64)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "Invalid base64 PFX data"}
    await _ensure_dirs(opts)
    with tempfile.TemporaryDirectory(prefix="lnxadmin-pfx-") as td:
        pfx_path = Path(td) / "in.p12"
        cert_path = Path(td) / "cert.pem"
        key_path = Path(td) / "key.pem"
        pfx_path.write_bytes(raw)
        passin = f"pass:{password}"
        code, _, err = await _openssl(
            "pkcs12", "-in", str(pfx_path), "-nodes", "-passin", passin,
            "-nokeys", "-out", str(cert_path),
        )
        if code != 0:
            return {"ok": False, "error": err or "PFX certificate extract failed"}
        code, _, err = await _openssl(
            "pkcs12", "-in", str(pfx_path), "-nodes", "-passin", passin,
            "-nocerts", "-out", str(key_path),
        )
        if code != 0:
            return {"ok": False, "error": err or "PFX key extract failed"}
        cert_pem = cert_path.read_text(encoding="utf-8")
        key_pem = key_path.read_text(encoding="utf-8")
    return await upload_certificate(
        {"name": name, "certificate_pem": cert_pem, "private_key_pem": key_pem},
        opts,
    )


async def generate_key_csr(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    cn = str(body.get("cn") or body.get("domain") or "").strip().lower()
    sans = body.get("sans") or []
    if not _valid_domain(cn):
        return {"ok": False, "error": "Invalid CN/domain"}
    san_list = [cn] + [str(s).strip().lower() for s in sans if str(s).strip()]
    for s in san_list:
        if not _valid_domain(s):
            return {"ok": False, "error": f"Invalid SAN: {s}"}
    await _ensure_dirs(opts)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="lnxadmin-csr-") as td:
        key_path = Path(td) / "key.pem"
        csr_path = Path(td) / "req.csr"
        conf_path = Path(td) / "openssl.cnf"
        alt = ",".join(f"DNS:{s}" for s in san_list)
        conf_path.write_text(
            f"[req]\ndistinguished_name=req_distinguished_name\nreq_extensions=v3_req\n"
            f"prompt=no\n[req_distinguished_name]\nCN={cn}\n"
            f"[v3_req]\nsubjectAltName={alt}\n",
            encoding="utf-8",
        )
        code, _, err = await _openssl("genrsa", "-out", str(key_path), "2048")
        if code != 0:
            return {"ok": False, "error": err or "key generation failed"}
        code, _, err = await _openssl(
            "req", "-new", "-key", str(key_path), "-out", str(csr_path), "-config", str(conf_path),
        )
        if code != 0:
            return {"ok": False, "error": err or "CSR generation failed"}
        key_pem = key_path.read_text(encoding="utf-8")
        csr_pem = csr_path.read_text(encoding="utf-8")

    # store key pending cert
    cert_id = _new_id("c")
    files_dir = _certs_files_dir(opts) / cert_id
    await run_privileged(["mkdir", "-p", str(files_dir)])
    await _write_file_priv(str(files_dir / "privkey.pem"), key_pem, "600")
    await _write_file_priv(str(files_dir / "request.csr"), csr_pem, "644")
    meta = {
        "id": cert_id,
        "name": str(body.get("name") or cn),
        "source": "csr",
        "cn": cn,
        "sans": san_list,
        "has_certificate": False,
        "created_at": _now(),
        "history": [],
    }
    await _write_file_priv(str(_certs_meta_dir(opts) / f"{cert_id}.json"), json.dumps(meta, indent=2), "600")
    await _audit(opts, "cert_csr", {"id": cert_id, "cn": cn})
    return {"ok": True, "certificate": meta, "csr_pem": csr_pem}


async def delete_certificate(cert_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    in_use = [r["name"] for r in state["routes"] if r.get("cert_id") == cert_id]
    if in_use:
        return {"ok": False, "error": f"Certificate in use by routes: {', '.join(in_use)}"}
    meta_path = _certs_meta_dir(opts) / f"{cert_id}.json"
    files_dir = _certs_files_dir(opts) / cert_id
    if not meta_path.is_file():
        return {"ok": False, "error": "Certificate not found"}
    # archive history entry then delete
    await run_privileged(["rm", "-rf", str(files_dir)])
    await run_privileged(["rm", "-f", str(meta_path)])
    await _audit(opts, "cert_delete", {"id": cert_id})
    return {"ok": True}


# ---- ACME / Let's Encrypt ----

def _acme_server_args(opts: dict[str, Any], state: dict[str, Any]) -> list[str]:
    env = (state.get("acme") or {}).get("environment") or opts.get("acme_environment") or "production"
    custom = (state.get("acme") or {}).get("directory_url") or opts.get("acme_directory_url") or ""
    if env == "staging":
        return ["--staging"]
    if env == "custom" and custom:
        return ["--server", custom]
    return []


async def _append_acme_log(opts: dict[str, Any], entry: dict[str, Any]) -> None:
    path = _acme_log_path(opts)
    await _ensure_dirs(opts)
    line = json.dumps({**entry, "ts": _now()}, ensure_ascii=False)
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        await run_privileged(["bash", "-c", f"printf '%s\\n' {json.dumps(line)} >> {path}"])


async def acme_issue(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    if not tools_status()["certbot"]:
        return {"ok": False, "error": "certbot is not installed (use Install tools)"}
    domains = body.get("domains") or []
    if isinstance(domains, str):
        domains = [domains]
    domains = [str(d).strip().lower() for d in domains if str(d).strip()]
    if not domains or not all(_valid_domain(d) for d in domains):
        return {"ok": False, "error": "Valid domains required"}
    challenge = str(body.get("challenge") or "http-01")
    if challenge not in ("http-01", "dns-01"):
        return {"ok": False, "error": "challenge must be http-01 or dns-01"}
    state = _load_state(opts)
    email = str(body.get("email") or (state.get("acme") or {}).get("email") or opts.get("acme_email") or "").strip()
    if not email or "@" not in email:
        return {"ok": False, "error": "ACME email required (set in module settings or request body)"}

    await _ensure_dirs(opts)
    webroot = _acme_webroot(opts)
    args = [
        "certbot", "certonly", "--non-interactive", "--agree-tos",
        "-m", email, "--cert-name", domains[0].replace("*.", "wildcard-"),
    ]
    args.extend(_acme_server_args(opts, state))
    if challenge == "http-01":
        if any(d.startswith("*.") for d in domains):
            return {"ok": False, "error": "Wildcard certificates require DNS-01"}
        # Deploy public :80 ACME vhost before certbot writes challenge files
        ready = await _ensure_acme_http(opts, domains)
        if not ready.get("ok") and not body.get("skip_public_check"):
            await _append_acme_log(opts, {"action": "issue", "domains": domains, "ok": False, "log": ready.get("error")})
            return {
                "ok": False,
                "error": ready.get("error") or "Failed to prepare HTTP-01 ACME endpoint",
                "probes": ready.get("probes"),
                "hint": ready.get("hint"),
                "suggested_challenge": "dns-01",
            }
        if not ready.get("ok") and body.get("skip_public_check"):
            # Still require local ACME path; ignore public ownership check
            local_ready = await _ensure_acme_http_local_only(opts, domains)
            if not local_ready.get("ok"):
                return {"ok": False, "error": local_ready.get("error") or "Local ACME path failed"}
        args.extend(["--webroot", "-w", webroot])
    else:
        provider_id = str(body.get("dns_provider_id") or "").strip()
        provider = next((p for p in state.get("dns_providers") or [] if p.get("id") == provider_id), None)
        # Manual DNS-01 (any registrar: AsiaInfo, etc.) when no API provider selected
        if not provider_id or (provider and provider.get("type") == "manual") or body.get("manual_dns"):
            return await _acme_issue_manual_dns(
                opts,
                state,
                domains=domains,
                email=email,
                dry_run=bool(body.get("dry_run")),
            )
        if not provider:
            return {
                "ok": False,
                "error": "Select DNS-01 Manual (no API) or add a DNS provider. Your DNS appears to be at a registrar without Cloudflare.",
                "suggested_challenge": "dns-01",
            }
        if provider.get("type") == "cloudflare":
            token = provider.get("token") or ""
            creds = _data(opts) / "acme" / f"cloudflare-{provider_id}.ini"
            await _write_file_priv(str(creds), f"dns_cloudflare_api_token = {token}\n", "600")
            args.extend(["--dns-cloudflare", "--dns-cloudflare-credentials", str(creds)])
        else:
            return {"ok": False, "error": f"DNS provider type '{provider.get('type')}' not wired — use DNS-01 Manual"}

    for d in domains:
        args.extend(["-d", d])

    if body.get("dry_run"):
        args.append("--dry-run")

    code, out, err = await run_privileged(args, timeout=300.0)
    log = ((out or "") + "\n" + (err or "")).strip()
    safe_log = log.replace(email, "<email>")
    await _append_acme_log(opts, {"action": "issue", "domains": domains, "ok": code == 0, "log": safe_log[-4000:]})
    if code != 0:
        hint = _friendly_acme_error(safe_log)
        return {
            "ok": False,
            "error": hint or (err or out or "certbot failed"),
            "log": safe_log[-4000:],
            "hint": hint or None,
        }

    if body.get("dry_run"):
        return {"ok": True, "dry_run": True, "log": safe_log[-4000:]}

    return await _import_letsencrypt_cert(opts, domains, safe_log[-2000:])


def _manual_dns_dir(opts: dict[str, Any]) -> Path:
    return _data(opts) / "acme" / "manual"


async def _ensure_acme_http_local_only(opts: dict[str, Any], domains: list[str]) -> dict[str, Any]:
    """Prepare ACME vhost and verify only on 127.0.0.1 (skip public ownership check)."""
    # Reuse ensure but strip public failure: call internal pieces
    result = await _ensure_acme_http(opts, domains)
    if result.get("ok"):
        return result
    probes = result.get("probes") or []
    if any(p.get("local_ok") for p in probes):
        return {"ok": True, "probes": probes, "skipped_public_check": True}
    return result


async def _write_manual_dns_hooks(opts: dict[str, Any]) -> tuple[Path, Path]:
    root = _manual_dns_dir(opts)
    await run_privileged(["mkdir", "-p", str(root)])
    auth = root / "auth-hook.py"
    cleanup = root / "cleanup-hook.py"
    auth_py = r'''#!/usr/bin/env python3
import json, os, time
from pathlib import Path
root = Path(os.environ["LNXADMIN_ACME_MANUAL"])
root.mkdir(parents=True, exist_ok=True)
domain = os.environ.get("CERTBOT_DOMAIN", "")
validation = os.environ.get("CERTBOT_VALIDATION", "")
item = {
    "domain": domain,
    "validation": validation,
    "record_name": f"_acme-challenge.{domain}",
    "record_type": "TXT",
    "record_value": validation,
    "status": "waiting_for_txt",
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
(root / "pending.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
status = {"state": "waiting_for_txt", "pending": item, "updated_at": item["ts"]}
(root / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
confirm = root / "confirm.flag"
# Wait up to 20 minutes for operator to publish TXT and confirm in UI
for _ in range(240):
    if confirm.is_file():
        try:
            confirm.unlink()
        except OSError:
            pass
        status = {"state": "validating", "pending": item, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (root / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        # brief DNS settle
        time.sleep(10)
        raise SystemExit(0)
    time.sleep(5)
status = {"state": "timeout", "pending": item, "error": "Timed out waiting for TXT confirmation", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
(root / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
raise SystemExit(1)
'''
    cleanup_py = r'''#!/usr/bin/env python3
import json, os, time
from pathlib import Path
root = Path(os.environ["LNXADMIN_ACME_MANUAL"])
pending = root / "pending.json"
if pending.is_file():
    try:
        pending.unlink()
    except OSError:
        pass
status = {"state": "cleanup", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
(root / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
raise SystemExit(0)
'''
    auth.write_text(auth_py, encoding="utf-8")
    cleanup.write_text(cleanup_py, encoding="utf-8")
    auth.chmod(0o755)
    cleanup.chmod(0o755)
    return auth, cleanup


async def _read_priv_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        code, out, err = await run_privileged(["cat", str(path)], timeout=10.0)
        if code == 0 and out:
            return out
        raise OSError(err or f"cannot read {path}") from None


async def _import_letsencrypt_cert(opts: dict[str, Any], domains: list[str], log_tail: str = "") -> dict[str, Any]:
    candidates = [
        Path("/etc/letsencrypt/live") / domains[0],
        Path("/etc/letsencrypt/live") / domains[0].replace("*.", "wildcard-"),
        Path("/etc/letsencrypt/live") / domains[0].replace("*.", ""),
    ]
    live = next((p for p in candidates if (p / "fullchain.pem").is_file()), None)
    if not live:
        return {"ok": True, "imported": False, "warning": "certbot ok but live path not found", "log": log_tail}
    try:
        cert_pem = await _read_priv_text(live / "fullchain.pem")
        key_pem = await _read_priv_text(live / "privkey.pem")
    except OSError as exc:
        return {"ok": True, "imported": False, "warning": f"cannot read live cert: {exc}", "log": log_tail}
    imported = await upload_certificate(
        {"name": f"le-{domains[0]}", "certificate_pem": cert_pem, "private_key_pem": key_pem},
        opts,
    )
    if imported.get("ok") and imported.get("certificate"):
        cid = imported["certificate"]["id"]
        meta = _get_cert_meta(opts, cid) or {}
        meta["source"] = "letsencrypt"
        meta["acme_domains"] = domains
        await _write_file_priv(str(_certs_meta_dir(opts) / f"{cid}.json"), json.dumps(meta, indent=2), "600")
        imported["certificate"] = {k: v for k, v in meta.items() if k != "private_key_pem"}
    return {"ok": True, "import": imported, "log": log_tail}


async def _acme_issue_manual_dns(
    opts: dict[str, Any],
    state: dict[str, Any],
    *,
    domains: list[str],
    email: str,
    dry_run: bool,
) -> dict[str, Any]:
    """DNS-01 via certbot --manual hooks: UI shows TXT, operator confirms."""
    import asyncio

    await _ensure_dirs(opts)
    auth, cleanup = await _write_manual_dns_hooks(opts)
    manual_dir = _manual_dns_dir(opts)
    # reset flags
    for name in ("confirm.flag", "pending.json", "result.json"):
        p = manual_dir / name
        if p.is_file():
            p.unlink(missing_ok=True)
    (manual_dir / "status.json").write_text(
        json.dumps({"state": "starting", "domains": domains, "updated_at": _now()}, indent=2),
        encoding="utf-8",
    )

    args = [
        "certbot", "certonly", "--agree-tos", "-m", email,
        "--cert-name", domains[0].replace("*.", "wildcard-"),
        "--manual", "--preferred-challenges", "dns",
        "--manual-auth-hook", str(auth),
        "--manual-cleanup-hook", str(cleanup),
        # required for non-interactive manual mode with hooks
        "--manual-public-ip-logging-ok",
    ]
    # certbot still wants non-interactive when hooks handle everything
    args.append("--non-interactive")
    args.extend(_acme_server_args(opts, state))
    if dry_run:
        args.append("--dry-run")
    for d in domains:
        args.extend(["-d", d])

    env = {
        **dict(__import__("os").environ),
        "LNXADMIN_ACME_MANUAL": str(manual_dir),
    }

    async def _runner() -> None:
        try:
            # Ensure /etc/letsencrypt is writable (root via sudo -n)
            cmd = list(args)
            if __import__("os").geteuid() != 0:
                sudo = shutil.which("sudo")
                if sudo:
                    cmd = [sudo, "-n", "env", f"LNXADMIN_ACME_MANUAL={manual_dir}", *args]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1500.0)
            code = proc.returncode or 0
            log = ((stdout or b"").decode("utf-8", "replace") + "\n" + (stderr or b"").decode("utf-8", "replace")).strip()
            safe_log = log.replace(email, "<email>")
            await _append_acme_log(opts, {"action": "issue_manual_dns", "domains": domains, "ok": code == 0, "log": safe_log[-4000:]})
            if code == 0 and not dry_run:
                imported = await _import_letsencrypt_cert(opts, domains, safe_log[-2000:])
                result = {"ok": True, "state": "done", **imported, "log": safe_log[-2000:]}
            elif code == 0:
                result = {"ok": True, "state": "done", "dry_run": True, "log": safe_log[-2000:]}
            else:
                hint = _friendly_acme_error(safe_log)
                result = {
                    "ok": False,
                    "state": "failed",
                    "error": hint or "Manual DNS-01 failed",
                    "log": safe_log[-4000:],
                }
            (manual_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            (manual_dir / "status.json").write_text(
                json.dumps({**result, "updated_at": _now()}, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "state": "failed", "error": str(exc)}
            (manual_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            (manual_dir / "status.json").write_text(json.dumps({**result, "updated_at": _now()}, indent=2), encoding="utf-8")

    asyncio.create_task(_runner())
    # Wait until pending TXT appears (auth hook started)
    pending = None
    for _ in range(60):
        p = manual_dir / "pending.json"
        if p.is_file():
            pending = _load_json(p)
            break
        st = _load_json(manual_dir / "status.json") or {}
        if st.get("state") in {"failed", "timeout", "done"}:
            return {"ok": False, "error": st.get("error") or "Manual DNS-01 failed early", "status": st}
        await asyncio.sleep(0.5)

    if not pending:
        return {
            "ok": False,
            "error": "Certbot did not start DNS challenge in time — check certbot/manual hooks",
        }

    return {
        "ok": True,
        "pending": True,
        "challenge": "dns-01",
        "mode": "manual",
        "message": "Add the TXT record at your DNS registrar (AsiaInfo / domain.kg), wait 1–2 minutes, then Confirm.",
        "txt": {
            "name": pending.get("record_name"),
            "type": "TXT",
            "value": pending.get("record_value") or pending.get("validation"),
            "domain": pending.get("domain"),
        },
        "domains": domains,
    }


async def acme_manual_dns_status(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    root = _manual_dns_dir(opts)
    status = _load_json(root / "status.json") or {}
    pending = _load_json(root / "pending.json")
    result = _load_json(root / "result.json")
    out: dict[str, Any] = {"ok": True, "status": status.get("state") or "idle", "raw": status}
    if pending:
        out["txt"] = {
            "name": pending.get("record_name"),
            "type": "TXT",
            "value": pending.get("record_value") or pending.get("validation"),
            "domain": pending.get("domain"),
        }
        out["pending"] = True
    if result:
        out["result"] = result
        out["pending"] = not bool(result.get("ok")) and status.get("state") not in {"done", "failed", "timeout"}
        if result.get("ok") and status.get("state") == "done":
            out["pending"] = False
    return out


async def acme_manual_dns_confirm(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    root = _manual_dns_dir(opts)
    pending = _load_json(root / "pending.json")
    if not pending:
        return {"ok": False, "error": "No pending DNS challenge"}
    # Optional: verify TXT visible before confirming
    record = pending.get("record_name") or f"_acme-challenge.{pending.get('domain')}"
    code, out, err = await run_cmd(["dig", "+short", "TXT", record], timeout=15.0)
    seen = (out or "").replace('"', "")
    expected = pending.get("record_value") or pending.get("validation") or ""
    dns_ok = bool(expected) and expected in seen
    flag = root / "confirm.flag"
    flag.write_text("1\n", encoding="utf-8")
    await _audit(opts, "acme_dns_confirm", {"record": record, "dns_seen": dns_ok})
    return {
        "ok": True,
        "confirmed": True,
        "dns_visible": dns_ok,
        "dns_lookup": (out or err or "").strip()[:500],
        "message": (
            "TXT seen in DNS — validating with Let's Encrypt…"
            if dns_ok
            else "Confirm sent. TXT not visible yet via dig — validation may still succeed after propagation."
        ),
    }


async def acme_renew(body: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    body = body or {}
    if not tools_status()["certbot"]:
        return {"ok": False, "error": "certbot is not installed"}
    args = ["certbot", "renew", "--non-interactive"]
    if body.get("dry_run") or body.get("test"):
        args.append("--dry-run")
    if body.get("force"):
        args.append("--force-renewal")
    code, out, err = await run_privileged(args, timeout=600.0)
    log = ((out or "") + "\n" + (err or "")).strip()
    await _append_acme_log(opts, {"action": "renew", "ok": code == 0, "log": log[-4000:]})
    if code != 0:
        return {"ok": False, "error": err or out or "renew failed", "log": log[-4000:]}
    # After renew: test + reload
    test_ok, test_msg = await _nginx_test()
    if not test_ok:
        return {"ok": False, "error": f"renewed but nginx -t failed: {test_msg}", "log": log[-2000:]}
    reload_ok, reload_msg = await _nginx_reload()
    return {"ok": reload_ok, "tested": test_msg, "reloaded": reload_msg, "log": log[-2000:]}


async def acme_logs(options: dict[str, Any] | None = None, limit: int = 50) -> dict[str, Any]:
    opts = _opts(options)
    path = _acme_log_path(opts)
    lines: list[dict[str, Any]] = []
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    lines.append({"raw": line})
        except OSError:
            pass
    return {"ok": True, "entries": list(reversed(lines))}


async def upsert_dns_provider(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    ptype = str(body.get("type") or "").strip()
    if ptype not in ("cloudflare", "route53", "digitalocean", "custom", "manual"):
        return {"ok": False, "error": "Unsupported DNS provider type"}
    name = str(body.get("name") or ptype).strip()
    token = str(body.get("token") or body.get("api_token") or "").strip()
    if ptype != "custom" and not token and not body.get("id"):
        return {"ok": False, "error": "API token required"}
    pid = body.get("id") or _new_id("dns")
    existing = next((p for p in state["dns_providers"] if p.get("id") == pid), None)
    provider = {
        "id": pid,
        "name": name,
        "type": ptype,
        "token": token or (existing or {}).get("token") or "",
        "updated_at": _now(),
        "created_at": (existing or {}).get("created_at") or _now(),
    }
    if existing:
        state["dns_providers"] = [provider if p.get("id") == pid else p for p in state["dns_providers"]]
    else:
        state["dns_providers"].append(provider)
    ok, err = await _save_state(opts, state)
    if not ok:
        return {"ok": False, "error": err}
    public = {**provider, "token": ("***" if provider.get("token") else "")}
    await _audit(opts, "dns_provider_upsert", {"id": pid, "type": ptype})
    return {"ok": True, "provider": public}


async def list_dns_providers(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    providers = []
    for p in state.get("dns_providers") or []:
        providers.append({**p, "token": "***" if p.get("token") else ""})
    return {"ok": True, "providers": providers}


async def delete_dns_provider(provider_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    state["dns_providers"] = [p for p in state["dns_providers"] if p.get("id") != provider_id]
    ok, err = await _save_state(opts, state)
    await _audit(opts, "dns_provider_delete", {"id": provider_id})
    return {"ok": ok, "error": err or None}


async def test_dns_provider(provider_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    provider = next((p for p in state.get("dns_providers") or [] if p.get("id") == provider_id), None)
    if not provider:
        return {"ok": False, "error": "Provider not found"}
    if provider.get("type") == "cloudflare":
        code, out, err = await run_cmd(
            [
                "curl", "-fsS", "-H", f"Authorization: Bearer {provider.get('token')}",
                "-H", "Content-Type: application/json",
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
            ],
            timeout=15.0,
        )
        if code != 0:
            return {"ok": False, "error": err or out or "Cloudflare API request failed"}
        try:
            data = json.loads(out)
            return {"ok": bool(data.get("success")), "response": {"success": data.get("success"), "status": (data.get("result") or {}).get("status")}}
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid Cloudflare response"}
    return {"ok": True, "message": f"Provider type {provider.get('type')} stored; live API test not implemented"}


async def update_acme_settings(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    acme = dict(state.get("acme") or {})
    if "email" in body:
        acme["email"] = str(body.get("email") or "").strip()
    if "environment" in body:
        env = str(body.get("environment") or "production")
        if env not in ACME_ENVIRONMENTS:
            return {"ok": False, "error": "Invalid ACME environment"}
        acme["environment"] = env
    if "directory_url" in body:
        url = str(body.get("directory_url") or "").strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return {"ok": False, "error": "Invalid ACME directory URL"}
        acme["directory_url"] = url
    if "auto_renew" in body:
        acme["auto_renew"] = bool(body.get("auto_renew"))
    if "renew_days_before" in body:
        try:
            acme["renew_days_before"] = max(1, min(int(body.get("renew_days_before") or 30), 90))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid renew_days_before"}
    state["acme"] = acme
    ok, err = await _save_state(opts, state)
    return {"ok": ok, "acme": acme, "error": err or None}


async def read_logs(kind: str = "error", options: dict[str, Any] | None = None, lines: int | None = None) -> dict[str, Any]:
    opts = _opts(options)
    n = int(lines or opts.get("log_lines") or 120)
    n = max(10, min(n, 2000))
    mapping = {
        "error": "/var/log/nginx/error.log",
        "access": "/var/log/nginx/access.log",
        "stream": "/var/log/nginx/lnxadmin-stream.access.log",
        "app": str(_audit_log_path(opts)),
    }
    path = mapping.get(kind) or mapping["error"]
    # Prefer journalctl for nginx unit when file missing
    if not Path(path).is_file() and kind in ("error", "access"):
        code, out, err = await run_cmd(
            ["journalctl", "-u", "nginx", "-n", str(n), "--no-pager"],
            timeout=10.0,
        )
        return {"ok": code == 0, "kind": kind, "path": "journalctl:nginx", "content": out or err or ""}
    code, out, err = await run_privileged(["tail", "-n", str(n), path], timeout=10.0)
    if code != 0:
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            return {"ok": True, "kind": kind, "path": path, "content": "\n".join(content)}
        except OSError as exc:
            return {"ok": False, "error": err or str(exc), "kind": kind, "path": path}
    return {"ok": True, "kind": kind, "path": path, "content": out}


async def install_tools(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    if not opts["allow_install"]:
        return {"ok": False, "error": "Package install is disabled in module settings"}
    tools = tools_status()
    if tools["nginx"] and tools["openssl"]:
        # still try certbot if missing
        need_certbot = not tools["certbot"]
        if not need_certbot:
            return {"ok": True, "already": True, "tools": tools}

    pm = tools["pkg_manager"]
    if not pm:
        return {"ok": False, "error": "No supported package manager found (apt/dnf/yum/apk/pacman/zypper)"}

    if pm == "apt-get":
        cmds = [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "nginx", "openssl", "certbot", "python3-certbot-nginx", "libnginx-mod-stream", "curl"],
        ]
    elif pm == "dnf":
        cmds = [["dnf", "install", "-y", "nginx", "openssl", "certbot", "curl"]]
    elif pm == "yum":
        cmds = [["yum", "install", "-y", "nginx", "openssl", "certbot", "curl"]]
    elif pm == "apk":
        cmds = [["apk", "add", "--no-cache", "nginx", "openssl", "certbot", "curl"]]
    elif pm == "pacman":
        cmds = [["pacman", "-Sy", "--noconfirm", "nginx", "openssl", "certbot", "curl"]]
    elif pm == "zypper":
        cmds = [["zypper", "--non-interactive", "install", "nginx", "openssl", "certbot", "curl"]]
    else:
        return {"ok": False, "error": f"Unsupported package manager: {pm}"}

    logs: list[str] = []
    for cmd in cmds:
        code, out, err = await run_privileged(cmd, timeout=300.0)
        logs.append(f"$ {' '.join(cmd)}\n{(out or '')}{(err or '')}".strip())
        if code != 0 and ("install" in cmd or cmd[0] in {"dnf", "yum", "apk", "pacman", "zypper"}):
            return {"ok": False, "error": err or out or "install failed", "log": "\n\n".join(logs)[-8000:]}

    # Enable and start nginx
    await run_privileged(["systemctl", "enable", "nginx"], timeout=30.0)
    await run_privileged(["systemctl", "start", "nginx"], timeout=30.0)
    await _ensure_dirs(opts)
    await _ensure_nginx_includes(opts)

    tools = tools_status()
    ok = bool(tools["nginx"] and tools["openssl"])
    await _audit(opts, "install_tools", {"ok": ok})
    return {
        "ok": ok,
        "tools": tools,
        "log": "\n\n".join(logs)[-8000:],
        "error": None if ok else "nginx/openssl still missing after install",
    }


async def service_action(action: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    if action not in ("start", "stop", "reload", "restart"):
        return {"ok": False, "error": "Invalid action"}
    if action == "reload":
        ok, msg = await _nginx_reload()
        if ok:
            state = _load_state(opts)
            state["last_reload"] = _now()
            await _save_state(opts, state)
        return {"ok": ok, "message": msg}
    code, out, err = await run_privileged(["systemctl", action, "nginx"], timeout=30.0)
    await _audit(opts, f"service_{action}", {"ok": code == 0})
    return {"ok": code == 0, "message": (out or err or "").strip(), "error": None if code == 0 else (err or out)}


async def probe_backends(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    state = _load_state(opts)
    results = []
    for r in state["routes"]:
        if not r.get("enabled", True):
            continue
        for b in r.get("backends") or []:
            host = b["host"]
            if host.startswith("docker:"):
                host = host[7:]
            port = int(b["port"])
            # TCP connect probe
            code, out, err = await run_cmd(
                ["bash", "-c", f"timeout 2 bash -c 'echo > /dev/tcp/{host}/{port}' 2>/dev/null"],
                timeout=4.0,
            )
            # /dev/tcp may fail in some shells — fallback to nc/python
            if code != 0:
                code2, _, _ = await run_cmd(
                    ["python3", "-c", f"import socket;s=socket.create_connection(('{host}',{port}),2);s.close()"],
                    timeout=5.0,
                )
                ok = code2 == 0
            else:
                ok = True
            results.append({
                "route_id": r["id"],
                "route_name": r.get("name"),
                "host": host,
                "port": port,
                "ok": ok,
            })
    return {"ok": True, "backends": results}


async def collect_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    installed = bool(tools["nginx"])
    state = _load_state(opts) if installed or _state_path(opts).is_file() else _default_state()
    routes = state.get("routes") or []
    enabled_routes = [r for r in routes if r.get("enabled", True)]
    certs = _list_cert_meta(opts) if installed or _certs_meta_dir(opts).is_dir() else []
    expiring = []
    for c in certs:
        days = c.get("days_left")
        if days is not None and days <= int((state.get("acme") or {}).get("renew_days_before") or opts["renew_days_before"]):
            expiring.append({"id": c["id"], "name": c.get("name"), "days_left": days, "not_after": c.get("not_after")})

    status = await _service_status() if installed else {"active": False, "state": "not-installed"}
    version = await _nginx_version() if installed else ""
    stub = await _stub_status() if installed and status.get("active") else {"available": False}
    backends = (await probe_backends(opts))["backends"] if installed and enabled_routes else []
    backends_ok = sum(1 for b in backends if b.get("ok"))
    backends_bad = sum(1 for b in backends if not b.get("ok"))

    by_type: dict[str, int] = {}
    for r in enabled_routes:
        by_type[r.get("proxy_type") or "unknown"] = by_type.get(r.get("proxy_type") or "unknown", 0) + 1

    return {
        "available": True,
        "tools": tools,
        "installed": installed,
        "version": version,
        "status": status,
        "stub_status": stub,
        "routes": routes,
        "route_count": len(routes),
        "routes_enabled": len(enabled_routes),
        "routes_by_type": by_type,
        "certificates": certs,
        "certificate_count": len(certs),
        "certs_expiring": expiring,
        "backends": backends,
        "backends_ok": backends_ok,
        "backends_down": backends_bad,
        "last_apply": state.get("last_apply"),
        "last_reload": state.get("last_reload"),
        "acme": {k: v for k, v in (state.get("acme") or {}).items()},
        "dns_providers": [
            {**p, "token": "***" if p.get("token") else ""}
            for p in (state.get("dns_providers") or [])
        ],
        "proxy_types": PROXY_TYPES,
        "lb_methods": list(LB_METHODS),
        "templates": list_templates()["templates"],
        "template_categories": list_templates()["categories"],
        "managed_dir": opts["managed_dir"],
        "data_dir": opts["data_dir"],
        "http_include": opts["http_include"],
    }


async def prometheus_metrics(options: dict[str, Any] | None = None) -> str:
    data = await collect_overview(options)
    lines = [
        "# HELP lnxadmin_nginx_up Nginx service active",
        "# TYPE lnxadmin_nginx_up gauge",
        f"lnxadmin_nginx_up {1 if data.get('status', {}).get('active') else 0}",
        "# HELP lnxadmin_nginx_routes_enabled Enabled proxy routes",
        "# TYPE lnxadmin_nginx_routes_enabled gauge",
        f"lnxadmin_nginx_routes_enabled {data.get('routes_enabled') or 0}",
        "# HELP lnxadmin_nginx_backends_up Healthy backends",
        "# TYPE lnxadmin_nginx_backends_up gauge",
        f"lnxadmin_nginx_backends_up {data.get('backends_ok') or 0}",
        "# HELP lnxadmin_nginx_backends_down Unhealthy backends",
        "# TYPE lnxadmin_nginx_backends_down gauge",
        f"lnxadmin_nginx_backends_down {data.get('backends_down') or 0}",
        "# HELP lnxadmin_nginx_certs_expiring Certificates near expiry",
        "# TYPE lnxadmin_nginx_certs_expiring gauge",
        f"lnxadmin_nginx_certs_expiring {len(data.get('certs_expiring') or [])}",
    ]
    stub = data.get("stub_status") or {}
    if stub.get("available"):
        lines.extend(
            [
                "# HELP lnxadmin_nginx_connections Active connections",
                "# TYPE lnxadmin_nginx_connections gauge",
                f"lnxadmin_nginx_connections {stub.get('active_connections') or 0}",
                "# HELP lnxadmin_nginx_requests_total Handled requests",
                "# TYPE lnxadmin_nginx_requests_total counter",
                f"lnxadmin_nginx_requests_total {stub.get('requests') or 0}",
            ]
        )
    return "\n".join(lines) + "\n"
