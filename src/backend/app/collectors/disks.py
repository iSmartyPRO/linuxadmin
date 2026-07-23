"""Disk partitions overview and directory size browser."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

# Virtual / pseudo filesystems — skip in overview and as browse roots
_SKIP_FSTYPES = {
    "",
    "squashfs",
    "tmpfs",
    "devtmpfs",
    "overlay",
    "proc",
    "sysfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "pstore",
    "bpf",
    "tracefs",
    "debugfs",
    "securityfs",
    "hugetlbfs",
    "mqueue",
    "fusectl",
    "configfs",
    "rpc_pipefs",
    "binfmt_misc",
    "autofs",
    "nsfs",
}

_DENY_PREFIXES = ("/proc", "/sys", "/dev", "/run/user")


def collect_disks_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    include_pseudo = bool(opts.get("include_pseudo", False))
    partitions: list[dict[str, Any]] = []

    for part in psutil.disk_partitions(all=include_pseudo):
        if not include_pseudo and part.fstype.lower() in _SKIP_FSTYPES:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        try:
            st = os.statvfs(part.mountpoint)
            inodes_total = int(st.f_files) if st.f_files else None
            inodes_free = int(st.f_ffree) if st.f_ffree is not None else None
            inodes_used = (
                (inodes_total - inodes_free)
                if inodes_total is not None and inodes_free is not None
                else None
            )
            inodes_percent = (
                round(100.0 * inodes_used / inodes_total, 1)
                if inodes_total and inodes_used is not None
                else None
            )
        except OSError:
            inodes_total = inodes_free = inodes_used = inodes_percent = None

        partitions.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
                "inodes_total": inodes_total,
                "inodes_used": inodes_used,
                "inodes_free": inodes_free,
                "inodes_percent": inodes_percent,
            }
        )

    partitions.sort(key=lambda p: (p["mountpoint"] != "/", p["mountpoint"]))

    io_total = psutil.disk_io_counters()
    io_perdisk = psutil.disk_io_counters(perdisk=True) or {}
    io_devices = []
    for name, counters in sorted(io_perdisk.items()):
        io_devices.append(
            {
                "name": name,
                "read_bytes": counters.read_bytes,
                "write_bytes": counters.write_bytes,
                "read_count": counters.read_count,
                "write_count": counters.write_count,
                "read_time_ms": getattr(counters, "read_time", None),
                "write_time_ms": getattr(counters, "write_time", None),
                "busy_time_ms": getattr(counters, "busy_time", None),
            }
        )

    return {
        "available": True,
        "partitions": partitions,
        "count": len(partitions),
        "io": {
            "read_bytes": getattr(io_total, "read_bytes", 0) if io_total else 0,
            "write_bytes": getattr(io_total, "write_bytes", 0) if io_total else 0,
            "read_count": getattr(io_total, "read_count", 0) if io_total else 0,
            "write_count": getattr(io_total, "write_count", 0) if io_total else 0,
            "devices": io_devices,
        },
    }


def _allowed_roots(include_pseudo: bool = False) -> list[str]:
    roots: list[str] = []
    for part in psutil.disk_partitions(all=include_pseudo):
        if not include_pseudo and part.fstype.lower() in _SKIP_FSTYPES:
            continue
        try:
            roots.append(os.path.realpath(part.mountpoint))
        except OSError:
            continue
    # Always allow / as fallback if somehow missing
    if "/" not in roots:
        roots.append("/")
    # Longer mounts first for prefix matching
    roots.sort(key=len, reverse=True)
    return roots


def _is_under_root(path: str, roots: list[str]) -> str | None:
    """Return matching mount root if path is under an allowed root (longest match)."""
    for root in roots:
        if root == "/":
            continue
        if path == root or path.startswith(root.rstrip("/") + "/"):
            return root
    if any(r == "/" for r in roots):
        return "/"
    return None


def _is_denied(path: str) -> bool:
    for prefix in _DENY_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _entry_size_du(path: str, timeout: float) -> int | None:
    binary = shutil.which("du")
    if not binary:
        return None
    try:
        r = subprocess.run(
            [binary, "-sb", path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            return None
        first = (r.stdout or "").strip().split()[0]
        return int(first)
    except (subprocess.TimeoutExpired, ValueError, OSError, IndexError):
        return None


def _dir_size_walk(path: str, deadline: float, max_files: int = 200_000) -> tuple[int, bool]:
    """Return (size, truncated)."""
    total = 0
    count = 0
    truncated = False
    try:
        for root, dirs, files in os.walk(path, followlinks=False):
            if time.monotonic() > deadline:
                truncated = True
                break
            # Skip denied / special
            dirs[:] = [
                d
                for d in dirs
                if not _is_denied(os.path.join(root, d))
            ]
            for name in files:
                if time.monotonic() > deadline or count >= max_files:
                    truncated = True
                    break
                fp = os.path.join(root, name)
                try:
                    st = os.lstat(fp)
                    if not os.path.islink(fp):
                        total += st.st_size
                        count += 1
                except OSError:
                    continue
            if truncated:
                break
    except OSError:
        pass
    return total, truncated


def _children_sizes_du(path: str, timeout: float) -> dict[str, int] | None:
    binary = shutil.which("du")
    if not binary:
        return None
    try:
        r = subprocess.run(
            [binary, "-sb", "--max-depth=1", path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0 and not (r.stdout or "").strip():
            # BusyBox / BSD may use -d 1
            r = subprocess.run(
                [binary, "-sb", "-d", "1", path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        mapping: dict[str, int] = {}
        for line in (r.stdout or "").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            mapping[os.path.realpath(parts[1])] = size
        return mapping
    except (subprocess.TimeoutExpired, OSError):
        return None


def browse_path(path: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    max_entries = int(opts.get("max_entries", 500))
    scan_timeout = float(opts.get("scan_timeout_seconds", 25))
    include_pseudo = bool(opts.get("include_pseudo", False))

    raw = (path or "/").strip() or "/"
    try:
        resolved = os.path.realpath(raw)
    except OSError as e:
        return {"available": False, "error": f"Invalid path: {e}", "entries": []}

    if _is_denied(resolved):
        return {
            "available": False,
            "error": f"Path is forbidden for browsing: {resolved}",
            "path": resolved,
            "entries": [],
        }

    roots = _allowed_roots(include_pseudo)
    mount_root = _is_under_root(resolved, roots)
    if mount_root is None:
        return {
            "available": False,
            "error": "Path is outside mounted filesystems",
            "path": resolved,
            "entries": [],
        }

    if not os.path.exists(resolved):
        return {
            "available": False,
            "error": "Path does not exist",
            "path": resolved,
            "entries": [],
        }
    if not os.path.isdir(resolved):
        return {
            "available": False,
            "error": "Path is not a directory",
            "path": resolved,
            "entries": [],
        }

    try:
        usage = psutil.disk_usage(mount_root if mount_root != "/" or resolved.startswith("/") else resolved)
    except OSError:
        try:
            usage = psutil.disk_usage(resolved)
        except OSError as e:
            return {"available": False, "error": str(e), "path": resolved, "entries": []}

    deadline = time.monotonic() + scan_timeout
    size_map = _children_sizes_du(resolved, min(scan_timeout, 20.0))
    truncated = False
    entries: list[dict[str, Any]] = []

    try:
        with os.scandir(resolved) as it:
            for entry in it:
                if len(entries) >= max_entries:
                    truncated = True
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue

                is_link = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                kind = "symlink" if is_link else "dir" if is_dir else "file" if is_file else "other"
                full = os.path.join(resolved, entry.name)

                # Hide pseudo / kernel trees from size analysis (misleading du numbers)
                if _is_denied(full) or _is_denied(os.path.realpath(full) if not is_link else full):
                    continue

                size: int | None = None
                size_truncated = False
                if is_link:
                    size = st.st_size
                elif is_file:
                    size = st.st_size
                elif is_dir:
                    if size_map is not None:
                        size = size_map.get(os.path.realpath(full))
                        if size is None:
                            # try non-realpath key
                            size = size_map.get(full)
                    if size is None and time.monotonic() < deadline:
                        remaining = max(0.5, deadline - time.monotonic())
                        du_size = _entry_size_du(full, min(remaining, 8.0))
                        if du_size is not None:
                            size = du_size
                        else:
                            walked, size_truncated = _dir_size_walk(
                                full, min(deadline, time.monotonic() + remaining)
                            )
                            size = walked
                            if size_truncated:
                                truncated = True
                    elif size is None:
                        truncated = True

                entries.append(
                    {
                        "name": entry.name,
                        "path": full,
                        "kind": kind,
                        "size": size,
                        "size_truncated": size_truncated,
                        "mtime": st.st_mtime,
                        "mode": oct(st.st_mode & 0o777),
                        "nlink": st.st_nlink,
                        "uid": st.st_uid,
                        "gid": st.st_gid,
                        "browsable": is_dir and not is_link,
                    }
                )
    except PermissionError:
        return {
            "available": False,
            "error": f"Access denied: {resolved}",
            "path": resolved,
            "entries": [],
        }
    except OSError as e:
        return {
            "available": False,
            "error": str(e),
            "path": resolved,
            "entries": [],
        }

    # Parent total from du map or sum
    parent_size = None
    if size_map is not None:
        parent_size = size_map.get(os.path.realpath(resolved)) or size_map.get(resolved)
    if parent_size is None:
        known = [e["size"] for e in entries if e["size"] is not None]
        parent_size = sum(known) if known else None

    entries.sort(key=lambda e: (-(e["size"] or 0), e["name"].lower()))

    # Breadcrumb segments
    parts: list[dict[str, str]] = [{"name": "/", "path": "/"}]
    if resolved != "/":
        accum = ""
        for seg in resolved.strip("/").split("/"):
            accum += "/" + seg
            parts.append({"name": seg, "path": accum})

    return {
        "available": True,
        "path": resolved,
        "mount_root": mount_root,
        "parent": str(Path(resolved).parent) if resolved != "/" else None,
        "breadcrumb": parts,
        "entries": entries,
        "entry_count": len(entries),
        "truncated": truncated,
        "parent_size": parent_size,
        "disk": {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        },
        "scan_seconds": round(scan_timeout - max(0.0, deadline - time.monotonic()), 2),
    }
