"""WireGuard VPN server management: install tools, interface, peers, client configs."""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from app.collectors._exec import run_cmd, run_privileged

DEFAULT_DATA_DIR = "/var/lib/lnxadmin/wireguard"
DEFAULT_INTERFACE = "wg0"
DEFAULT_ADDRESS = "10.66.0.1/24"
DEFAULT_LISTEN_PORT = 51820
MANAGED_MARKER = "# managed-by: lnxadmin-wireguard"

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,31}$")
IFACE_RE = re.compile(r"^[a-zA-Z0-9_]{1,15}$")

ROUTE_PRESETS: dict[str, dict[str, Any]] = {
    "vpn_only": {
        "label": "VPN subnet only (recommended)",
        "description": (
            "Only the WireGuard network (e.g. 10.77.77.0/24). "
            "Does not steal other VPN / LAN routes — best for multi-VPN setups."
        ),
        "allowed_ips": [],  # filled with server network at runtime
    },
    "split_lan": {
        "label": "All private LANs (RFC1918)",
        "description": (
            "Routes 10/8, 172.16/12, 192.168/16 via VPN. "
            "Can conflict with other VPNs that use the same private ranges."
        ),
        "allowed_ips": [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fd00::/8",
        ],
    },
    "full": {
        "label": "Full tunnel (all traffic)",
        "description": "Send all client traffic through the VPN (0.0.0.0/0 and ::/0).",
        "allowed_ips": ["0.0.0.0/0", "::/0"],
    },
    "custom": {
        "label": "Custom routes",
        "description": "Specify exact AllowedIPs (CIDRs). Use this to include only the LANs you need.",
        "allowed_ips": [],
    },
}


def _opts(options: dict[str, Any] | None) -> dict[str, Any]:
    o = options or {}
    return {
        "data_dir": o.get("data_dir") or DEFAULT_DATA_DIR,
        "interface": o.get("interface") or DEFAULT_INTERFACE,
        "wg_conf_dir": o.get("wg_conf_dir") or "/etc/wireguard",
        "default_address": o.get("default_address") or DEFAULT_ADDRESS,
        "default_listen_port": int(o.get("default_listen_port") or DEFAULT_LISTEN_PORT),
        "default_dns": o.get("default_dns") or "1.1.1.1, 8.8.8.8",
        "endpoint_host": (o.get("endpoint_host") or "").strip(),
        "allow_install": bool(o.get("allow_install", True)),
        "show_live_peers": bool(o.get("show_live_peers", True)),
        "show_ip_map": bool(o.get("show_ip_map", True)),
        "record_history": bool(o.get("record_history", False)),
        "history_interval_seconds": int(o.get("history_interval_seconds") or 30),
        "online_handshake_seconds": int(o.get("online_handshake_seconds") or 180),
    }


def _data_dir(opts: dict[str, Any]) -> Path:
    return Path(opts["data_dir"])


def _server_meta_path(opts: dict[str, Any]) -> Path:
    return _data_dir(opts) / "server.json"


def _peers_dir(opts: dict[str, Any]) -> Path:
    return _data_dir(opts) / "peers"


def _conf_path(opts: dict[str, Any]) -> Path:
    return Path(opts["wg_conf_dir"]) / f"{opts['interface']}.conf"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


async def _ensure_data_dirs(opts: dict[str, Any]) -> tuple[bool, str]:
    root = str(_data_dir(opts))
    peers = str(_peers_dir(opts))
    for path in (root, peers):
        if Path(path).is_dir():
            continue
        code, out, err = await run_privileged(["mkdir", "-p", path])
        if code != 0:
            return False, (err or out or "mkdir failed").strip()
        await run_privileged(["chmod", "0700", path])
    return True, ""


async def _write_secret_file(path: str, content: str, mode: str = "0600") -> tuple[bool, str]:
    parent = str(Path(path).parent)
    code, out, err = await run_privileged(["mkdir", "-p", parent])
    if code != 0 and not Path(parent).is_dir():
        return False, (err or out or "mkdir failed").strip()
    import tempfile
    import os

    fd, tmp = tempfile.mkstemp(prefix="lnxadmin-wg-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        code, out, err = await run_privileged(["install", f"-m{mode}", tmp, path])
        if code != 0:
            return False, (err or out or "install failed").strip()
        return True, ""
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _save_json_local(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


async def _gen_keypair() -> tuple[str, str] | None:
    import asyncio

    wg = shutil.which("wg")
    if not wg:
        return None
    code, priv, _ = await run_cmd([wg, "genkey"])
    if code != 0:
        return None
    priv = priv.strip()
    try:
        proc = await asyncio.create_subprocess_exec(
            wg,
            "pubkey",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate(priv.encode())
        if proc.returncode != 0:
            return None
        return priv, stdout.decode().strip()
    except Exception:
        return None


async def _gen_psk() -> str | None:
    wg = shutil.which("wg")
    if not wg:
        return None
    code, out, _ = await run_cmd([wg, "genpsk"])
    return out.strip() if code == 0 else None


def _detect_pkg_manager() -> str | None:
    for name in ("apt-get", "dnf", "yum", "apk", "pacman", "zypper"):
        if shutil.which(name):
            return name
    return None


def _default_endpoint(opts: dict[str, Any], listen_port: int) -> str:
    host = opts.get("endpoint_host") or ""
    if not host:
        try:
            host = socket.getfqdn() or socket.gethostname()
        except Exception:
            host = "YOUR_SERVER_IP"
    if not host or host.startswith("localhost"):
        host = "YOUR_SERVER_IP"
    return _normalize_endpoint(host, listen_port)


def _normalize_endpoint(endpoint: str, listen_port: int) -> str:
    """Ensure Endpoint is host:port (WireGuard clients reject host-only values)."""
    ep = (endpoint or "").strip()
    port = int(listen_port or DEFAULT_LISTEN_PORT)
    if not ep:
        return ep

    # Bracketed IPv6: [addr] or [addr]:port
    if ep.startswith("["):
        close = ep.find("]")
        if close != -1:
            rest = ep[close + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return ep
            if rest == "":
                return f"{ep}:{port}"
        return ep

    # Already host:port (exactly one colon, numeric port)
    if ep.count(":") == 1:
        _host, maybe_port = ep.rsplit(":", 1)
        if maybe_port.isdigit() and 1 <= int(maybe_port) <= 65535:
            return ep

    # Bare IPv6 (multiple colons) → wrap and add port
    if ep.count(":") >= 2:
        return f"[{ep}]:{port}"

    return f"{ep}:{port}"


def _network_of(cidr: str) -> str:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        return str(net)
    except ValueError:
        return cidr


def _next_client_address(server_cidr: str, used: set[str]) -> str | None:
    try:
        net = ipaddress.ip_network(server_cidr, strict=False)
    except ValueError:
        return None
    # skip network, gateway (.1 typically server), broadcast
    for host in net.hosts():
        addr = f"{host}/{net.max_prefixlen}"
        ip = str(host)
        if ip in used:
            continue
        # skip server address itself
        server_ip = server_cidr.split("/")[0]
        if ip == server_ip:
            continue
        return addr
    return None


def _used_peer_ips(opts: dict[str, Any], *, exclude_peer_id: str | None = None) -> set[str]:
    used: set[str] = set()
    for p in _peers_dir(opts).glob("*.json"):
        d = _load_json(p) or {}
        if exclude_peer_id and d.get("id") == exclude_peer_id:
            continue
        ip = (d.get("address") or "").split("/")[0].strip()
        if ip:
            used.add(ip)
    return used


def _normalize_client_address(raw: str, server_cidr: str) -> tuple[str | None, str | None]:
    """Normalize peer address to host/prefixlen inside the VPN subnet.

    Returns (address, error). Accepts ``10.x.x.x`` or ``10.x.x.x/32``.
    """
    value = (raw or "").strip()
    if not value:
        return None, "Address is required"
    try:
        net = ipaddress.ip_network(server_cidr, strict=False)
    except ValueError:
        return None, "Invalid server subnet"
    try:
        if "/" in value:
            iface = ipaddress.ip_interface(value)
        else:
            iface = ipaddress.ip_interface(f"{value}/{net.max_prefixlen}")
    except ValueError:
        return None, "Invalid peer address"
    if iface.ip.version != net.version:
        return None, "Address family mismatch (IPv4/IPv6)"
    if iface.ip not in net:
        return None, f"Address must be inside VPN subnet {net}"
    if iface.ip == net.network_address:
        return None, "Cannot use network address"
    if net.version == 4 and iface.ip == net.broadcast_address:
        return None, "Cannot use broadcast address"
    server_ip = server_cidr.split("/")[0].strip()
    if str(iface.ip) == server_ip:
        return None, "Address is reserved for the WireGuard server"
    return f"{iface.ip}/{net.max_prefixlen}", None


IP_MAP_MAX_HOSTS = 1024  # up to /22


def _build_ip_map(server_cidr: str, peers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """phpIPAM-style occupancy map for the VPN subnet."""
    try:
        net = ipaddress.ip_network(server_cidr, strict=False)
    except ValueError:
        return None

    server_ip = server_cidr.split("/")[0].strip()
    by_ip: dict[str, dict[str, Any]] = {}
    for p in peers:
        ip = (p.get("address") or "").split("/")[0].strip()
        if ip:
            by_ip[ip] = p

    # Prefer usable hosts; for tiny nets include all addresses in network
    hosts = list(net.hosts())
    if net.num_addresses <= 2:
        hosts = list(net)

    truncated = len(hosts) > IP_MAP_MAX_HOSTS
    if truncated:
        hosts = hosts[:IP_MAP_MAX_HOSTS]

    cells: list[dict[str, Any]] = []
    used = 0
    free = 0
    for host in hosts:
        ip = str(host)
        peer = by_ip.get(ip)
        if ip == server_ip:
            state = "server"
        elif peer:
            state = "peer"
            used += 1
        else:
            state = "free"
            free += 1
        cell: dict[str, Any] = {
            "ip": ip,
            "host": int(host) & 0xFF if host.version == 4 else None,
            "state": state,
        }
        if peer:
            cell["peer_id"] = peer.get("id")
            cell["peer_name"] = peer.get("name")
            cell["enabled"] = bool(peer.get("enabled", True))
            cell["notes"] = peer.get("notes") or ""
        cells.append(cell)

    total_usable = max(0, net.num_addresses - (2 if net.version == 4 and net.prefixlen < 31 else 0))
    # subtract server reservation from free pool conceptually
    reserved = 1 if server_ip else 0
    peer_count = len(by_ip)
    return {
        "network": str(net),
        "server_ip": server_ip,
        "prefixlen": net.prefixlen,
        "version": net.version,
        "total_usable": total_usable,
        "reserved": reserved,
        "used": peer_count,
        "free": max(0, total_usable - reserved - peer_count),
        "shown": len(cells),
        "truncated": truncated,
        "cells": cells,
    }


def _public_server(meta: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    listen = int(meta.get("listen_port") or opts["default_listen_port"])
    return {
        "configured": True,
        "interface": meta.get("interface") or opts["interface"],
        "address": meta.get("address") or opts["default_address"],
        "listen_port": listen,
        "public_key": meta.get("public_key") or "",
        # Empty is intentional — DNS is optional and only used when a peer chooses "server" mode
        "dns": (meta.get("dns") or "").strip(),
        "mtu": meta.get("mtu") or 1420,
        "endpoint": _normalize_endpoint(
            str(meta.get("endpoint") or _default_endpoint(opts, listen)),
            listen,
        ),
        "nat_enabled": bool(meta.get("nat_enabled", True)),
        "wan_interface": meta.get("wan_interface") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


def _list_peers(opts: dict[str, Any]) -> list[dict[str, Any]]:
    root = _peers_dir(opts)
    if not root.is_dir():
        return []
    peers: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        data = _load_json(p)
        if not data:
            continue
        peers.append(_public_peer(data))
    return peers


def _public_peer(data: dict[str, Any]) -> dict[str, Any]:
    dns_mode = (data.get("dns_mode") or "").strip().lower()
    if dns_mode not in {"none", "server", "custom"}:
        # Legacy peers: non-empty dns ⇒ custom; empty ⇒ none (never force server DNS)
        dns_mode = "custom" if (data.get("dns") or "").strip() else "none"
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "public_key": data.get("public_key"),
        "address": data.get("address"),
        "route_mode": data.get("route_mode") or "vpn_only",
        "allowed_ips_client": data.get("allowed_ips_client") or [],
        "dns_mode": dns_mode,
        "dns": data.get("dns") or "",
        "persistent_keepalive": data.get("persistent_keepalive", 25),
        "enabled": bool(data.get("enabled", True)),
        "has_preshared_key": bool(data.get("preshared_key")),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "notes": data.get("notes") or "",
    }


def _resolve_client_dns(peer: dict[str, Any], server: dict[str, Any]) -> str:
    """Decide which DNS (if any) goes into the client config.

    Modes:
      none   — omit DNS= (client keeps OS / corporate DNS)  [default]
      server — use server.dns if set
      custom — use peer.dns
    Legacy peers without dns_mode: non-empty peer.dns is treated as custom;
    empty means none (no longer falls back to server DNS).
    """
    mode = (peer.get("dns_mode") or "").strip().lower()
    if not mode:
        return (peer.get("dns") or "").strip()
    if mode == "none":
        return ""
    if mode == "server":
        return (server.get("dns") or "").strip()
    # custom
    return (peer.get("dns") or "").strip()


def _normalize_peer_dns_fields(body: dict[str, Any], server: dict[str, Any]) -> tuple[str, str]:
    """Return (dns_mode, dns) from request body."""
    mode = (body.get("dns_mode") or "").strip().lower()
    raw = body.get("dns")
    if not mode:
        # Back-compat: explicit dns string ⇒ custom; empty/missing ⇒ none
        if raw is None or str(raw).strip() == "":
            return "none", ""
        return "custom", str(raw).strip()
    if mode not in {"none", "server", "custom"}:
        mode = "none"
    if mode == "none":
        return "none", ""
    if mode == "server":
        return "server", ""  # resolved at config-build time
    return "custom", (str(raw).strip() if raw is not None else "")


def _resolve_allowed_ips(
    mode: str,
    custom: list[str] | None,
    server_cidr: str,
) -> list[str]:
    mode = (mode or "vpn_only").lower()
    if mode == "custom":
        return [x.strip() for x in (custom or []) if x and x.strip()]
    if mode == "vpn_only":
        return [_network_of(server_cidr)]
    preset = ROUTE_PRESETS.get(mode) or ROUTE_PRESETS["vpn_only"]
    ips = list(preset["allowed_ips"])
    if mode == "split_lan":
        # always include VPN subnet
        net = _network_of(server_cidr)
        if net not in ips:
            ips.insert(0, net)
    return ips


def _format_bytes(n: int) -> str:
    value = float(max(0, int(n or 0)))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{int(n)} B"


def _format_ago(seconds: int | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s ago"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m ago"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d}d {h}h ago"


async def _wg_dump_peers(
    interface: str,
    *,
    online_handshake_seconds: int = 180,
) -> dict[str, Any]:
    """Parse ``wg show <iface> dump`` into structured peer runtime rows."""
    wg = shutil.which("wg")
    if not wg:
        return {"up": False, "error": "wg not installed", "peers": [], "online_count": 0}
    code, out, err = await run_cmd([wg, "show", interface, "dump"])
    if code != 0:
        return {
            "up": False,
            "error": (err or out or "not running").strip(),
            "peers": [],
            "online_count": 0,
        }

    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return {"up": False, "error": "empty dump", "peers": [], "online_count": 0}

    now = int(time.time())
    threshold = max(30, int(online_handshake_seconds or 180))
    peers: list[dict[str, Any]] = []
    # First line is the interface itself
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        public_key = parts[0]
        endpoint = parts[2] if parts[2] != "(none)" else ""
        allowed_ips = parts[3] if parts[3] != "(none)" else ""
        try:
            handshake = int(parts[4] or 0)
        except ValueError:
            handshake = 0
        try:
            rx = int(parts[5] or 0)
            tx = int(parts[6] or 0)
        except ValueError:
            rx, tx = 0, 0
        ago = (now - handshake) if handshake > 0 else None
        online = handshake > 0 and ago is not None and ago <= threshold
        remote_ip = None
        remote_port = None
        if endpoint:
            if endpoint.startswith("["):
                # [ipv6]:port
                m = re.match(r"^\[([^\]]+)\]:(\d+)$", endpoint)
                if m:
                    remote_ip, remote_port = m.group(1), int(m.group(2))
            elif endpoint.count(":") == 1:
                host, port_s = endpoint.rsplit(":", 1)
                if port_s.isdigit():
                    remote_ip, remote_port = host, int(port_s)
            else:
                remote_ip = endpoint
        peers.append(
            {
                "public_key": public_key,
                "endpoint": endpoint or None,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "allowed_ips": [x.strip() for x in allowed_ips.split(",") if x.strip()] if allowed_ips else [],
                "latest_handshake": handshake or None,
                "latest_handshake_ago": ago,
                "latest_handshake_ago_human": _format_ago(ago),
                "transfer_rx": rx,
                "transfer_tx": tx,
                "transfer_rx_human": _format_bytes(rx),
                "transfer_tx_human": _format_bytes(tx),
                "online": online,
            }
        )

    online_count = sum(1 for p in peers if p.get("online"))
    return {
        "up": True,
        "peers": peers,
        "online_count": online_count,
        "peer_runtime_count": len(peers),
        "online_handshake_seconds": threshold,
        "collected_at": now,
    }


async def _wg_show(interface: str, *, with_raw: bool = False) -> dict[str, Any]:
    """Lightweight interface status (no per-peer dump)."""
    wg = shutil.which("wg")
    if not wg:
        return {"up": False, "error": "wg not installed"}
    code, out, err = await run_cmd([wg, "show", interface])
    if code != 0:
        return {"up": False, "raw": "", "error": (err or out or "not running").strip()}
    result: dict[str, Any] = {
        "up": True,
        "peers_listed": out.count("peer:"),
    }
    if with_raw:
        result["raw"] = out
    return result



def tools_status() -> dict[str, Any]:
    return {
        "wg": bool(shutil.which("wg")),
        "wg_quick": bool(shutil.which("wg-quick")),
        "ip": bool(shutil.which("ip")),
        "pkg_manager": _detect_pkg_manager(),
    }


async def collect_live_peers(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live peer runtime used by overview + history worker."""
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    iface = (meta or {}).get("interface") or opts["interface"]
    if not meta:
        return {
            "available": False,
            "up": False,
            "peers": [],
            "online_count": 0,
            "error": "Server not configured",
        }

    dump = await _wg_dump_peers(
        iface,
        online_handshake_seconds=opts["online_handshake_seconds"],
    )
    peers_meta = {p.get("public_key"): p for p in _list_peers(opts)}
    enriched: list[dict[str, Any]] = []
    for row in dump.get("peers") or []:
        meta_p = peers_meta.get(row.get("public_key")) or {}
        enriched.append(
            {
                **row,
                "peer_id": meta_p.get("id"),
                "name": meta_p.get("name") or (row.get("public_key") or "")[:12],
                "address": meta_p.get("address"),
                "enabled": meta_p.get("enabled", True),
                "notes": meta_p.get("notes") or "",
            }
        )
    online = [p for p in enriched if p.get("online")]
    return {
        "available": True,
        "interface": iface,
        "up": bool(dump.get("up")),
        "error": dump.get("error"),
        "peers": enriched,
        "online_peers": online,
        "online_count": len(online),
        "peer_count": len(peers_meta) or len(enriched),
        "online_handshake_seconds": dump.get("online_handshake_seconds"),
        "collected_at": dump.get("collected_at"),
    }


async def collect_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    meta = _load_json(_server_meta_path(opts))
    peers = _list_peers(opts)
    iface = (meta or {}).get("interface") or opts["interface"]
    conf = _conf_path(opts)

    status: dict[str, Any]
    live_peers: list[dict[str, Any]] = []
    online_count = 0
    features = {
        "show_live_peers": opts["show_live_peers"],
        "show_ip_map": opts["show_ip_map"],
        "record_history": opts["record_history"],
        "online_handshake_seconds": opts["online_handshake_seconds"],
    }

    if not tools["wg"]:
        status = {"up": False, "error": "wg missing"}
    elif opts["show_live_peers"]:
        dump = await _wg_dump_peers(
            iface,
            online_handshake_seconds=opts["online_handshake_seconds"],
        )
        status = {
            "up": bool(dump.get("up")),
            "error": dump.get("error"),
            "online_count": dump.get("online_count") or 0,
            "online_handshake_seconds": dump.get("online_handshake_seconds"),
        }
        # Optional human dump for the debug panel (only when live is on)
        light = await _wg_show(iface, with_raw=True)
        if light.get("raw"):
            status["raw"] = light["raw"]
        by_key = {p.get("public_key"): p for p in (dump.get("peers") or [])}
        enriched_peers: list[dict[str, Any]] = []
        for p in peers:
            runtime = by_key.get(p.get("public_key")) or {}
            row = {
                **p,
                "online": bool(runtime.get("online")),
                "endpoint_runtime": runtime.get("endpoint"),
                "remote_ip": runtime.get("remote_ip"),
                "remote_port": runtime.get("remote_port"),
                "latest_handshake": runtime.get("latest_handshake"),
                "latest_handshake_ago": runtime.get("latest_handshake_ago"),
                "latest_handshake_ago_human": runtime.get("latest_handshake_ago_human") or "never",
                "transfer_rx": runtime.get("transfer_rx") or 0,
                "transfer_tx": runtime.get("transfer_tx") or 0,
                "transfer_rx_human": runtime.get("transfer_rx_human") or "0 B",
                "transfer_tx_human": runtime.get("transfer_tx_human") or "0 B",
            }
            enriched_peers.append(row)
            if row["online"]:
                live_peers.append(row)
                online_count += 1
        peers = enriched_peers
        # Also include unknown runtime peers (not in our JSON store)
        known = {p.get("public_key") for p in peers}
        for runtime in dump.get("peers") or []:
            if runtime.get("public_key") in known:
                continue
            if not runtime.get("online"):
                continue
            ghost = {
                "id": None,
                "name": f"unknown:{(runtime.get('public_key') or '')[:8]}",
                "public_key": runtime.get("public_key"),
                "address": (runtime.get("allowed_ips") or ["?"])[0],
                "online": True,
                "endpoint_runtime": runtime.get("endpoint"),
                "remote_ip": runtime.get("remote_ip"),
                "remote_port": runtime.get("remote_port"),
                "latest_handshake": runtime.get("latest_handshake"),
                "latest_handshake_ago": runtime.get("latest_handshake_ago"),
                "latest_handshake_ago_human": runtime.get("latest_handshake_ago_human"),
                "transfer_rx": runtime.get("transfer_rx") or 0,
                "transfer_tx": runtime.get("transfer_tx") or 0,
                "transfer_rx_human": runtime.get("transfer_rx_human"),
                "transfer_tx_human": runtime.get("transfer_tx_human"),
                "enabled": True,
                "notes": "Not managed by this panel",
            }
            live_peers.append(ghost)
            online_count += 1
        status["online_count"] = online_count
    else:
        status = await _wg_show(iface, with_raw=False)

    ip_map = None
    if opts["show_ip_map"] and meta and meta.get("address"):
        ip_map = _build_ip_map(meta["address"], peers)

    return {
        "available": True,
        "tools": tools,
        "installed": bool(tools["wg"] and tools["wg_quick"]),
        "interface": iface,
        "conf_path": str(conf),
        "conf_exists": conf.is_file(),
        "server": _public_server(meta, opts) if meta else None,
        "peers": peers,
        "peer_count": len(peers),
        "peers_enabled": sum(1 for p in peers if p.get("enabled")),
        "status": status,
        "live_peers": live_peers,
        "online_count": online_count,
        "features": features,
        "ip_map": ip_map,
        "route_presets": {
            k: {"label": v["label"], "description": v["description"]}
            for k, v in ROUTE_PRESETS.items()
        },
        "data_dir": opts["data_dir"],
    }


async def install_tools(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    if not opts["allow_install"]:
        return {"ok": False, "error": "Package install is disabled in module settings"}
    tools = tools_status()
    if tools["wg"] and tools["wg_quick"]:
        return {"ok": True, "already": True, "tools": tools}

    pm = tools["pkg_manager"]
    if not pm:
        return {"ok": False, "error": "No supported package manager found (apt/dnf/yum/apk/pacman/zypper)"}

    if pm == "apt-get":
        cmds = [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "wireguard", "wireguard-tools"],
        ]
    elif pm == "dnf":
        cmds = [["dnf", "install", "-y", "wireguard-tools"]]
    elif pm == "yum":
        cmds = [["yum", "install", "-y", "wireguard-tools"]]
    elif pm == "apk":
        cmds = [["apk", "add", "--no-cache", "wireguard-tools"]]
    elif pm == "pacman":
        cmds = [["pacman", "-Sy", "--noconfirm", "wireguard-tools"]]
    elif pm == "zypper":
        cmds = [["zypper", "--non-interactive", "install", "wireguard-tools"]]
    else:
        return {"ok": False, "error": f"Unsupported package manager: {pm}"}

    logs: list[str] = []
    for cmd in cmds:
        code, out, err = await run_privileged(cmd, timeout=300.0)
        logs.append(f"$ {' '.join(cmd)}\n{(out or '')}{(err or '')}".strip())
        if code != 0 and cmd[0] != "apt-get":  # apt-get update may warn
            # apt-get update failure is soft; install failure is hard
            if "install" in cmd or cmd[0] in {"dnf", "yum", "apk", "pacman", "zypper"}:
                return {"ok": False, "error": err or out or "install failed", "log": "\n\n".join(logs)}

    tools = tools_status()
    ok = bool(tools["wg"] and tools["wg_quick"])
    return {
        "ok": ok,
        "tools": tools,
        "log": "\n\n".join(logs)[-8000:],
        "error": None if ok else "wireguard-tools still missing after install",
    }


async def create_or_update_server(
    body: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opts = _opts(options)
    if not tools_status()["wg"]:
        return {"ok": False, "error": "Install WireGuard tools first"}

    ok, err = await _ensure_data_dirs(opts)
    if not ok:
        return {"ok": False, "error": err}

    iface = (body.get("interface") or opts["interface"]).strip()
    if not IFACE_RE.fullmatch(iface):
        return {"ok": False, "error": "Invalid interface name"}

    address = (body.get("address") or opts["default_address"]).strip()
    try:
        ipaddress.ip_network(address, strict=False)
    except ValueError:
        return {"ok": False, "error": "Invalid server address CIDR"}

    listen_port = int(body.get("listen_port") or opts["default_listen_port"])
    if not (1 <= listen_port <= 65535):
        return {"ok": False, "error": "Invalid listen port"}

    existing = _load_json(_server_meta_path(opts)) or {}
    private_key = existing.get("private_key")
    public_key = existing.get("public_key")
    if not private_key or body.get("rotate_keys"):
        pair = await _gen_keypair()
        if not pair:
            return {"ok": False, "error": "Failed to generate keys (is wg installed?)"}
        private_key, public_key = pair

    wan = (body.get("wan_interface") or existing.get("wan_interface") or "").strip()
    if not wan:
        wan = await _detect_wan_iface()

    meta = {
        "interface": iface,
        "address": address,
        "listen_port": listen_port,
        "private_key": private_key,
        "public_key": public_key,
        "dns": (body.get("dns") if body.get("dns") is not None else existing.get("dns") or ""),
        "mtu": int(body.get("mtu") or existing.get("mtu") or 1420),
        "endpoint": _normalize_endpoint(
            str(body.get("endpoint") or existing.get("endpoint") or _default_endpoint(opts, listen_port)),
            listen_port,
        ),
        "nat_enabled": bool(body.get("nat_enabled", existing.get("nat_enabled", True))),
        "wan_interface": wan,
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(),
    }
    opts["interface"] = iface
    _save_json_local(_server_meta_path(opts), meta)

    # Keep module interface in sync via returned value
    return {"ok": True, "server": _public_server(meta, opts)}


def _build_server_conf(meta: dict[str, Any], peers: list[dict[str, Any]]) -> str:
    iface = meta["interface"]
    wan = meta.get("wan_interface") or "eth0"
    lines = [
        MANAGED_MARKER,
        "[Interface]",
        f"Address = {meta['address']}",
        f"ListenPort = {meta['listen_port']}",
        f"PrivateKey = {meta['private_key']}",
    ]
    mtu = meta.get("mtu")
    if mtu:
        lines.append(f"MTU = {mtu}")

    if meta.get("nat_enabled", True):
        # IPv4 NAT + forwarding; keep portable
        lines.append(
            f"PostUp = sysctl -w net.ipv4.ip_forward=1; "
            f"iptables -A FORWARD -i {iface} -j ACCEPT; "
            f"iptables -A FORWARD -o {iface} -j ACCEPT; "
            f"iptables -t nat -A POSTROUTING -o {wan} -j MASQUERADE"
        )
        lines.append(
            f"PostDown = iptables -D FORWARD -i {iface} -j ACCEPT; "
            f"iptables -D FORWARD -o {iface} -j ACCEPT; "
            f"iptables -t nat -D POSTROUTING -o {wan} -j MASQUERADE"
        )

    for peer in peers:
        if not peer.get("enabled", True):
            continue
        lines.extend(
            [
                "",
                f"# Peer: {peer.get('name')}",
                "[Peer]",
                f"PublicKey = {peer['public_key']}",
            ]
        )
        if peer.get("preshared_key"):
            lines.append(f"PresharedKey = {peer['preshared_key']}")
        # On server, AllowedIPs is the peer tunnel address
        peer_ip = (peer.get("address") or "").split("/")[0]
        if peer_ip:
            lines.append(f"AllowedIPs = {peer_ip}/32")

    return "\n".join(lines) + "\n"


async def _ensure_wg_udp_port(listen_port: int) -> str | None:
    """Open WireGuard listen port (UDP) in UFW if present. Returns warning or None."""
    port = int(listen_port or DEFAULT_LISTEN_PORT)
    if not (1 <= port <= 65535):
        return f"Invalid listen port: {port}"
    ufw = shutil.which("ufw")
    if not ufw:
        return None
    # status may be inactive — still add rule for when UFW is enabled later
    code, out, _ = await run_privileged([ufw, "status"], timeout=10.0)
    status_text = (out or "").lower()
    # Avoid duplicate rules: check if udp already allowed
    if f"{port}/udp" in status_text and "allow" in status_text:
        return None
    code, out, err = await run_privileged(
        [ufw, "allow", f"{port}/udp", "comment", "WireGuard"],
        timeout=15.0,
    )
    if code != 0:
        return f"Could not open {port}/udp in UFW: {(err or out or '').strip()[:200]}"
    # Remove mistaken TCP rule if someone opened tcp for WG earlier
    await run_privileged([ufw, "delete", "allow", f"{port}/tcp"], timeout=10.0)
    return None


async def apply_server(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured yet"}
    opts["interface"] = meta.get("interface") or opts["interface"]

    peers_raw: list[dict[str, Any]] = []
    for p in _peers_dir(opts).glob("*.json"):
        data = _load_json(p)
        if data:
            peers_raw.append(data)

    conf = _build_server_conf(meta, peers_raw)
    conf_path = str(_conf_path(opts))
    ok, err = await _write_secret_file(conf_path, conf, "0600")
    if not ok:
        return {"ok": False, "error": err}

    iface = meta["interface"]
    listen_port = int(meta.get("listen_port") or opts["default_listen_port"] or DEFAULT_LISTEN_PORT)
    fw_warning = await _ensure_wg_udp_port(listen_port)

    # Bring down if already up, then up
    wg_quick = shutil.which("wg-quick") or "/usr/bin/wg-quick"
    await run_privileged([wg_quick, "down", iface], timeout=30.0)
    code, out, err = await run_privileged([wg_quick, "up", iface], timeout=30.0)
    if code != 0:
        return {
            "ok": False,
            "error": (err or out or "wg-quick up failed").strip(),
            "conf_path": conf_path,
        }

    # Enable on boot
    await run_privileged(["systemctl", "enable", f"wg-quick@{iface}"], timeout=20.0)

    status = await _wg_show(iface)
    result: dict[str, Any] = {"ok": True, "conf_path": conf_path, "status": status}
    if fw_warning:
        result["warning"] = fw_warning
    return result


async def stop_server(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    iface = (meta or {}).get("interface") or opts["interface"]
    wg_quick = shutil.which("wg-quick") or "/usr/bin/wg-quick"
    code, out, err = await run_privileged([wg_quick, "down", iface], timeout=30.0)
    if code != 0:
        return {"ok": False, "error": (err or out or "wg-quick down failed").strip()}
    return {"ok": True, "status": await _wg_show(iface)}


async def create_peer(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    if not meta:
        return {"ok": False, "error": "Configure the WireGuard server first"}

    name = (body.get("name") or "").strip()
    if not NAME_RE.fullmatch(name):
        return {"ok": False, "error": "Invalid peer name (letters, digits, ._- ; max 32)"}

    ok, err = await _ensure_data_dirs(opts)
    if not ok:
        return {"ok": False, "error": err}

    # uniqueness
    for existing in _list_peers(opts):
        if (existing.get("name") or "").lower() == name.lower():
            return {"ok": False, "error": f"Peer '{name}' already exists"}

    pair = await _gen_keypair()
    if not pair:
        return {"ok": False, "error": "Failed to generate peer keys"}
    priv, pub = pair
    psk = await _gen_psk() if body.get("use_preshared_key", True) else None

    used = _used_peer_ips(opts)
    server_ip = (meta.get("address") or "").split("/")[0]
    if server_ip:
        used.add(server_ip)

    raw_address = (body.get("address") or "").strip()
    if raw_address:
        address, addr_err = _normalize_client_address(raw_address, meta["address"])
        if addr_err or not address:
            return {"ok": False, "error": addr_err or "Invalid peer address"}
        if address.split("/")[0] in used:
            return {"ok": False, "error": f"Address {address.split('/')[0]} is already in use"}
    else:
        address = _next_client_address(meta["address"], used) or ""
        if not address:
            return {"ok": False, "error": "No free client addresses in server subnet"}

    route_mode = (body.get("route_mode") or "vpn_only").lower()
    if route_mode not in ROUTE_PRESETS:
        return {"ok": False, "error": "Invalid route mode"}

    allowed = _resolve_allowed_ips(
        route_mode,
        body.get("allowed_ips_client"),
        meta["address"],
    )
    if route_mode == "custom" and not allowed:
        return {"ok": False, "error": "Custom mode requires at least one AllowedIP"}

    dns_mode, dns_value = _normalize_peer_dns_fields(body, meta)

    peer_id = secrets.token_hex(8)
    data = {
        "id": peer_id,
        "name": name,
        "private_key": priv,
        "public_key": pub,
        "preshared_key": psk,
        "address": address,
        "route_mode": route_mode,
        "allowed_ips_client": allowed,
        "dns_mode": dns_mode,
        "dns": dns_value,
        "persistent_keepalive": int(body.get("persistent_keepalive") or 25),
        "enabled": True,
        "notes": (body.get("notes") or "")[:200],
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save_json_local(_peers_dir(opts) / f"{peer_id}.json", data)

    applied = False
    apply_err = None
    if body.get("apply", True):
        res = await apply_server(options)
        applied = bool(res.get("ok"))
        apply_err = res.get("error")

    return {
        "ok": True,
        "peer": _public_peer(data),
        "client_config": build_client_config(data, meta, opts),
        "applied": applied,
        "apply_error": apply_err,
    }


async def update_peer(
    peer_id: str,
    body: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured"}
    path = _peers_dir(opts) / f"{peer_id}.json"
    data = _load_json(path)
    if not data:
        return {"ok": False, "error": "Peer not found"}

    if "name" in body and body["name"]:
        name = str(body["name"]).strip()
        if not NAME_RE.fullmatch(name):
            return {"ok": False, "error": "Invalid peer name (letters, digits, ._- ; max 32)"}
        for existing in _list_peers(opts):
            if existing.get("id") == peer_id:
                continue
            if (existing.get("name") or "").lower() == name.lower():
                return {"ok": False, "error": f"Peer '{name}' already exists"}
        data["name"] = name
    if "enabled" in body:
        data["enabled"] = bool(body["enabled"])
    if "dns_mode" in body or "dns" in body:
        # Merge with existing so partial updates still work
        merged = {
            "dns_mode": body.get("dns_mode", data.get("dns_mode")),
            "dns": body["dns"] if "dns" in body else data.get("dns"),
        }
        dns_mode, dns_value = _normalize_peer_dns_fields(merged, meta)
        data["dns_mode"] = dns_mode
        data["dns"] = dns_value
    if "persistent_keepalive" in body:
        data["persistent_keepalive"] = int(body["persistent_keepalive"] or 0)
    if "notes" in body:
        data["notes"] = str(body["notes"] or "")[:200]
    if "address" in body and body["address"]:
        address, addr_err = _normalize_client_address(str(body["address"]), meta["address"])
        if addr_err or not address:
            return {"ok": False, "error": addr_err or "Invalid peer address"}
        used = _used_peer_ips(opts, exclude_peer_id=peer_id)
        server_ip = (meta.get("address") or "").split("/")[0]
        if server_ip:
            used.add(server_ip)
        if address.split("/")[0] in used:
            return {"ok": False, "error": f"Address {address.split('/')[0]} is already in use"}
        data["address"] = address

    if "route_mode" in body or "allowed_ips_client" in body:
        mode = (body.get("route_mode") or data.get("route_mode") or "vpn_only").lower()
        if mode not in ROUTE_PRESETS:
            return {"ok": False, "error": "Invalid route mode"}
        data["route_mode"] = mode
        data["allowed_ips_client"] = _resolve_allowed_ips(
            mode,
            body.get("allowed_ips_client", data.get("allowed_ips_client")),
            meta["address"],
        )

    data["updated_at"] = _now()
    _save_json_local(path, data)

    applied = False
    apply_err = None
    if body.get("apply", True):
        res = await apply_server(options)
        applied = bool(res.get("ok"))
        apply_err = res.get("error")

    return {
        "ok": True,
        "peer": _public_peer(data),
        "client_config": build_client_config(data, meta, opts),
        "applied": applied,
        "apply_error": apply_err,
    }


async def delete_peer(
    peer_id: str,
    options: dict[str, Any] | None = None,
    *,
    apply: bool = True,
) -> dict[str, Any]:
    opts = _opts(options)
    path = _peers_dir(opts) / f"{peer_id}.json"
    if not path.is_file():
        return {"ok": False, "error": "Peer not found"}
    try:
        path.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if apply and _load_json(_server_meta_path(opts)):
        res = await apply_server(options)
        return {"ok": True, "applied": bool(res.get("ok")), "apply_error": res.get("error")}
    return {"ok": True, "applied": False}


def build_client_config(
    peer: dict[str, Any],
    server: dict[str, Any],
    opts: dict[str, Any] | None = None,
) -> str:
    o = _opts(opts)
    listen_port = int(server.get("listen_port") or o["default_listen_port"] or 51820)
    endpoint = _normalize_endpoint(
        str(server.get("endpoint") or _default_endpoint(o, listen_port)),
        listen_port,
    )
    allowed = peer.get("allowed_ips_client") or ["0.0.0.0/0", "::/0"]
    if isinstance(allowed, str):
        allowed_s = allowed
    else:
        allowed_s = ", ".join(allowed)

    lines = [
        "[Interface]",
        f"PrivateKey = {peer['private_key']}",
        f"Address = {peer['address']}",
    ]
    dns = _resolve_client_dns(peer, server)
    if dns:
        lines.append(f"DNS = {dns}")
    mtu = server.get("mtu")
    if mtu:
        lines.append(f"MTU = {mtu}")

    lines.extend(
        [
            "",
            "[Peer]",
            f"PublicKey = {server['public_key']}",
        ]
    )
    if peer.get("preshared_key"):
        lines.append(f"PresharedKey = {peer['preshared_key']}")
    lines.append(f"Endpoint = {endpoint}")
    lines.append(f"AllowedIPs = {allowed_s}")
    ka = int(peer.get("persistent_keepalive") or 0)
    if ka > 0:
        lines.append(f"PersistentKeepalive = {ka}")
    return "\n".join(lines) + "\n"


async def get_peer_config(peer_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta_path(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured"}
    data = _load_json(_peers_dir(opts) / f"{peer_id}.json")
    if not data:
        return {"ok": False, "error": "Peer not found"}
    conf = build_client_config(data, meta, opts)
    return {
        "ok": True,
        "peer": _public_peer(data),
        "filename": f"{data.get('name') or peer_id}.conf",
        "config": conf,
    }
