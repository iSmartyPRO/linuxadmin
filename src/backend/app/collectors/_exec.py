"""Shared privileged subprocess helpers for collectors."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


async def run_cmd(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
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


async def run_privileged(argv: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    code, out, err = await run_cmd(argv, timeout=timeout)
    if code == 0:
        return code, out, err
    sudo = shutil.which("sudo")
    if not sudo:
        return code, out, err or "Permission denied (root or sudo required)"
    return await run_cmd([sudo, "-n", *argv], timeout=timeout)


def which_or(path: str, fallback: str) -> str:
    return shutil.which(path) or fallback


def safe_unit_name(name: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_.@:-]+", name or ""))


def safe_iface(name: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name or ""))
