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
    "full": {
        "label": "Full tunnel (all traffic)",
        "description": "Send all client traffic through the VPN (0.0.0.0/0 and ::/0).",
        "allowed_ips": ["0.0.0.0/0", "::/0"],
    },
    "split_lan": {
        "label": "Split tunnel — private networks",
        "description": "Only RFC1918 / ULA ranges via VPN; internet stays local.",
        "allowed_ips": [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fd00::/8",
        ],
    },
    "vpn_only": {
        "label": "VPN subnet only",
        "description": "Only the WireGuard network (talk to peers / server).",
        "allowed_ips": [],  # filled with server network at runtime
    },
    "custom": {
        "label": "Custom routes",
        "description": "Specify AllowedIPs manually.",
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
    return f"{host}:{listen_port}"


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


def _public_server(meta: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    listen = int(meta.get("listen_port") or opts["default_listen_port"])
    return {
        "configured": True,
        "interface": meta.get("interface") or opts["interface"],
        "address": meta.get("address") or opts["default_address"],
        "listen_port": listen,
        "public_key": meta.get("public_key") or "",
        "dns": meta.get("dns") or opts["default_dns"],
        "mtu": meta.get("mtu") or 1420,
        "endpoint": meta.get("endpoint") or _default_endpoint(opts, listen),
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
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "public_key": data.get("public_key"),
        "address": data.get("address"),
        "route_mode": data.get("route_mode") or "full",
        "allowed_ips_client": data.get("allowed_ips_client") or [],
        "dns": data.get("dns") or "",
        "persistent_keepalive": data.get("persistent_keepalive", 25),
        "enabled": bool(data.get("enabled", True)),
        "has_preshared_key": bool(data.get("preshared_key")),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "notes": data.get("notes") or "",
    }


def _resolve_allowed_ips(
    mode: str,
    custom: list[str] | None,
    server_cidr: str,
) -> list[str]:
    mode = (mode or "full").lower()
    if mode == "custom":
        return [x.strip() for x in (custom or []) if x and x.strip()]
    if mode == "vpn_only":
        return [_network_of(server_cidr)]
    preset = ROUTE_PRESETS.get(mode) or ROUTE_PRESETS["full"]
    ips = list(preset["allowed_ips"])
    if mode == "split_lan":
        # always include VPN subnet
        net = _network_of(server_cidr)
        if net not in ips:
            ips.insert(0, net)
    return ips


async def _wg_show(interface: str) -> dict[str, Any]:
    wg = shutil.which("wg")
    if not wg:
        return {"up": False, "error": "wg not installed"}
    code, out, err = await run_cmd([wg, "show", interface])
    if code != 0:
        return {"up": False, "raw": "", "error": (err or out or "not running").strip()}
    peers_online = out.count("peer:")
    transfer = []
    for line in out.splitlines():
        if "transfer:" in line:
            transfer.append(line.strip())
    return {
        "up": True,
        "raw": out,
        "peers_with_handshake": peers_online,
        "transfer_lines": transfer,
    }


async def _detect_wan_iface() -> str:
    code, out, _ = await run_cmd(["ip", "route", "show", "default"])
    if code == 0 and out:
        # default via x.x.x.x dev eth0
        m = re.search(r"\bdev\s+(\S+)", out)
        if m:
            return m.group(1)
    return "eth0"


def tools_status() -> dict[str, Any]:
    return {
        "wg": bool(shutil.which("wg")),
        "wg_quick": bool(shutil.which("wg-quick")),
        "ip": bool(shutil.which("ip")),
        "pkg_manager": _detect_pkg_manager(),
    }


async def collect_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    meta = _load_json(_server_meta_path(opts))
    peers = _list_peers(opts)
    iface = (meta or {}).get("interface") or opts["interface"]
    status = await _wg_show(iface) if tools["wg"] else {"up": False, "error": "wg missing"}
    conf = _conf_path(opts)

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
        "dns": (body.get("dns") if body.get("dns") is not None else existing.get("dns"))
        or opts["default_dns"],
        "mtu": int(body.get("mtu") or existing.get("mtu") or 1420),
        "endpoint": (body.get("endpoint") or existing.get("endpoint") or _default_endpoint(opts, listen_port)),
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
    return {"ok": True, "conf_path": conf_path, "status": status}


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

    used: set[str] = set()
    for p in _peers_dir(opts).glob("*.json"):
        d = _load_json(p) or {}
        ip = (d.get("address") or "").split("/")[0]
        if ip:
            used.add(ip)
    server_ip = (meta.get("address") or "").split("/")[0]
    if server_ip:
        used.add(server_ip)

    address = (body.get("address") or "").strip()
    if not address:
        address = _next_client_address(meta["address"], used) or ""
    if not address:
        return {"ok": False, "error": "No free client addresses in server subnet"}

    try:
        ipaddress.ip_interface(address)
    except ValueError:
        return {"ok": False, "error": "Invalid peer address"}

    route_mode = (body.get("route_mode") or "full").lower()
    if route_mode not in ROUTE_PRESETS:
        return {"ok": False, "error": "Invalid route mode"}

    allowed = _resolve_allowed_ips(
        route_mode,
        body.get("allowed_ips_client"),
        meta["address"],
    )
    if route_mode == "custom" and not allowed:
        return {"ok": False, "error": "Custom mode requires at least one AllowedIP"}

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
        "dns": body.get("dns") if body.get("dns") is not None else meta.get("dns") or "",
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
            return {"ok": False, "error": "Invalid peer name"}
        data["name"] = name
    if "enabled" in body:
        data["enabled"] = bool(body["enabled"])
    if "dns" in body:
        data["dns"] = body["dns"] or ""
    if "persistent_keepalive" in body:
        data["persistent_keepalive"] = int(body["persistent_keepalive"] or 0)
    if "notes" in body:
        data["notes"] = str(body["notes"] or "")[:200]
    if "address" in body and body["address"]:
        try:
            ipaddress.ip_interface(body["address"])
        except ValueError:
            return {"ok": False, "error": "Invalid peer address"}
        data["address"] = body["address"]

    if "route_mode" in body or "allowed_ips_client" in body:
        mode = (body.get("route_mode") or data.get("route_mode") or "full").lower()
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
    endpoint = server.get("endpoint") or _default_endpoint(o, int(server.get("listen_port") or 51820))
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
    dns = (peer.get("dns") or server.get("dns") or "").strip()
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
