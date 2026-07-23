from __future__ import annotations

import socket
import shutil
from collections import Counter
from typing import Any

import psutil


def _addr(addr: Any) -> dict[str, Any] | None:
    if not addr:
        return None
    try:
        ip = getattr(addr, "ip", None)
        port = getattr(addr, "port", None)
        if ip is None:
            return None
        return {"ip": str(ip), "port": int(port) if port is not None else None}
    except Exception:
        return None


def _fmt_addr(addr: dict[str, Any] | None) -> str:
    if not addr:
        return "—"
    ip = addr.get("ip") or ""
    port = addr.get("port")
    if port is None:
        return ip or "—"
    # IPv6
    if ":" in ip and not ip.startswith("["):
        return f"[{ip}]:{port}"
    return f"{ip}:{port}"


def _proc_cache() -> dict[int, dict[str, Any]]:
    cache: dict[int, dict[str, Any]] = {}
    for p in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        try:
            info = p.info
            pid = info.get("pid")
            if pid is None:
                continue
            cmd = info.get("cmdline") or []
            cache[int(pid)] = {
                "name": info.get("name") or "?",
                "username": info.get("username"),
                "cmdline": " ".join(cmd)[:200] if cmd else None,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return cache


def collect_network_overview() -> dict[str, Any]:
    """Light summary: listening count + status histogram. Always cheap-ish."""
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        return {
            "available": False,
            "error": f"No permission to read connections: {exc}",
            "listening": 0,
            "established": 0,
            "total": 0,
            "by_status": {},
        }

    by_status: Counter[str] = Counter()
    listening = 0
    established = 0
    for c in conns:
        status = c.status or "NONE"
        by_status[status] += 1
        if status == psutil.CONN_LISTEN:
            listening += 1
        elif status == psutil.CONN_ESTABLISHED:
            established += 1

    ifaces = []
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for name, st in stats.items():
            if name.startswith("lo"):
                continue
            ipv4 = []
            ipv6 = []
            for a in addrs.get(name, []):
                if a.family == socket.AF_INET:
                    ipv4.append(a.address)
                elif a.family == socket.AF_INET6:
                    ipv6.append(a.address.split("%")[0])
            ifaces.append(
                {
                    "name": name,
                    "isup": bool(st.isup),
                    "speed": st.speed,
                    "mtu": st.mtu,
                    "ipv4": ipv4,
                    "ipv6": ipv6,
                }
            )
    except Exception:
        ifaces = []

    return {
        "available": True,
        "error": None,
        "listening": listening,
        "established": established,
        "total": len(conns),
        "by_status": dict(by_status),
        "interfaces_up": sum(1 for i in ifaces if i.get("isup")),
        "interfaces": ifaces,
    }


def collect_network_details(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    show_listening = opts.get("show_listening", True)
    show_established = opts.get("show_established", True)
    show_other = opts.get("show_other", True)
    show_interfaces = opts.get("show_interfaces", True)
    include_localhost = opts.get("include_localhost", True)
    max_rows = int(opts.get("max_rows") or 500)
    max_rows = max(50, min(5000, max_rows))

    overview = collect_network_overview()
    if not overview.get("available"):
        return {
            **overview,
            "listening_ports": [],
            "connections": [],
            "interfaces_detail": overview.get("interfaces") or [],
        }

    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        overview["available"] = False
        overview["error"] = str(exc)
        return {
            **overview,
            "listening_ports": [],
            "connections": [],
            "interfaces_detail": [],
        }

    procs = _proc_cache()
    listening_ports: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []

    for c in conns:
        local = _addr(c.laddr)
        remote = _addr(c.raddr)
        status = c.status or "NONE"
        pid = c.pid
        family = "tcp" if c.type == socket.SOCK_STREAM else "udp" if c.type == socket.SOCK_DGRAM else str(c.type)
        # psutil uses SOCK_STREAM for TCP even for LISTEN
        if c.family == socket.AF_INET:
            ip_ver = "v4"
        elif c.family == socket.AF_INET6:
            ip_ver = "v6"
        else:
            ip_ver = "?"

        if not include_localhost and local and (
            local["ip"] in ("127.0.0.1", "::1") or str(local["ip"]).startswith("127.")
        ):
            continue

        proc = procs.get(int(pid)) if pid else None
        row = {
            "pid": pid,
            "process": (proc or {}).get("name"),
            "username": (proc or {}).get("username"),
            "cmdline": (proc or {}).get("cmdline"),
            "status": status,
            "family": family,
            "ip_version": ip_ver,
            "local": local,
            "remote": remote,
            "local_addr": _fmt_addr(local),
            "remote_addr": _fmt_addr(remote),
        }

        if status == psutil.CONN_LISTEN:
            if show_listening:
                listening_ports.append(row)
        elif status == psutil.CONN_ESTABLISHED:
            if show_established:
                connections.append(row)
        else:
            if show_other:
                connections.append(row)

    # Sort listening by port, connections by status then local port
    def port_key(r: dict[str, Any]) -> int:
        return int((r.get("local") or {}).get("port") or 0)

    listening_ports.sort(key=port_key)
    connections.sort(key=lambda r: (r.get("status") or "", port_key(r)))

    if len(listening_ports) > max_rows:
        listening_ports = listening_ports[:max_rows]
    if len(connections) > max_rows:
        connections = connections[:max_rows]

    return {
        **overview,
        "listening_ports": listening_ports if show_listening else [],
        "connections": connections,
        "interfaces_detail": (overview.get("interfaces") or []) if show_interfaces else [],
        "truncated": True,
    }


_PROTECTED_IFACES = {"lo"}


async def network_set_iface(name: str, state: str) -> dict[str, Any]:
    from app.collectors._exec import run_privileged, safe_iface

    if not safe_iface(name):
        return {"ok": False, "error": "Invalid interface name"}
    if name in _PROTECTED_IFACES:
        return {"ok": False, "error": f"Interface {name} is protected"}
    state = (state or "").strip().lower()
    if state not in ("up", "down"):
        return {"ok": False, "error": "state: up|down"}
    ip = shutil.which("ip") or "/sbin/ip"
    code, out, err = await run_privileged([ip, "link", "set", "dev", name, state])
    if code != 0:
        return {"ok": False, "error": (err or out or "ip link failed").strip()[:400]}
    return {"ok": True, "iface": name, "state": state}


async def network_kill_pid(pid: int, signal: str = "TERM") -> dict[str, Any]:
    from app.collectors._exec import run_privileged

    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid PID"}
    if pid_i <= 1:
        return {"ok": False, "error": "PID ≤ 1 is forbidden"}
    sig = (signal or "TERM").upper().lstrip("-")
    if sig not in ("TERM", "KILL", "HUP", "INT"):
        return {"ok": False, "error": "signal: TERM|KILL|HUP|INT"}
    # Refuse killing ourselves / critical if obvious
    try:
        p = psutil.Process(pid_i)
        name = (p.name() or "").lower()
        if name in {"systemd", "init", "sshd"} and sig == "KILL":
            return {"ok": False, "error": f"Denied: dangerous process {name}"}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    code, out, err = await run_privileged(["kill", f"-{sig}", str(pid_i)])
    if code != 0:
        return {"ok": False, "error": (err or out or "kill failed").strip()[:400]}
    return {"ok": True, "pid": pid_i, "signal": sig}
