from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any

UNIT_RE = re.compile(r"^[A-Za-z0-9@_.\\-]+\.(service|socket|timer|target|mount|path|slice)$")
ACTION_ALLOW = {"start", "stop", "restart", "reload", "try-reload", "enable", "disable", "mask", "unmask"}


async def _run(cmd: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except (FileNotFoundError, asyncio.TimeoutError, PermissionError) as exc:
        return 1, "", str(exc)


async def _run_privileged(argv: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    code, out, err = await _run(argv, timeout=timeout)
    if code == 0:
        return code, out, err
    combined = (err or out or "").lower()
    needs_priv = any(
        x in combined
        for x in ("permission denied", "access denied", "interactive authentication", "auth")
    )
    sudo = shutil.which("sudo")
    if not sudo:
        return code, out, err
    if needs_priv or code != 0:
        return await _run([sudo, "-n", *argv], timeout=timeout)
    return code, out, err


def _systemctl() -> str | None:
    return shutil.which("systemctl")


def _valid_unit(name: str) -> bool:
    return bool(UNIT_RE.fullmatch(name or ""))


async def collect_services_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    show_inactive = bool(opts.get("show_inactive", True))
    binary = _systemctl()
    if not binary:
        return {
            "available": False,
            "error": "systemctl not found (systemd required)",
            "services": [],
            "counts": {},
        }

    # JSON output is stable on modern systemd
    code, out, err = await _run(
        [
            binary,
            "list-units",
            "--type=service",
            "--all",
            "--no-pager",
            "--no-legend",
            "--output=json",
        ],
        timeout=25.0,
    )
    services: list[dict[str, Any]] = []
    if code == 0 and out.strip().startswith("["):
        try:
            raw = json.loads(out)
            for item in raw:
                unit = item.get("unit") or item.get("Unit") or ""
                if not unit.endswith(".service"):
                    continue
                load = item.get("load") or item.get("LoadState") or ""
                active = item.get("active") or item.get("ActiveState") or ""
                sub = item.get("sub") or item.get("SubState") or ""
                desc = item.get("description") or item.get("Description") or ""
                if not show_inactive and active not in ("active", "activating", "reloading"):
                    continue
                services.append(
                    {
                        "unit": unit,
                        "load": load,
                        "active": active,
                        "sub": sub,
                        "description": desc,
                    }
                )
        except json.JSONDecodeError:
            pass

    if not services:
        # Fallback plain text
        code, out, err = await _run(
            [binary, "list-units", "--type=service", "--all", "--no-pager", "--plain", "--no-legend"],
            timeout=25.0,
        )
        if code != 0:
            return {
                "available": False,
                "error": (err or out or "systemctl failed").strip()[:300],
                "services": [],
                "counts": {},
            }
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
            desc = parts[4] if len(parts) > 4 else ""
            if not unit.endswith(".service"):
                continue
            if not show_inactive and active not in ("active", "activating", "reloading"):
                continue
            services.append(
                {
                    "unit": unit,
                    "load": load,
                    "active": active,
                    "sub": sub,
                    "description": desc,
                }
            )

    # Enabled state (batch via list-unit-files)
    enabled_map: dict[str, str] = {}
    code, out, _ = await _run(
        [binary, "list-unit-files", "--type=service", "--no-pager", "--no-legend", "--output=json"],
        timeout=25.0,
    )
    if code == 0 and out.strip().startswith("["):
        try:
            for item in json.loads(out):
                u = item.get("unit_file") or item.get("UnitFile") or item.get("unit") or ""
                state = item.get("state") or item.get("State") or ""
                if u:
                    enabled_map[u] = state
        except json.JSONDecodeError:
            pass
    else:
        code, out, _ = await _run(
            [binary, "list-unit-files", "--type=service", "--no-pager", "--no-legend"],
            timeout=25.0,
        )
        if code == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    enabled_map[parts[0]] = parts[1]

    for s in services:
        s["enabled"] = enabled_map.get(s["unit"], "unknown")

    services.sort(key=lambda s: (s["active"] != "active", s["unit"]))

    counts = {
        "total": len(services),
        "active": sum(1 for s in services if s["active"] == "active"),
        "failed": sum(1 for s in services if s["active"] == "failed"),
        "inactive": sum(1 for s in services if s["active"] == "inactive"),
    }

    return {
        "available": True,
        "error": None,
        "services": services,
        "counts": counts,
        "binary": binary,
    }


async def collect_service_details(unit: str, log_lines: int = 80) -> dict[str, Any]:
    if not _valid_unit(unit):
        return {"available": False, "error": "Invalid unit name"}
    binary = _systemctl()
    if not binary:
        return {"available": False, "error": "systemctl not found"}

    n = max(10, min(500, int(log_lines or 80)))
    props = [
        "Id",
        "Description",
        "LoadState",
        "ActiveState",
        "SubState",
        "UnitFileState",
        "FragmentPath",
        "DropInPaths",
        "MainPID",
        "ExecMainStartTimestamp",
        "ActiveEnterTimestamp",
        "MemoryCurrent",
        "CPUUsageNSec",
        "TasksCurrent",
        "User",
        "Group",
        "Restart",
        "FragmentPath",
    ]
    code, out, err = await _run(
        [binary, "show", unit, "--no-pager", f"--property={','.join(props)}"],
        timeout=10.0,
    )
    info: dict[str, Any] = {}
    if code == 0:
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v

    code2, status_out, _ = await _run([binary, "status", unit, "--no-pager", "-l"], timeout=10.0)
    # status often returns non-zero for inactive — still useful
    journal: list[str] = []
    jctl = shutil.which("journalctl")
    if jctl:
        jc, jout, _ = await _run(
            [jctl, "-u", unit, "-n", str(n), "--no-pager", "-o", "short-iso"],
            timeout=12.0,
        )
        if jc == 0:
            journal = [ln for ln in jout.splitlines() if ln.strip()]

    return {
        "available": True,
        "unit": unit,
        "info": info,
        "status_text": status_out if status_out else err,
        "journal": journal,
        "active": info.get("ActiveState"),
        "sub": info.get("SubState"),
        "enabled": info.get("UnitFileState"),
        "description": info.get("Description"),
        "main_pid": info.get("MainPID"),
        "fragment": info.get("FragmentPath"),
    }


async def service_action(unit: str, action: str) -> dict[str, Any]:
    if not _valid_unit(unit):
        return {"ok": False, "error": "Invalid unit name"}
    if action not in ACTION_ALLOW:
        return {"ok": False, "error": f"Action not allowed: {action}"}
    binary = _systemctl()
    if not binary:
        return {"ok": False, "error": "systemctl not found"}

    code, out, err = await _run_privileged([binary, action, unit, "--no-block"], timeout=45.0)
    # enable/disable often don't need --no-block the same way; retry without for enable/disable
    if code != 0 and action in ("enable", "disable", "mask", "unmask"):
        code, out, err = await _run_privileged([binary, action, unit], timeout=45.0)

    if code != 0:
        return {"ok": False, "error": (err or out or f"systemctl {action} failed").strip()[:400]}
    return {"ok": True, "unit": unit, "action": action}
