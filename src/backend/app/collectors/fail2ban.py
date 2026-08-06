"""Fail2ban collector and management actions."""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.collectors._exec import run_cmd as _run
from app.collectors._exec import run_privileged

MANAGED_MARKER = "# managed-by: lnxadmin-fail2ban"
JAIL_D_DIR = "/etc/fail2ban/jail.d"
MAXRETRY_RE = re.compile(r"^[1-9]\d{0,5}$")


async def _systemd_active(unit: str) -> bool:
    code, out, _ = await _run(["systemctl", "is-active", unit])
    return code == 0 and out.strip() == "active"


def _detect_pkg_manager() -> str | None:
    for name in ("apt-get", "dnf", "yum", "apk", "pacman", "zypper"):
        if shutil.which(name):
            return name
    return None


def tools_status() -> dict[str, Any]:
    return {
        "fail2ban_client": bool(shutil.which("fail2ban-client")),
        "pkg_manager": _detect_pkg_manager(),
    }


def _parse_jail_status(output: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "currently_failed": 0,
        "total_failed": 0,
        "currently_banned": 0,
        "total_banned": 0,
        "banned_ips": [],
        "filter": None,
        "raw": output,
    }
    for line in output.splitlines():
        line = line.strip()
        if "Currently failed:" in line:
            result["currently_failed"] = int(re.findall(r"\d+", line)[-1])
        elif "Total failed:" in line:
            result["total_failed"] = int(re.findall(r"\d+", line)[-1])
        elif "Currently banned:" in line:
            result["currently_banned"] = int(re.findall(r"\d+", line)[-1])
        elif "Total banned:" in line:
            result["total_banned"] = int(re.findall(r"\d+", line)[-1])
        elif "Banned IP list:" in line:
            ips = line.split(":", 1)[-1].strip()
            result["banned_ips"] = [ip for ip in ips.split() if ip]
        elif "Filter" in line and "----" not in line:
            parts = line.split()
            if len(parts) >= 2:
                result["filter"] = parts[-1]
    return result


def _parse_ignoreip(output: str) -> list[str]:
    items: list[str] = []
    for line in (output or "").splitlines():
        line = line.strip()
        if not line or "ignored" in line.lower() or line.startswith("These "):
            continue
        m = re.search(r"(?:\|)?[`'\-]+\s*(.+)$", line)
        cand = (m.group(1) if m else line).strip()
        if cand and not cand.lower().startswith("these"):
            items.append(cand)
    return items


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address((ip or "").strip())
        return True
    except ValueError:
        return False


def _valid_ip_or_net(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    try:
        if "/" in v:
            ipaddress.ip_network(v, strict=False)
        else:
            ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


def _valid_jail(name: str | None) -> bool:
    return bool(name and re.fullmatch(r"[A-Za-z0-9_.-]+", name))


def _valid_time(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    if re.fullmatch(r"-?\d+", v):
        return True
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?[smhdwSMHDW]?", v))


def _normalize_time(value: str | int | float | None) -> str | None:
    if value is None or value == "":
        return None
    s = str(value).strip().replace(" ", "")
    if not _valid_time(s):
        return None
    return s


def _seconds_hint(raw: Any) -> str | None:
    try:
        sec = int(str(raw).strip())
    except (TypeError, ValueError):
        return str(raw) if raw is not None else None
    if sec < 0:
        return "permanent"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s".strip() if sec % 60 else f"{sec // 60}m"
    if sec < 86400:
        h, rem = divmod(sec, 3600)
        m = rem // 60
        return f"{h}h {m}m" if m else f"{h}h"
    d, rem = divmod(sec, 86400)
    h = rem // 3600
    return f"{d}d {h}h" if h else f"{d}d"


async def collect_fail2ban_overview() -> dict[str, Any]:
    tools = tools_status()
    binary = shutil.which("fail2ban-client")
    installed = bool(tools["fail2ban_client"])
    active = await _systemd_active("fail2ban") if installed else False
    jails: list[str] = []
    version = None
    if installed:
        code, out, _ = await _run(["fail2ban-client", "version"])
        if code == 0:
            version = out.strip() or None
        code, out, _ = await _run(["fail2ban-client", "status"])
        if code == 0:
            m = re.search(r"Jail list:\s*(.*)", out)
            if m:
                jails = [j.strip() for j in m.group(1).replace(",", " ").split() if j.strip()]
    return {
        "installed": installed,
        "active": active,
        "version": version,
        "jails_count": len(jails),
        "jails": jails,
        "binary": binary,
        "tools": tools,
    }


async def install_tools(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    if not bool(opts.get("allow_install", True)):
        return {"ok": False, "error": "Package install is disabled in module settings"}
    tools = tools_status()
    if tools["fail2ban_client"]:
        return {"ok": True, "already": True, "tools": tools}

    pm = tools["pkg_manager"]
    if not pm:
        return {"ok": False, "error": "No supported package manager found (apt/dnf/yum/apk/pacman/zypper)"}

    if pm == "apt-get":
        cmds = [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "fail2ban"],
        ]
    elif pm == "dnf":
        cmds = [["dnf", "install", "-y", "fail2ban"]]
    elif pm == "yum":
        cmds = [["yum", "install", "-y", "fail2ban"]]
    elif pm == "apk":
        cmds = [["apk", "add", "--no-cache", "fail2ban"]]
    elif pm == "pacman":
        cmds = [["pacman", "-Sy", "--noconfirm", "fail2ban"]]
    elif pm == "zypper":
        cmds = [["zypper", "--non-interactive", "install", "fail2ban"]]
    else:
        return {"ok": False, "error": f"Unsupported package manager: {pm}"}

    logs: list[str] = []
    for cmd in cmds:
        code, out, err = await run_privileged(cmd, timeout=300.0)
        logs.append(f"$ {' '.join(cmd)}\n{(out or '')}{(err or '')}".strip())
        if code != 0 and ("install" in cmd or cmd[0] in {"dnf", "yum", "apk", "pacman", "zypper"}):
            return {
                "ok": False,
                "error": err or out or "install failed",
                "log": "\n\n".join(logs)[-8000:],
            }

    await run_privileged(["systemctl", "enable", "fail2ban"], timeout=30.0)
    await run_privileged(["systemctl", "start", "fail2ban"], timeout=30.0)

    tools = tools_status()
    ok = bool(tools["fail2ban_client"])
    return {
        "ok": ok,
        "tools": tools,
        "log": "\n\n".join(logs)[-8000:],
        "error": None if ok else "fail2ban still missing after install",
    }


async def collect_fail2ban_details(log_lines: int = 80) -> dict[str, Any]:
    overview = await collect_fail2ban_overview()
    jails_detail = []
    for jail in overview.get("jails", []):
        if not _valid_jail(jail):
            continue
        code, out, err = await _run(["fail2ban-client", "status", jail])
        detail = _parse_jail_status(out if code == 0 else err)
        detail["name"] = jail
        for prop in ("bantime", "findtime", "maxretry"):
            c, o, _ = await _run(["fail2ban-client", "get", jail, prop])
            detail[prop] = o.strip() if c == 0 else None
        c, o, _ = await _run(["fail2ban-client", "get", jail, "ignoreip"])
        detail["ignoreip"] = _parse_ignoreip(o) if c == 0 else []
        detail["bantime_hint"] = _seconds_hint(detail.get("bantime"))
        detail["findtime_hint"] = _seconds_hint(detail.get("findtime"))
        jails_detail.append(detail)

    n = max(10, min(500, int(log_lines or 80)))
    log_tail: list[str] = []
    for path in ("/var/log/fail2ban.log", "/var/log/fail2ban/fail2ban.log"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                log_tail = [ln.rstrip() for ln in lines[-n:]]
                break
        except (FileNotFoundError, PermissionError):
            continue
    if not log_tail:
        code, out, _ = await _run(
            ["journalctl", "-u", "fail2ban", "-n", str(n), "--no-pager"]
        )
        if code == 0:
            log_tail = [ln for ln in out.splitlines() if ln.strip()]

    return {
        **overview,
        "config_paths": [
            "/etc/fail2ban/jail.conf",
            "/etc/fail2ban/jail.local",
            "/etc/fail2ban/jail.d",
        ],
        "jails_detail": jails_detail,
        "log_tail": log_tail,
        "param_help": {
            "bantime": "Ban duration (seconds or 10m / 1h / 1d). -1 = permanent.",
            "findtime": "Failure counting window (seconds or 10m / 1h).",
            "maxretry": "Number of failed attempts within findtime before a ban.",
            "ignoreip": "IP/CIDR in whitelist — not banned.",
        },
    }


async def _write_file(path: str, content: str, mode: str = "0644") -> tuple[bool, str]:
    parent = str(Path(path).parent)
    code, out, err = await run_privileged(["mkdir", "-p", parent])
    if code != 0 and not Path(parent).is_dir():
        return False, (err or out or "mkdir failed").strip()
    fd, tmp = tempfile.mkstemp(prefix="lnxadmin-f2b-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        code, out, err = await run_privileged(["install", f"-m{mode}", tmp, path])
        if code != 0:
            return False, (err or out or "install failed").strip()[:400]
        return True, ""
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _jail_dropin_path(jail: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", jail)
    return f"{JAIL_D_DIR}/99-lnxadmin-{safe}.local"


async def _persist_jail_params(
    jail: str,
    *,
    bantime: str | None,
    findtime: str | None,
    maxretry: str | None,
) -> tuple[bool, str]:
    path = _jail_dropin_path(jail)
    existing: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip().lower()] = v.strip()
    except OSError:
        pass

    if bantime is not None:
        existing["bantime"] = bantime
    if findtime is not None:
        existing["findtime"] = findtime
    if maxretry is not None:
        existing["maxretry"] = maxretry

    lines = [
        MANAGED_MARKER,
        f"# Jail ban conditions for [{jail}] — edited via Linux Admin",
        f"[{jail}]",
        "enabled = true",
    ]
    for key in ("bantime", "findtime", "maxretry"):
        if key in existing:
            lines.append(f"{key} = {existing[key]}")
    return await _write_file(path, "\n".join(lines) + "\n")


async def fail2ban_action(
    action: str,
    *,
    jail: str | None = None,
    ip: str | None = None,
    bantime: str | int | None = None,
    findtime: str | int | None = None,
    maxretry: str | int | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """ban|unban|reload|start|stop|restart|reload-jail|set-params|add-ignoreip|del-ignoreip"""
    action = (action or "").strip().lower()
    binary = shutil.which("fail2ban-client")
    if action in ("start", "stop", "restart"):
        code, out, err = await run_privileged(["systemctl", action, "fail2ban"])
        if code != 0:
            return {"ok": False, "error": (err or out or f"systemctl {action} failed").strip()[:400]}
        return {"ok": True, "action": action}

    if not binary:
        return {"ok": False, "error": "fail2ban-client not found"}

    if action == "reload":
        code, out, err = await run_privileged([binary, "reload"])
        if code != 0:
            return {"ok": False, "error": (err or out or "reload failed").strip()[:400]}
        return {"ok": True, "action": "reload"}

    if action == "reload-jail":
        if not _valid_jail(jail):
            return {"ok": False, "error": "Invalid jail"}
        code, out, err = await run_privileged([binary, "reload", str(jail)])
        if code != 0:
            return {"ok": False, "error": (err or out or "reload jail failed").strip()[:400]}
        return {"ok": True, "action": action, "jail": jail}

    if action in ("ban", "unban"):
        if not _valid_jail(jail):
            return {"ok": False, "error": "Invalid jail"}
        if not ip or not _valid_ip(ip):
            return {"ok": False, "error": "Invalid IP"}
        cmd_action = "banip" if action == "ban" else "unbanip"
        code, out, err = await run_privileged([binary, "set", str(jail), cmd_action, ip.strip()])
        if code != 0:
            return {"ok": False, "error": (err or out or f"{action} failed").strip()[:400]}
        return {"ok": True, "action": action, "jail": jail, "ip": ip.strip()}

    if action in ("add-ignoreip", "del-ignoreip"):
        if not _valid_jail(jail):
            return {"ok": False, "error": "Invalid jail"}
        if not ip or not _valid_ip_or_net(ip):
            return {"ok": False, "error": "Invalid IP/CIDR"}
        sub = "addignoreip" if action == "add-ignoreip" else "delignoreip"
        code, out, err = await run_privileged([binary, "set", str(jail), sub, ip.strip()])
        if code != 0:
            return {"ok": False, "error": (err or out or f"{action} failed").strip()[:400]}
        return {"ok": True, "action": action, "jail": jail, "ip": ip.strip()}

    if action == "set-params":
        if not _valid_jail(jail):
            return {"ok": False, "error": "Invalid jail"}
        bt = _normalize_time(bantime)
        ft = _normalize_time(findtime)
        mr = None if maxretry is None or maxretry == "" else str(maxretry).strip()
        if bantime is not None and bantime != "" and bt is None:
            return {"ok": False, "error": "Invalid bantime (example: 3600, 10m, 1h, -1)"}
        if findtime is not None and findtime != "" and ft is None:
            return {"ok": False, "error": "Invalid findtime (example: 600, 10m, 1h)"}
        if mr is not None and not MAXRETRY_RE.fullmatch(mr):
            return {"ok": False, "error": "Invalid maxretry (integer ≥ 1)"}
        if bt is None and ft is None and mr is None:
            return {"ok": False, "error": "Specify at least one parameter"}

        applied: dict[str, str] = {}
        for prop, val in (("bantime", bt), ("findtime", ft), ("maxretry", mr)):
            if val is None:
                continue
            code, out, err = await run_privileged([binary, "set", str(jail), prop, val])
            if code != 0:
                return {
                    "ok": False,
                    "error": (err or out or f"set {prop} failed").strip()[:400],
                    "applied": applied,
                }
            applied[prop] = val

        warning = None
        if persist:
            ok, err = await _persist_jail_params(
                str(jail),
                bantime=bt,
                findtime=ft,
                maxretry=mr,
            )
            if not ok:
                warning = f"Runtime applied, but persist to jail.d failed: {err}"
            else:
                await run_privileged([binary, "reload", str(jail)])

        return {
            "ok": True,
            "action": "set-params",
            "jail": jail,
            "applied": applied,
            "persisted": bool(persist and not warning),
            "dropin": _jail_dropin_path(str(jail)) if persist else None,
            "warning": warning,
        }

    return {"ok": False, "error": f"Unknown action: {action}"}
