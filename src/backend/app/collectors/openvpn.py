"""OpenVPN server management: install, PKI, clients, .ovpn export."""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

from app.collectors._exec import run_cmd, run_privileged

DEFAULT_DATA_DIR = "/var/lib/lnxadmin/openvpn"
DEFAULT_NETWORK = "10.8.0.0/24"
DEFAULT_PORT = 1194
MANAGED_MARKER = "# managed-by: lnxadmin-openvpn"
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,31}$")

ROUTE_PRESETS: dict[str, dict[str, Any]] = {
    "full": {
        "label": "Full tunnel (all traffic)",
        "description": "Push redirect-gateway so all client traffic goes through the VPN.",
        "push_routes": [],
        "redirect_gateway": True,
    },
    "split_lan": {
        "label": "Split tunnel — private networks",
        "description": "Push RFC1918 routes only; internet stays on the client.",
        "push_routes": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        "redirect_gateway": False,
    },
    "vpn_only": {
        "label": "VPN subnet only",
        "description": "No extra routes — only the OpenVPN network.",
        "push_routes": [],
        "redirect_gateway": False,
    },
    "custom": {
        "label": "Custom routes",
        "description": "Push only the CIDRs you specify.",
        "push_routes": [],
        "redirect_gateway": False,
    },
}


def _opts(options: dict[str, Any] | None) -> dict[str, Any]:
    o = options or {}
    return {
        "data_dir": o.get("data_dir") or DEFAULT_DATA_DIR,
        "conf_dir": o.get("conf_dir") or "/etc/openvpn/server",
        "instance": o.get("instance") or "lnxadmin",
        "default_network": o.get("default_network") or DEFAULT_NETWORK,
        "default_port": int(o.get("default_port") or DEFAULT_PORT),
        "default_proto": o.get("default_proto") or "udp",
        "default_dns": o.get("default_dns") or "1.1.1.1, 8.8.8.8",
        "endpoint_host": (o.get("endpoint_host") or "").strip(),
        "allow_install": bool(o.get("allow_install", True)),
    }


def _root(opts: dict[str, Any]) -> Path:
    return Path(opts["data_dir"])


def _pki(opts: dict[str, Any]) -> Path:
    return _root(opts) / "pki"


def _clients_dir(opts: dict[str, Any]) -> Path:
    return _root(opts) / "clients"


def _server_meta(opts: dict[str, Any]) -> Path:
    return _root(opts) / "server.json"


def _conf_path(opts: dict[str, Any]) -> Path:
    return Path(opts["conf_dir"]) / f"{opts['instance']}.conf"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _detect_pkg_manager() -> str | None:
    for name in ("apt-get", "dnf", "yum", "apk", "pacman", "zypper"):
        if shutil.which(name):
            return name
    return None


def tools_status() -> dict[str, Any]:
    return {
        "openvpn": bool(shutil.which("openvpn")),
        "openssl": bool(shutil.which("openssl")),
        "pkg_manager": _detect_pkg_manager(),
    }


async def _ensure_dirs(opts: dict[str, Any]) -> tuple[bool, str]:
    for path in (_root(opts), _pki(opts), _clients_dir(opts), _pki(opts) / "issued", _pki(opts) / "private"):
        if path.is_dir():
            continue
        code, out, err = await run_privileged(["mkdir", "-p", str(path)])
        if code != 0 and not path.is_dir():
            # fallback local mkdir for data_dir under /var/lib may need root
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False, (err or out or f"mkdir {path} failed").strip()
        await run_privileged(["chmod", "0700", str(path)])
    return True, ""


async def _write_file(path: str, content: str, mode: str = "0600") -> tuple[bool, str]:
    parent = str(Path(path).parent)
    await run_privileged(["mkdir", "-p", parent])
    fd, tmp = tempfile.mkstemp(prefix="lnxadmin-ovpn-")
    import os

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        code, out, err = await run_privileged(["install", f"-m{mode}", tmp, path])
        if code != 0:
            # try direct write for data_dir
            try:
                Path(path).write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
                Path(path).chmod(int(mode, 8))
                return True, ""
            except OSError:
                return False, (err or out or "write failed").strip()
        return True, ""
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _default_endpoint(opts: dict[str, Any], port: int, proto: str) -> str:
    host = opts.get("endpoint_host") or ""
    if not host:
        try:
            host = socket.getfqdn() or socket.gethostname()
        except Exception:
            host = "YOUR_SERVER_IP"
    if not host or str(host).startswith("localhost"):
        host = "YOUR_SERVER_IP"
    return f"{host}"


def _netmask(cidr: str) -> tuple[str, str]:
    net = ipaddress.ip_network(cidr, strict=False)
    return str(net.network_address), str(net.netmask)


def _cidr_to_route_push(cidr: str) -> str | None:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    return f'push "route {net.network_address} {net.netmask}"'


async def _openssl(*args: str, input_text: str | None = None) -> tuple[int, str, str]:
    openssl = shutil.which("openssl") or "openssl"
    cmd = [openssl, *args]
    if input_text is None:
        return await run_cmd(cmd, timeout=120.0)
    import asyncio

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input_text.encode()), timeout=120.0
        )
        return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except Exception as exc:
        return 1, "", str(exc)


async def _ensure_pki(opts: dict[str, Any], cn_server: str = "lnxadmin-server") -> tuple[bool, str]:
    """Create CA, server cert, tls-crypt key if missing."""
    ok, err = await _ensure_dirs(opts)
    if not ok:
        return False, err
    pki = _pki(opts)
    ca_key = pki / "private" / "ca.key"
    ca_crt = pki / "ca.crt"
    server_key = pki / "private" / "server.key"
    server_crt = pki / "issued" / "server.crt"
    ta_key = pki / "ta.key"

    openssl = shutil.which("openssl")
    if not openssl:
        return False, "openssl not found"

    # CA
    if not ca_key.is_file() or not ca_crt.is_file():
        code, _, err = await _openssl(
            "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(ca_key), "-out", str(ca_crt),
            "-days", "3650", "-nodes",
            "-subj", "/CN=lnxadmin-OpenVPN-CA",
        )
        if code != 0:
            return False, err or "CA generation failed"
        ca_key.chmod(0o600)

    # Server
    if not server_key.is_file() or not server_crt.is_file():
        csr = pki / "server.csr"
        code, _, err = await _openssl(
            "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(server_key), "-out", str(csr),
            "-nodes", "-subj", f"/CN={cn_server}",
        )
        if code != 0:
            return False, err or "server key failed"
        code, _, err = await _openssl(
            "x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key),
            "-CAcreateserial", "-out", str(server_crt), "-days", "3650",
        )
        if code != 0:
            return False, err or "server cert failed"
        server_key.chmod(0o600)
        try:
            csr.unlink()
        except OSError:
            pass

    # tls-crypt
    if not ta_key.is_file():
        openvpn = shutil.which("openvpn")
        if openvpn:
            code, out, err = await run_cmd([openvpn, "--genkey", "secret", str(ta_key)])
            if code != 0:
                # older syntax
                code, out, err = await run_cmd([openvpn, "--genkey", "--secret", str(ta_key)])
            if code != 0:
                return False, err or out or "tls-crypt key failed"
        else:
            return False, "openvpn not found (needed for tls-crypt key)"
        try:
            ta_key.chmod(0o600)
        except OSError:
            pass

    return True, ""


async def _issue_client_cert(opts: dict[str, Any], name: str) -> tuple[bool, str]:
    pki = _pki(opts)
    ca_key = pki / "private" / "ca.key"
    ca_crt = pki / "ca.crt"
    key = pki / "private" / f"{name}.key"
    crt = pki / "issued" / f"{name}.crt"
    csr = pki / f"{name}.csr"

    if key.is_file() and crt.is_file():
        return True, ""

    code, _, err = await _openssl(
        "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-keyout", str(key), "-out", str(csr),
        "-nodes", "-subj", f"/CN={name}",
    )
    if code != 0:
        return False, err or "client key failed"
    code, _, err = await _openssl(
        "x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key),
        "-CAcreateserial", "-out", str(crt), "-days", "3650",
    )
    try:
        csr.unlink()
    except OSError:
        pass
    if code != 0:
        return False, err or "client cert failed"
    try:
        key.chmod(0o600)
    except OSError:
        pass
    return True, ""


def _public_server(meta: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    port = int(meta.get("port") or opts["default_port"])
    proto = meta.get("proto") or opts["default_proto"]
    return {
        "configured": True,
        "instance": meta.get("instance") or opts["instance"],
        "network": meta.get("network") or opts["default_network"],
        "port": port,
        "proto": proto,
        "dev": meta.get("dev") or "tun",
        "dns": meta.get("dns") or opts["default_dns"],
        "endpoint_host": meta.get("endpoint_host") or _default_endpoint(opts, port, proto),
        "cipher": meta.get("cipher") or "AES-256-GCM",
        "auth": meta.get("auth") or "SHA256",
        "nat_enabled": bool(meta.get("nat_enabled", True)),
        "wan_interface": meta.get("wan_interface") or "",
        "client_to_client": bool(meta.get("client_to_client", True)),
        "compress": meta.get("compress") or "off",
        "max_clients": int(meta.get("max_clients") or 100),
        "keepalive": meta.get("keepalive") or "10 120",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


def _public_client(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "route_mode": data.get("route_mode") or "full",
        "push_routes": data.get("push_routes") or [],
        "redirect_gateway": bool(data.get("redirect_gateway", False)),
        "dns": data.get("dns") or "",
        "enabled": bool(data.get("enabled", True)),
        "notes": data.get("notes") or "",
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def _list_clients(opts: dict[str, Any]) -> list[dict[str, Any]]:
    root = _clients_dir(opts)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        data = _load_json(p)
        if data:
            out.append(_public_client(data))
    return out


def _resolve_routes(mode: str, custom: list[str] | None, network: str) -> tuple[bool, list[str]]:
    mode = (mode or "full").lower()
    preset = ROUTE_PRESETS.get(mode) or ROUTE_PRESETS["full"]
    if mode == "custom":
        routes = [x.strip() for x in (custom or []) if x and x.strip()]
        return False, routes
    if mode == "vpn_only":
        return False, []
    if mode == "split_lan":
        routes = list(preset["push_routes"])
        return False, routes
    # full
    return True, []


async def _detect_wan() -> str:
    code, out, _ = await run_cmd(["ip", "route", "show", "default"])
    if code == 0 and out:
        m = re.search(r"\bdev\s+(\S+)", out)
        if m:
            return m.group(1)
    return "eth0"


async def _unit_status(instance: str) -> dict[str, Any]:
    # Prefer openvpn-server@INSTANCE (Debian bookworm+), fallback openvpn@INSTANCE
    for unit in (f"openvpn-server@{instance}", f"openvpn@{instance}"):
        code, out, _ = await run_cmd(["systemctl", "is-active", unit])
        state = (out or "").strip()
        if state in {"active", "inactive", "failed", "activating"}:
            return {"unit": unit, "active": state == "active", "state": state}
    return {"unit": f"openvpn-server@{instance}", "active": False, "state": "unknown"}


async def collect_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    meta = _load_json(_server_meta(opts))
    clients = _list_clients(opts)
    instance = (meta or {}).get("instance") or opts["instance"]
    status = await _unit_status(instance) if tools["openvpn"] else {"active": False, "state": "missing"}
    conf = _conf_path(opts)
    return {
        "available": True,
        "tools": tools,
        "installed": bool(tools["openvpn"] and tools["openssl"]),
        "server": _public_server(meta, opts) if meta else None,
        "clients": clients,
        "client_count": len(clients),
        "clients_enabled": sum(1 for c in clients if c.get("enabled")),
        "status": status,
        "conf_path": str(conf),
        "conf_exists": conf.is_file(),
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
    if tools["openvpn"] and tools["openssl"]:
        return {"ok": True, "already": True, "tools": tools}

    pm = tools["pkg_manager"]
    if not pm:
        return {"ok": False, "error": "No supported package manager found"}

    if pm == "apt-get":
        cmds = [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "openvpn", "openssl"],
        ]
    elif pm == "dnf":
        cmds = [["dnf", "install", "-y", "openvpn", "openssl"]]
    elif pm == "yum":
        cmds = [["yum", "install", "-y", "openvpn", "openssl"]]
    elif pm == "apk":
        cmds = [["apk", "add", "--no-cache", "openvpn", "openssl"]]
    elif pm == "pacman":
        cmds = [["pacman", "-Sy", "--noconfirm", "openvpn", "openssl"]]
    elif pm == "zypper":
        cmds = [["zypper", "--non-interactive", "install", "openvpn", "openssl"]]
    else:
        return {"ok": False, "error": f"Unsupported package manager: {pm}"}

    logs: list[str] = []
    for cmd in cmds:
        code, out, err = await run_privileged(cmd, timeout=300.0)
        logs.append(f"$ {' '.join(cmd)}\n{(out or '')}{(err or '')}".strip())
        if code != 0 and ("install" in cmd or cmd[0] in {"dnf", "yum", "apk", "pacman", "zypper"}):
            return {"ok": False, "error": err or out or "install failed", "log": "\n\n".join(logs)[-8000:]}

    tools = tools_status()
    ok = bool(tools["openvpn"] and tools["openssl"])
    return {
        "ok": ok,
        "tools": tools,
        "log": "\n\n".join(logs)[-8000:],
        "error": None if ok else "openvpn/openssl still missing after install",
    }


async def create_or_update_server(
    body: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opts = _opts(options)
    tools = tools_status()
    if not tools["openvpn"] or not tools["openssl"]:
        return {"ok": False, "error": "Install OpenVPN tools first"}

    network = (body.get("network") or opts["default_network"]).strip()
    try:
        ipaddress.ip_network(network, strict=False)
    except ValueError:
        return {"ok": False, "error": "Invalid VPN network CIDR"}

    port = int(body.get("port") or opts["default_port"])
    proto = (body.get("proto") or opts["default_proto"]).lower()
    if proto not in {"udp", "tcp"}:
        return {"ok": False, "error": "Protocol must be udp or tcp"}
    dev = (body.get("dev") or "tun").lower()
    if dev not in {"tun", "tap"}:
        return {"ok": False, "error": "Device must be tun or tap"}

    ok, err = await _ensure_pki(opts)
    if not ok:
        return {"ok": False, "error": err}

    existing = _load_json(_server_meta(opts)) or {}
    wan = (body.get("wan_interface") or existing.get("wan_interface") or "").strip()
    if not wan:
        wan = await _detect_wan()

    meta = {
        "instance": opts["instance"],
        "network": network,
        "port": port,
        "proto": proto,
        "dev": dev,
        "dns": (body.get("dns") if body.get("dns") is not None else existing.get("dns"))
        or opts["default_dns"],
        "endpoint_host": (body.get("endpoint_host") or existing.get("endpoint_host")
                          or _default_endpoint(opts, port, proto)),
        "cipher": body.get("cipher") or existing.get("cipher") or "AES-256-GCM",
        "auth": body.get("auth") or existing.get("auth") or "SHA256",
        "nat_enabled": bool(body.get("nat_enabled", existing.get("nat_enabled", True))),
        "wan_interface": wan,
        "client_to_client": bool(body.get("client_to_client", existing.get("client_to_client", True))),
        "compress": body.get("compress") or existing.get("compress") or "off",
        "max_clients": int(body.get("max_clients") or existing.get("max_clients") or 100),
        "keepalive": body.get("keepalive") or existing.get("keepalive") or "10 120",
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(),
    }
    _save_json(_server_meta(opts), meta)
    return {"ok": True, "server": _public_server(meta, opts)}


def _build_server_conf(meta: dict[str, Any], clients: list[dict[str, Any]], opts: dict[str, Any]) -> str:
    pki = _pki(opts)
    net, mask = _netmask(meta["network"])
    wan = meta.get("wan_interface") or "eth0"
    instance = meta.get("instance") or opts["instance"]
    lines = [
        MANAGED_MARKER,
        f"port {meta['port']}",
        f"proto {meta['proto']}",
        f"dev {meta.get('dev') or 'tun'}",
        f"ca {pki / 'ca.crt'}",
        f"cert {pki / 'issued' / 'server.crt'}",
        f"key {pki / 'private' / 'server.key'}",
        f"tls-crypt {pki / 'ta.key'}",
        "dh none",
        "ecdh-curve prime256v1",
        "topology subnet",
        f"server {net} {mask}",
        f"keepalive {meta.get('keepalive') or '10 120'}",
        f"cipher {meta.get('cipher') or 'AES-256-GCM'}",
        f"auth {meta.get('auth') or 'SHA256'}",
        "user nobody",
        "group nogroup",
        "persist-key",
        "persist-tun",
        f"max-clients {int(meta.get('max_clients') or 100)}",
        "status /var/log/openvpn-lnxadmin-status.log",
        "verb 3",
        "explicit-exit-notify 1" if meta.get("proto") == "udp" else "# tcp: no explicit-exit-notify",
    ]
    if meta.get("client_to_client", True):
        lines.append("client-to-client")

    compress = (meta.get("compress") or "off").lower()
    if compress in {"lz4", "lz4-v2", "lzo"}:
        lines.append(f"compress {compress}")

    # Per-client CCD directory for custom routes
    ccd = _root(opts) / "ccd"
    lines.append(f"client-config-dir {ccd}")

    # Default pushes from server DNS (clients may override via CCD — we push DNS always at server level)
    dns = [d.strip() for d in str(meta.get("dns") or "").split(",") if d.strip()]
    for d in dns:
        lines.append(f'push "dhcp-option DNS {d}"')

    # NAT via up/down scripts inline
    if meta.get("nat_enabled", True):
        lines.append(f'# NAT via {wan}')
        lines.append(
            f'push "block-outside-dns"'
        )  # Windows helper; harmless elsewhere if unsupported

    # Global note: full/split is per-client via CCD; server still enables IP forward in apply
    _ = clients  # CCD written separately
    _ = instance
    return "\n".join(lines) + "\n"


def _build_ccd(client: dict[str, Any]) -> str:
    lines: list[str] = [f"# client {client.get('name')}"]
    if client.get("redirect_gateway"):
        lines.append('push "redirect-gateway def1 bypass-dhcp"')
    for cidr in client.get("push_routes") or []:
        push = _cidr_to_route_push(cidr)
        if push:
            lines.append(push)
    dns = [d.strip() for d in str(client.get("dns") or "").split(",") if d.strip()]
    for d in dns:
        lines.append(f'push "dhcp-option DNS {d}"')
    if not client.get("enabled", True):
        lines.append("disable")
    return "\n".join(lines) + "\n"


async def apply_server(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured yet"}

    ok, err = await _ensure_pki(opts)
    if not ok:
        return {"ok": False, "error": err}

    clients_raw: list[dict[str, Any]] = []
    for p in _clients_dir(opts).glob("*.json"):
        d = _load_json(p)
        if d:
            clients_raw.append(d)

    ccd_dir = _root(opts) / "ccd"
    await run_privileged(["mkdir", "-p", str(ccd_dir)])
    try:
        ccd_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    for c in clients_raw:
        name = c.get("name")
        if not name:
            continue
        ccd_content = _build_ccd(c)
        ok, err = await _write_file(str(ccd_dir / name), ccd_content, "0644")
        if not ok:
            return {"ok": False, "error": f"CCD write failed: {err}"}

    instance = meta.get("instance") or opts["instance"]
    # Prefer openvpn-server@ (Debian bookworm+: /etc/openvpn/server/%i.conf)
    unit = f"openvpn-server@{instance}"
    code, _, _ = await run_cmd(["systemctl", "cat", unit])
    if code != 0:
        unit = f"openvpn@{instance}"
        conf_path = f"/etc/openvpn/{instance}.conf"
    else:
        conf_path = str(_conf_path(opts))

    conf = _build_server_conf(meta, clients_raw, opts)
    ok, err = await _write_file(conf_path, conf, "0644")
    if not ok:
        return {"ok": False, "error": err}

    # IP forwarding + NAT
    wan = meta.get("wan_interface") or await _detect_wan()
    if meta.get("nat_enabled", True):
        await run_privileged(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        check = await run_cmd(
            ["iptables", "-t", "nat", "-C", "POSTROUTING", "-s", meta["network"], "-o", wan, "-j", "MASQUERADE"]
        )
        if check[0] != 0:
            await run_privileged(
                ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", meta["network"], "-o", wan, "-j", "MASQUERADE"]
            )

    await run_privileged(["systemctl", "enable", unit], timeout=30.0)
    code, out, err = await run_privileged(["systemctl", "restart", unit], timeout=30.0)
    if code != 0:
        return {
            "ok": False,
            "error": (err or out or f"failed to restart {unit}").strip(),
            "conf_path": conf_path,
            "hint": "Ensure OpenVPN systemd templates exist and PKI paths are readable by the openvpn user",
        }

    status = await _unit_status(instance)
    return {"ok": True, "conf_path": conf_path, "status": status, "unit": unit}


async def stop_server(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta(opts))
    instance = (meta or {}).get("instance") or opts["instance"]
    status = await _unit_status(instance)
    unit = status.get("unit") or f"openvpn-server@{instance}"
    code, out, err = await run_privileged(["systemctl", "stop", unit], timeout=30.0)
    if code != 0:
        return {"ok": False, "error": (err or out or "stop failed").strip()}
    return {"ok": True, "status": await _unit_status(instance)}


async def create_client(body: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta(opts))
    if not meta:
        return {"ok": False, "error": "Configure the OpenVPN server first"}

    name = (body.get("name") or "").strip()
    if not NAME_RE.fullmatch(name):
        return {"ok": False, "error": "Invalid client name"}

    for existing in _list_clients(opts):
        if (existing.get("name") or "").lower() == name.lower():
            return {"ok": False, "error": f"Client '{name}' already exists"}

    ok, err = await _ensure_pki(opts)
    if not ok:
        return {"ok": False, "error": err}
    ok, err = await _issue_client_cert(opts, name)
    if not ok:
        return {"ok": False, "error": err}

    route_mode = (body.get("route_mode") or "full").lower()
    if route_mode not in ROUTE_PRESETS:
        return {"ok": False, "error": "Invalid route mode"}
    redirect, routes = _resolve_routes(route_mode, body.get("push_routes"), meta["network"])
    if route_mode == "custom" and not routes and not redirect:
        return {"ok": False, "error": "Custom mode requires at least one route"}

    client_id = secrets.token_hex(8)
    data = {
        "id": client_id,
        "name": name,
        "route_mode": route_mode,
        "push_routes": routes,
        "redirect_gateway": redirect if route_mode == "full" else bool(body.get("redirect_gateway", redirect)),
        "dns": body.get("dns") if body.get("dns") is not None else "",
        "enabled": True,
        "notes": (body.get("notes") or "")[:200],
        "created_at": _now(),
        "updated_at": _now(),
    }
    # fix full mode redirect
    if route_mode == "full":
        data["redirect_gateway"] = True
        data["push_routes"] = []
    elif route_mode == "vpn_only":
        data["redirect_gateway"] = False
        data["push_routes"] = []

    _save_json(_clients_dir(opts) / f"{client_id}.json", data)

    applied = False
    apply_err = None
    if body.get("apply", True):
        res = await apply_server(options)
        applied = bool(res.get("ok"))
        apply_err = res.get("error")

    conf = build_client_ovpn(data, meta, opts)
    return {
        "ok": True,
        "client": _public_client(data),
        "client_config": conf,
        "filename": f"{name}.ovpn",
        "applied": applied,
        "apply_error": apply_err,
        "qr_recommended": len(conf) < 2500,
    }


async def update_client(
    client_id: str,
    body: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured"}
    path = _clients_dir(opts) / f"{client_id}.json"
    data = _load_json(path)
    if not data:
        return {"ok": False, "error": "Client not found"}

    if "enabled" in body:
        data["enabled"] = bool(body["enabled"])
    if "notes" in body:
        data["notes"] = str(body["notes"] or "")[:200]
    if "dns" in body:
        data["dns"] = body["dns"] or ""
    if "route_mode" in body or "push_routes" in body:
        mode = (body.get("route_mode") or data.get("route_mode") or "full").lower()
        if mode not in ROUTE_PRESETS:
            return {"ok": False, "error": "Invalid route mode"}
        redirect, routes = _resolve_routes(mode, body.get("push_routes", data.get("push_routes")), meta["network"])
        data["route_mode"] = mode
        data["redirect_gateway"] = redirect if mode == "full" else False
        data["push_routes"] = routes if mode != "full" else []
        if mode == "full":
            data["redirect_gateway"] = True

    data["updated_at"] = _now()
    _save_json(path, data)

    applied = False
    apply_err = None
    if body.get("apply", True):
        res = await apply_server(options)
        applied = bool(res.get("ok"))
        apply_err = res.get("error")

    return {
        "ok": True,
        "client": _public_client(data),
        "client_config": build_client_ovpn(data, meta, opts),
        "filename": f"{data.get('name')}.ovpn",
        "applied": applied,
        "apply_error": apply_err,
    }


async def delete_client(
    client_id: str,
    options: dict[str, Any] | None = None,
    *,
    apply: bool = True,
) -> dict[str, Any]:
    opts = _opts(options)
    path = _clients_dir(opts) / f"{client_id}.json"
    data = _load_json(path)
    if not data:
        return {"ok": False, "error": "Client not found"}
    name = data.get("name")
    try:
        path.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    # revoke note: leave certs; disable via missing CCD on next apply
    ccd = _root(opts) / "ccd" / str(name)
    if ccd.is_file():
        try:
            ccd.unlink()
        except OSError:
            await run_privileged(["rm", "-f", str(ccd)])
    if apply and _load_json(_server_meta(opts)):
        res = await apply_server(options)
        return {"ok": True, "applied": bool(res.get("ok")), "apply_error": res.get("error")}
    return {"ok": True, "applied": False}


def build_client_ovpn(
    client: dict[str, Any],
    server: dict[str, Any],
    opts: dict[str, Any] | None = None,
) -> str:
    o = _opts(opts)
    pki = _pki(o)
    name = client["name"]
    ca = (pki / "ca.crt").read_text(encoding="utf-8")
    cert = (pki / "issued" / f"{name}.crt").read_text(encoding="utf-8")
    key = (pki / "private" / f"{name}.key").read_text(encoding="utf-8")
    ta = (pki / "ta.key").read_text(encoding="utf-8")
    host = server.get("endpoint_host") or _default_endpoint(o, int(server.get("port") or 1194), server.get("proto") or "udp")
    proto = server.get("proto") or "udp"
    # inline route hints for clients that ignore CCD (most mobile apps use embedded only — push is server-side)
    # For .ovpn we still set client basics; routes are pushed by server when connected.
    lines = [
        "client",
        f"dev {server.get('dev') or 'tun'}",
        f"proto {proto}",
        f"remote {host} {server.get('port') or 1194}",
        "resolv-retry infinite",
        "nobind",
        "persist-key",
        "persist-tun",
        "remote-cert-tls server",
        f"cipher {server.get('cipher') or 'AES-256-GCM'}",
        f"auth {server.get('auth') or 'SHA256'}",
        "verb 3",
        "<ca>",
        ca.strip(),
        "</ca>",
        "<cert>",
        cert.strip(),
        "</cert>",
        "<key>",
        key.strip(),
        "</key>",
        "<tls-crypt>",
        ta.strip(),
        "</tls-crypt>",
    ]
    return "\n".join(lines) + "\n"


async def get_client_config(client_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    meta = _load_json(_server_meta(opts))
    if not meta:
        return {"ok": False, "error": "Server not configured"}
    data = _load_json(_clients_dir(opts) / f"{client_id}.json")
    if not data:
        return {"ok": False, "error": "Client not found"}
    conf = build_client_ovpn(data, meta, opts)
    return {
        "ok": True,
        "client": _public_client(data),
        "filename": f"{data.get('name')}.ovpn",
        "config": conf,
        "qr_recommended": len(conf) < 2500,
    }
