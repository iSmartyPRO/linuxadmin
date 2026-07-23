from __future__ import annotations

import ipaddress
import re
import shutil
from typing import Any

from app.collectors._exec import run_cmd as _run
from app.collectors._exec import run_privileged


async def _systemd_active(unit: str) -> bool:
    code, out, _ = await _run(["systemctl", "is-active", unit])
    return code == 0 and out.strip() == "active"


def _parse_ufw(output: str) -> dict[str, Any]:
    enabled = "Status: active" in output
    defaults: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Default:"):
            defaults["raw"] = stripped.replace("Default:", "").strip()
            continue
        # [ 1] 22/tcp ALLOW IN 192.168...
        m_num = re.match(
            r"^\[?\s*(\d+)\]?\s+(\S+)\s+(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT|FWD)?\s*(.*)$",
            stripped,
            re.I,
        )
        if m_num:
            rules.append(
                {
                    "number": m_num.group(1),
                    "action": m_num.group(3).upper(),
                    "direction": (m_num.group(4) or "").upper(),
                    "details": f"{m_num.group(2)} {m_num.group(5)}".strip(),
                }
            )
            continue
        # 22/tcp ALLOW IN 192.168...
        m = re.match(
            r"^(\S+)\s+(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT|FWD)\s+(.*)$",
            stripped,
            re.I,
        )
        if m:
            rules.append(
                {
                    "number": None,
                    "action": m.group(2).upper(),
                    "direction": m.group(3).upper(),
                    "details": f"{m.group(1)} {m.group(4)}".strip(),
                }
            )
    return {"enabled": enabled, "defaults": defaults, "rules": rules, "raw": output}


async def collect_firewall_overview() -> dict[str, Any]:
    if shutil.which("ufw"):
        code, out, _ = await _run(["ufw", "status"])
        enabled = code == 0 and "Status: active" in out
        return {
            "backend": "ufw",
            "installed": True,
            "enabled": enabled,
            "active_service": await _systemd_active("ufw"),
        }
    if shutil.which("firewall-cmd"):
        active = await _systemd_active("firewalld")
        code, out, _ = await _run(["firewall-cmd", "--state"])
        enabled = code == 0 and "running" in out.lower()
        return {
            "backend": "firewalld",
            "installed": True,
            "enabled": enabled or active,
            "active_service": active,
        }
    if shutil.which("nft"):
        code, out, _ = await _run(["nft", "list", "ruleset"])
        has_rules = code == 0 and bool(out.strip())
        return {
            "backend": "nftables",
            "installed": True,
            "enabled": has_rules,
            "active_service": await _systemd_active("nftables"),
        }
    if shutil.which("iptables"):
        code, out, _ = await _run(["iptables", "-L", "-n"])
        return {
            "backend": "iptables",
            "installed": True,
            "enabled": code == 0 and "Chain" in out,
            "active_service": False,
        }
    return {
        "backend": "none",
        "installed": False,
        "enabled": False,
        "active_service": False,
    }


async def collect_firewall_details(log_lines: int = 80) -> dict[str, Any]:
    overview = await collect_firewall_overview()
    backend = overview["backend"]
    details: dict[str, Any] = {**overview, "rules": [], "zones": [], "raw": "", "log_tail": []}
    n = max(10, min(500, int(log_lines or 80)))

    if backend == "ufw":
        code, out, err = await _run(["ufw", "status", "verbose"])
        raw_verbose = out if code == 0 else err
        code2, numbered, _ = await _run(["ufw", "status", "numbered"])
        source = numbered if code2 == 0 and numbered.strip() else raw_verbose
        parsed = _parse_ufw(source)
        details.update(parsed)
        details["raw"] = raw_verbose
        if code2 == 0:
            details["numbered_raw"] = numbered
    elif backend == "firewalld":
        zones = []
        code, out, _ = await _run(["firewall-cmd", "--get-active-zones"])
        zone_names = re.findall(r"^(\S+)", out, re.M) if code == 0 else []
        for zone in zone_names:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", zone):
                continue
            z: dict[str, Any] = {"name": zone}
            for flag, arg in (
                ("services", "--list-services"),
                ("ports", "--list-ports"),
                ("rich_rules", "--list-rich-rules"),
                ("interfaces", "--list-interfaces"),
            ):
                c, o, _ = await _run(["firewall-cmd", f"--zone={zone}", arg])
                z[flag] = o.strip().split() if c == 0 and o.strip() else (
                    o.strip().splitlines() if c == 0 else []
                )
            zones.append(z)
        details["zones"] = zones
        details["raw"] = out
        details["enabled"] = overview["enabled"]
    elif backend == "nftables":
        code, out, err = await _run(["nft", "list", "ruleset"])
        details["raw"] = out if code == 0 else err
        details["rules"] = [
            {"details": line} for line in details["raw"].splitlines() if line.strip()
        ][:500]
    elif backend == "iptables":
        code, out, err = await _run(["iptables", "-L", "-n", "-v", "--line-numbers"])
        details["raw"] = out if code == 0 else err
        details["rules"] = [
            {"details": line} for line in details["raw"].splitlines() if line.strip()
        ]

    for path in ("/var/log/ufw.log", "/var/log/kern.log", "/var/log/messages"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            drops = [
                ln.rstrip()
                for ln in lines[-max(200, n * 2) :]
                if re.search(r"UFW|DROP|REJECT|firewall", ln, re.I)
            ]
            if drops:
                details["log_tail"] = drops[-n:]
                break
        except (FileNotFoundError, PermissionError):
            continue

    return details


def _valid_ip_or_cidr(value: str) -> bool:
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


async def firewall_action(
    action: str,
    *,
    rule: str | None = None,
    number: int | None = None,
    port: str | None = None,
    proto: str = "tcp",
    zone: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """
    Common:
      enable|disable|reload
    ufw:
      allow|deny|reject (+ rule like '22/tcp' or port+proto), delete (by number)
    firewalld:
      add-port|remove-port (port like 443/tcp or port+proto), add-service|remove-service
    """
    action = (action or "").strip().lower()
    overview = await collect_firewall_overview()
    backend = overview.get("backend") or "none"
    if backend == "none":
        return {"ok": False, "error": "Firewall backend not detected"}

    if action in ("enable", "disable", "reload"):
        if backend == "ufw":
            ufw = shutil.which("ufw") or "/usr/sbin/ufw"
            if action == "enable":
                code, out, err = await run_privileged([ufw, "--force", "enable"])
            elif action == "disable":
                code, out, err = await run_privileged([ufw, "--force", "disable"])
            else:
                code, out, err = await run_privileged([ufw, "reload"])
            if code != 0:
                return {"ok": False, "error": (err or out or "ufw failed").strip()[:400]}
            return {"ok": True, "action": action, "backend": backend}
        if backend == "firewalld":
            if action == "reload":
                code, out, err = await run_privileged(["firewall-cmd", "--reload"])
            elif action == "enable":
                code, out, err = await run_privileged(["systemctl", "start", "firewalld"])
            else:
                code, out, err = await run_privileged(["systemctl", "stop", "firewalld"])
            if code != 0:
                return {"ok": False, "error": (err or out or "firewalld failed").strip()[:400]}
            return {"ok": True, "action": action, "backend": backend}
        return {"ok": False, "error": f"{action} is supported for ufw/firewalld"}

    if backend == "ufw":
        ufw = shutil.which("ufw") or "/usr/sbin/ufw"
        if action == "delete":
            if number is None or int(number) < 1:
                return {"ok": False, "error": "Specify a rule number"}
            # ufw --force delete N
            code, out, err = await run_privileged([ufw, "--force", "delete", str(int(number))])
            if code != 0:
                return {"ok": False, "error": (err or out or "delete failed").strip()[:400]}
            return {"ok": True, "action": "delete", "number": int(number)}

        if action in ("allow", "deny", "reject", "limit"):
            spec = (rule or "").strip()
            if not spec and port:
                p = str(port).strip()
                pr = (proto or "tcp").lower()
                if not re.fullmatch(r"\d{1,5}(?:-\d{1,5})?", p):
                    return {"ok": False, "error": "Invalid port"}
                if pr not in ("tcp", "udp", "any"):
                    return {"ok": False, "error": "proto: tcp|udp|any"}
                spec = f"{p}/{pr}" if pr != "any" else p
            if not spec or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,80}", spec):
                return {"ok": False, "error": "Invalid rule (example: 22/tcp)"}
            cmd = [ufw, action]
            if source:
                if not _valid_ip_or_cidr(source):
                    return {"ok": False, "error": "Invalid source"}
                cmd.extend(["from", source.strip(), "to", "any", "port"])
                # if spec is 22/tcp split
                m = re.fullmatch(r"(\d{1,5}(?:-\d{1,5})?)(?:/(tcp|udp))?", spec)
                if not m:
                    return {"ok": False, "error": "For from=source use port[/proto]"}
                cmd.append(m.group(1))
                if m.group(2):
                    cmd.extend(["proto", m.group(2)])
            else:
                cmd.append(spec)
            code, out, err = await run_privileged(cmd)
            if code != 0:
                return {"ok": False, "error": (err or out or f"ufw {action} failed").strip()[:400]}
            return {"ok": True, "action": action, "rule": spec, "backend": "ufw"}

        return {"ok": False, "error": f"Unknown action for ufw: {action}"}

    if backend == "firewalld":
        zargs: list[str] = []
        if zone:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", zone):
                return {"ok": False, "error": "Invalid zone"}
            zargs = [f"--zone={zone}"]

        if action in ("add-port", "remove-port"):
            p = (port or rule or "").strip()
            pr = (proto or "tcp").lower()
            if "/" in p:
                port_spec = p
            else:
                if not re.fullmatch(r"\d{1,5}(-\d{1,5})?", p):
                    return {"ok": False, "error": "Invalid port"}
                if pr not in ("tcp", "udp", "sctp", "dccp"):
                    return {"ok": False, "error": "Invalid proto"}
                port_spec = f"{p}/{pr}"
            if not re.fullmatch(r"\d{1,5}(-\d{1,5})?/(tcp|udp|sctp|dccp)", port_spec):
                return {"ok": False, "error": "Port format: 443/tcp"}
            flag = f"--{action}={port_spec}"
            code, out, err = await run_privileged(
                ["firewall-cmd", "--permanent", *zargs, flag]
            )
            if code != 0:
                return {"ok": False, "error": (err or out or "firewall-cmd failed").strip()[:400]}
            await run_privileged(["firewall-cmd", "--reload"])
            return {"ok": True, "action": action, "port": port_spec, "backend": "firewalld"}

        if action in ("add-service", "remove-service"):
            svc = (rule or port or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", svc):
                return {"ok": False, "error": "Invalid service name"}
            flag = f"--{action}={svc}"
            code, out, err = await run_privileged(
                ["firewall-cmd", "--permanent", *zargs, flag]
            )
            if code != 0:
                return {"ok": False, "error": (err or out or "firewall-cmd failed").strip()[:400]}
            await run_privileged(["firewall-cmd", "--reload"])
            return {"ok": True, "action": action, "service": svc, "backend": "firewalld"}

        return {"ok": False, "error": f"Unknown action for firewalld: {action}"}

    return {
        "ok": False,
        "error": f"Rule management for backend “{backend}” is not supported (use ufw or firewalld)",
    }
