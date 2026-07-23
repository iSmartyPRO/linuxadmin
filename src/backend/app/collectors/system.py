from __future__ import annotations

import os
import platform
import socket
import time
from typing import Any

import psutil

_prev_net: dict[str, Any] | None = None
_prev_net_ts: float | None = None
_prev_disk_io: Any | None = None
_prev_disk_io_ts: float | None = None


def _rate(prev: int, curr: int, dt: float) -> float:
    if dt <= 0:
        return 0.0
    return max(0.0, (curr - prev) / dt)


def collect_system_metrics() -> dict[str, Any]:
    global _prev_net, _prev_net_ts, _prev_disk_io, _prev_disk_io_ts

    now = time.time()
    cpu_percent = psutil.cpu_percent(interval=None)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    boot = psutil.boot_time()

    disks = []
    root_percent = None
    for part in psutil.disk_partitions(all=False):
        if part.fstype in ("", "squashfs", "tmpfs", "devtmpfs", "overlay"):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        item = {
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        }
        disks.append(item)
        if part.mountpoint == "/":
            root_percent = usage.percent

    disk_io = psutil.disk_io_counters()
    disk_read_rate = disk_write_rate = 0.0
    if disk_io and _prev_disk_io and _prev_disk_io_ts:
        dt = now - _prev_disk_io_ts
        disk_read_rate = _rate(_prev_disk_io.read_bytes, disk_io.read_bytes, dt)
        disk_write_rate = _rate(_prev_disk_io.write_bytes, disk_io.write_bytes, dt)
    _prev_disk_io = disk_io
    _prev_disk_io_ts = now

    net_io = psutil.net_io_counters(pernic=True)
    interfaces = []
    total_sent_rate = total_recv_rate = 0.0
    if _prev_net and _prev_net_ts:
        dt = now - _prev_net_ts
        for name, counters in net_io.items():
            if name.startswith("lo"):
                continue
            prev = _prev_net.get(name)
            if not prev:
                continue
            sent_rate = _rate(prev.bytes_sent, counters.bytes_sent, dt)
            recv_rate = _rate(prev.bytes_recv, counters.bytes_recv, dt)
            total_sent_rate += sent_rate
            total_recv_rate += recv_rate
            interfaces.append(
                {
                    "name": name,
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                    "bytes_sent_rate": sent_rate,
                    "bytes_recv_rate": recv_rate,
                    "packets_sent": counters.packets_sent,
                    "packets_recv": counters.packets_recv,
                }
            )
    else:
        for name, counters in net_io.items():
            if name.startswith("lo"):
                continue
            interfaces.append(
                {
                    "name": name,
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                    "bytes_sent_rate": 0.0,
                    "bytes_recv_rate": 0.0,
                    "packets_sent": counters.packets_sent,
                    "packets_recv": counters.packets_recv,
                }
            )
    _prev_net = net_io
    _prev_net_ts = now

    processes = []
    for proc in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_percent", "status"]
    ):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"],
                    "username": info.get("username"),
                    "cpu_percent": info.get("cpu_percent") or 0.0,
                    "memory_percent": info.get("memory_percent") or 0.0,
                    "status": info.get("status"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
    top_processes = processes[:20]

    temperatures: list[dict[str, Any]] = []
    try:
        temps = psutil.sensors_temperatures() or {}
        for chip, entries in temps.items():
            for entry in entries:
                temperatures.append(
                    {
                        "chip": chip,
                        "label": entry.label or chip,
                        "current": entry.current,
                        "high": entry.high,
                        "critical": entry.critical,
                    }
                )
    except Exception:
        pass

    uname = platform.uname()
    os_release = _read_os_release()
    pretty = os_release.get("PRETTY_NAME") or os_release.get("NAME") or uname.system
    virt = _detect_virt()
    return {
        "timestamp": now,
        "host": {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
            "os": pretty,
            "os_name": os_release.get("NAME") or uname.system,
            "os_id": (os_release.get("ID") or "").lower(),
            "os_id_like": (os_release.get("ID_LIKE") or "").lower(),
            "os_version": os_release.get("VERSION") or os_release.get("VERSION_ID"),
            "os_version_id": os_release.get("VERSION_ID"),
            "os_codename": os_release.get("VERSION_CODENAME") or os_release.get("UBUNTU_CODENAME"),
            "os_pretty_name": pretty,
            "os_home_url": os_release.get("HOME_URL"),
            "os_support_url": os_release.get("SUPPORT_URL"),
            "os_release": os_release,
            "kernel": uname.release,
            "kernel_version": uname.version,
            "system": uname.system,
            "arch": uname.machine,
            "processor": _cpu_model(),
            "virtualization": virt,
            "boot_time": boot,
            "uptime_seconds": now - boot,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "cpu": {
            "percent": cpu_percent,
            "per_cpu": per_cpu,
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "load_avg": {"1": load[0], "5": load[1], "15": load[2]},
        },
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        },
        "swap": {
            "total": swap.total,
            "used": swap.used,
            "percent": swap.percent,
        },
        "disks": disks,
        "disk_io": {
            "read_bytes_rate": disk_read_rate,
            "write_bytes_rate": disk_write_rate,
        },
        "network": {
            "interfaces": interfaces,
            "bytes_sent_rate": total_sent_rate,
            "bytes_recv_rate": total_recv_rate,
        },
        "processes": top_processes,
        "temperatures": temperatures,
        "summary": {
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "swap_percent": swap.percent,
            "load_1": load[0],
            "load_5": load[1],
            "load_15": load[2],
            "disk_percent": root_percent,
            "net_bytes_sent_rate": total_sent_rate,
            "net_bytes_recv_rate": total_recv_rate,
        },
    }


def _read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    data[key] = val.strip().strip('"')
            if data:
                break
        except OSError:
            continue
    return data


def _detect_virt() -> str | None:
    import shutil
    import subprocess

    binary = shutil.which("systemd-detect-virt")
    if binary:
        try:
            r = subprocess.run([binary], capture_output=True, text=True, timeout=2)
            val = (r.stdout or "").strip()
            if val and val != "none":
                return val
            if val == "none":
                return "bare-metal"
        except Exception:
            pass
    for path in (
        "/sys/class/dmi/id/product_name",
        "/sys/devices/virtual/dmi/id/product_name",
    ):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                name = f.read().strip()
                if name:
                    return name
        except OSError:
            continue
    return None


def _cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[-1].strip()
    except OSError:
        pass
    return platform.processor() or None
