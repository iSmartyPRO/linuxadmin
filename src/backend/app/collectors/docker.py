from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any

_SIZE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kKmMgGtTpP]?i?[bB])",
)
_PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
_PAIR_RE = re.compile(r"^\s*(?P<a>.+?)\s*/\s*(?P<b>.+?)\s*$")
_PS_SIZE_RE = re.compile(
    r"^\s*(?P<rw>.+?)\s*\(\s*virtual\s+(?P<virtual>.+?)\s*\)\s*$",
    re.IGNORECASE,
)

_UNIT_BYTES = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


def _parse_byte_size(text: Any) -> int | None:
    """Parse Docker human sizes (12.3MiB, 1.2kB, 512B) into bytes."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip()
    if not s or s in {"--", "N/A", "n/a"}:
        return None
    m = _SIZE_RE.search(s)
    if not m:
        return None
    value = float(m.group("value"))
    unit = m.group("unit").lower()
    if unit == "k":
        unit = "kb"
    elif unit == "m":
        unit = "mb"
    elif unit == "g":
        unit = "gb"
    elif unit.endswith("ib") or unit == "b":
        pass
    elif unit.endswith("b") and not unit.endswith("ib"):
        pass
    factor = _UNIT_BYTES.get(unit)
    if factor is None:
        return None
    return int(value * factor)


def _parse_percent(text: Any) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _PERCENT_RE.search(str(text))
    if not m:
        return None
    return float(m.group("value"))


def _parse_pair(text: Any) -> tuple[str | None, str | None]:
    if text is None:
        return None, None
    s = str(text).strip()
    m = _PAIR_RE.match(s)
    if not m:
        return None, None
    return m.group("a").strip(), m.group("b").strip()


def _parse_ps_size(text: Any) -> dict[str, Any]:
    """Parse `docker ps --size` Size field: '1.2MB (virtual 234MB)'."""
    out: dict[str, Any] = {
        "size": text,
        "size_rw_bytes": None,
        "size_virtual_bytes": None,
    }
    if not text:
        return out
    s = str(text).strip()
    m = _PS_SIZE_RE.match(s)
    if m:
        rw, virtual = m.group("rw").strip(), m.group("virtual").strip()
        out["size_rw_bytes"] = _parse_byte_size(rw)
        out["size_virtual_bytes"] = _parse_byte_size(virtual)
        return out
    out["size_rw_bytes"] = _parse_byte_size(s)
    return out


def _normalize_stats_row(s: dict[str, Any]) -> dict[str, Any]:
    cpu_raw = s.get("CPUPerc") or s.get("CPUPercentage")
    mem_usage_raw = s.get("MemUsage") or s.get("MemoryUsage")
    mem_pct_raw = s.get("MemPerc") or s.get("MemoryPercentage")
    net_raw = s.get("NetIO") or s.get("NetworkIO")
    block_raw = s.get("BlockIO")
    pids_raw = s.get("PIDs")

    mem_used_s, mem_limit_s = _parse_pair(mem_usage_raw)
    net_rx_s, net_tx_s = _parse_pair(net_raw)
    block_r_s, block_w_s = _parse_pair(block_raw)

    pids: int | None
    try:
        pids = int(pids_raw) if pids_raw not in (None, "") else None
    except (TypeError, ValueError):
        pids = None

    return {
        "id": (s.get("ID") or s.get("Container") or "")[:12],
        "name": (s.get("Name") or "").lstrip("/"),
        "cpu_percent": _parse_percent(cpu_raw),
        "cpu_percent_raw": cpu_raw,
        "mem_usage": mem_usage_raw,
        "mem_percent": _parse_percent(mem_pct_raw),
        "mem_percent_raw": mem_pct_raw,
        "mem_used_bytes": _parse_byte_size(mem_used_s),
        "mem_limit_bytes": _parse_byte_size(mem_limit_s),
        "net_io": net_raw,
        "net_rx_bytes": _parse_byte_size(net_rx_s),
        "net_tx_bytes": _parse_byte_size(net_tx_s),
        "block_io": block_raw,
        "block_read_bytes": _parse_byte_size(block_r_s),
        "block_write_bytes": _parse_byte_size(block_w_s),
        "pids": pids,
    }


def _stats_lookup(stats_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in stats_list:
        cid = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        if cid:
            by_key[cid] = row
            by_key[cid[:12]] = row
        if name:
            by_key[name] = row
            by_key[name.lstrip("/")] = row
    return by_key


def _sum_optional(rows: list[dict[str, Any]], key: str) -> int | float | None:
    total = 0.0
    seen = False
    for row in rows:
        val = row.get(key)
        if val is None:
            continue
        try:
            total += float(val)
            seen = True
        except (TypeError, ValueError):
            continue
    if not seen:
        return None
    if key.endswith("_bytes") or key == "pids":
        return int(total)
    return total


def _normalize_disk_usage(disk_usage: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(disk_usage, list):
        src = disk_usage
    elif isinstance(disk_usage, dict):
        src = [disk_usage]
    else:
        return rows
    for item in src:
        if not isinstance(item, dict):
            continue
        size_raw = item.get("Size") or item.get("size")
        reclaim_raw = item.get("Reclaimable") or item.get("reclaimable")
        # Reclaimable often looks like "1.2GB (45%)"
        reclaim_size = None
        if reclaim_raw is not None:
            reclaim_size = _parse_byte_size(str(reclaim_raw).split("(")[0].strip())
        rows.append(
            {
                "type": item.get("Type") or item.get("type"),
                "size": size_raw,
                "size_bytes": _parse_byte_size(size_raw),
                "active": item.get("Active") or item.get("active"),
                "reclaimable": reclaim_raw,
                "reclaimable_bytes": reclaim_size,
            }
        )
    return rows


def _build_resources_total(
    containers_list: list[dict[str, Any]],
    *,
    host_cpus: int | None,
    host_memory_bytes: int | None,
    disk_usage: Any,
) -> dict[str, Any]:
    """Aggregate live stats + disk footprint across all containers."""
    with_stats = [
        c
        for c in containers_list
        if c.get("cpu_percent") is not None
        or c.get("mem_used_bytes") is not None
        or c.get("pids") is not None
    ]
    all_rows = containers_list

    cpu_sum = _sum_optional(with_stats, "cpu_percent")
    mem_used = _sum_optional(with_stats, "mem_used_bytes")
    net_rx = _sum_optional(with_stats, "net_rx_bytes")
    net_tx = _sum_optional(with_stats, "net_tx_bytes")
    block_r = _sum_optional(with_stats, "block_read_bytes")
    block_w = _sum_optional(with_stats, "block_write_bytes")
    pids = _sum_optional(with_stats, "pids")
    size_rw = _sum_optional(all_rows, "size_rw_bytes")

    ncpu = int(host_cpus) if host_cpus else 0
    # docker stats CPU%: ~100% ≈ one core; convert to host-wide %
    cpu_of_host = None
    if cpu_sum is not None and ncpu > 0:
        cpu_of_host = float(cpu_sum) / ncpu

    mem_of_host = None
    if mem_used is not None and host_memory_bytes:
        mem_of_host = (float(mem_used) / float(host_memory_bytes)) * 100.0

    disk_rows = _normalize_disk_usage(disk_usage)
    disk_by_type = {str(r.get("type") or "").lower(): r for r in disk_rows}

    return {
        "containers_total": len(all_rows),
        "containers_with_stats": len(with_stats),
        "host_cpus": ncpu or None,
        "host_memory_bytes": host_memory_bytes,
        "cpu_percent": round(float(cpu_sum), 2) if cpu_sum is not None else None,
        "cpu_percent_of_host": round(cpu_of_host, 2) if cpu_of_host is not None else None,
        "mem_used_bytes": mem_used,
        "mem_percent_of_host": round(mem_of_host, 2) if mem_of_host is not None else None,
        "net_rx_bytes": net_rx,
        "net_tx_bytes": net_tx,
        "net_total_bytes": (net_rx or 0) + (net_tx or 0) if net_rx is not None or net_tx is not None else None,
        "block_read_bytes": block_r,
        "block_write_bytes": block_w,
        "block_total_bytes": (block_r or 0) + (block_w or 0)
        if block_r is not None or block_w is not None
        else None,
        "size_rw_bytes": size_rw,
        "pids": pids,
        "disk": disk_rows,
        "disk_images_bytes": (disk_by_type.get("images") or {}).get("size_bytes"),
        "disk_containers_bytes": (disk_by_type.get("containers") or {}).get("size_bytes"),
        "disk_volumes_bytes": (disk_by_type.get("local volumes") or disk_by_type.get("volumes") or {}).get(
            "size_bytes"
        ),
        "disk_build_cache_bytes": (disk_by_type.get("build cache") or {}).get("size_bytes"),
        "disk_total_bytes": _sum_optional(disk_rows, "size_bytes"),
    }


async def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
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


async def _systemd_active(unit: str) -> bool:
    code, out, _ = await _run(["systemctl", "is-active", unit], timeout=3.0)
    return code == 0 and out.strip() == "active"


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        elif isinstance(obj, list):
            rows.extend(x for x in obj if isinstance(x, dict))
    return rows


def _parse_json_blob(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some docker versions print one JSON object per line for system df
        rows = _parse_json_lines(text)
        return rows or None


def _not_installed() -> dict[str, Any]:
    return {
        "installed": False,
        "available": False,
        "active": False,
        "binary": None,
        "version": None,
        "server_version": None,
        "error": None,
        "containers": 0,
        "containers_running": 0,
        "containers_paused": 0,
        "containers_stopped": 0,
        "images": 0,
        "volumes": 0,
        "networks": 0,
    }


async def collect_docker_overview() -> dict[str, Any]:
    """Lightweight check. If docker binary is absent — return immediately (no daemon calls)."""
    binary = shutil.which("docker")
    if not binary:
        return _not_installed()

    result = _not_installed()
    result.update(
        {
            "installed": True,
            "binary": binary,
            "active": await _systemd_active("docker")
            or await _systemd_active("docker.service")
            or await _systemd_active("containerd"),
        }
    )

    # Single cheap probe: client version never needs a running daemon.
    code, out, err = await _run([binary, "version", "--format", "{{json .}}"], timeout=4.0)
    if code == 0:
        payload = _parse_json_blob(out)
        if isinstance(payload, dict):
            client = payload.get("Client") or {}
            server = payload.get("Server") or {}
            result["version"] = client.get("Version") or payload.get("Version")
            if isinstance(server, dict) and server:
                result["server_version"] = server.get("Version")
                result["available"] = True
            else:
                # Client OK, server section empty → daemon likely down
                result["available"] = False
                result["error"] = "Docker daemon unavailable"
    else:
        result["error"] = (err or out or "docker version failed").strip()[:300]

    # Only hit the daemon when version suggests server is reachable,
    # or when we still need a definitive availability check.
    code, out, err = await _run(
        [
            binary,
            "info",
            "--format",
            "{{json .}}",
        ],
        timeout=5.0,
    )
    if code != 0:
        msg = (err or out or "docker info failed").strip()
        result["available"] = False
        # Prefer a short human hint for common permission issues
        if "permission denied" in msg.lower():
            result["error"] = "No access to Docker socket (add the user to the docker group)"
        elif "Cannot connect" in msg or "Is the docker daemon running" in msg:
            result["error"] = "Docker daemon is not running"
        else:
            result["error"] = msg[:300]
        return result

    info = _parse_json_blob(out)
    if not isinstance(info, dict):
        result["available"] = False
        result["error"] = "Failed to parse docker info"
        return result

    result["available"] = True
    result["active"] = True
    result["error"] = None
    result["server_version"] = info.get("ServerVersion") or result.get("server_version")
    result["containers"] = int(info.get("Containers") or 0)
    result["containers_running"] = int(info.get("ContainersRunning") or 0)
    result["containers_paused"] = int(info.get("ContainersPaused") or 0)
    result["containers_stopped"] = int(info.get("ContainersStopped") or 0)
    result["images"] = int(info.get("Images") or 0)
    result["driver"] = info.get("Driver")
    result["root_dir"] = info.get("DockerRootDir")
    result["operating_system"] = info.get("OperatingSystem")
    result["architecture"] = info.get("Architecture")
    result["cpus"] = info.get("NCPU")
    result["memory_total"] = info.get("MemTotal")
    result["swarm"] = (info.get("Swarm") or {}).get("LocalNodeState")
    result["name"] = info.get("Name")
    return result


async def _docker_json_lines(binary: str, args: list[str], timeout: float = 12.0) -> list[dict[str, Any]]:
    code, out, _ = await _run([binary, *args], timeout=timeout)
    if code != 0:
        return []
    return _parse_json_lines(out)


async def collect_docker_details(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    collect_stats = opts.get("collect_stats", True)
    collect_disk = opts.get("collect_disk", True)
    collect_info = opts.get("collect_info", True)

    overview = await collect_docker_overview()
    empty = {
        **overview,
        "containers_list": [],
        "stats": [],
        "images_list": [],
        "volumes_list": [],
        "networks_list": [],
        "disk_usage": None,
        "resources_total": None,
        "info": None,
    }
    if not overview.get("installed") or not overview.get("available"):
        return empty

    binary = overview["binary"]

    tasks = [
        _docker_json_lines(
            binary,
            ["ps", "-a", "--size", "--no-trunc", "--format", "{{json .}}"],
            timeout=20.0,
        ),
        _docker_json_lines(binary, ["images", "--format", "{{json .}}"]),
        _docker_json_lines(binary, ["volume", "ls", "--format", "{{json .}}"]),
        _docker_json_lines(binary, ["network", "ls", "--format", "{{json .}}"]),
    ]
    if collect_stats:
        tasks.append(
            _docker_json_lines(
                binary,
                ["stats", "--no-stream", "--format", "{{json .}}"],
                timeout=15.0,
            )
        )
    if collect_disk:
        tasks.append(_run([binary, "system", "df", "--format", "{{json .}}"], timeout=12.0))
    if collect_info:
        tasks.append(_run([binary, "info", "--format", "{{json .}}"], timeout=8.0))

    results = await asyncio.gather(*tasks)
    containers, images, volumes, networks = results[0], results[1], results[2], results[3]
    idx = 4
    stats: list[dict[str, Any]] = []
    if collect_stats:
        stats = results[idx]  # type: ignore[assignment]
        idx += 1
    disk_usage = None
    if collect_disk:
        df_code, df_out, _ = results[idx]  # type: ignore[misc]
        idx += 1
        if df_code == 0:
            disk_usage = _parse_json_blob(df_out)
    info = None
    if collect_info:
        info_code, info_out, _ = results[idx]  # type: ignore[misc]
        if info_code == 0:
            info = _parse_json_blob(info_out)

    overview["volumes"] = len(volumes)
    overview["networks"] = len(networks)

    stats_list = [_normalize_stats_row(s) for s in stats]
    stats_by_key = _stats_lookup(stats_list)

    # Normalize container rows for the UI (merge live stats when available)
    containers_list = []
    for c in containers:
        cid = (c.get("ID") or c.get("Id") or "")[:12]
        names = (c.get("Names") or c.get("Name") or "").lstrip("/")
        primary_name = names.split(",")[0].strip() if names else ""
        size_info = _parse_ps_size(c.get("Size"))
        st = stats_by_key.get(cid) or stats_by_key.get(primary_name) or {}
        containers_list.append(
            {
                "id": cid,
                "id_full": c.get("ID") or c.get("Id"),
                "names": names,
                "image": c.get("Image"),
                "status": c.get("Status"),
                "state": c.get("State"),
                "ports": c.get("Ports"),
                "created": c.get("CreatedAt") or c.get("Created"),
                "command": c.get("Command"),
                "size": size_info.get("size"),
                "size_rw_bytes": size_info.get("size_rw_bytes"),
                "size_virtual_bytes": size_info.get("size_virtual_bytes"),
                "networks": c.get("Networks"),
                "mounts": c.get("Mounts"),
                "labels": c.get("Labels"),
                "cpu_percent": st.get("cpu_percent"),
                "mem_percent": st.get("mem_percent"),
                "mem_usage": st.get("mem_usage"),
                "mem_used_bytes": st.get("mem_used_bytes"),
                "mem_limit_bytes": st.get("mem_limit_bytes"),
                "net_io": st.get("net_io"),
                "net_rx_bytes": st.get("net_rx_bytes"),
                "net_tx_bytes": st.get("net_tx_bytes"),
                "block_io": st.get("block_io"),
                "block_read_bytes": st.get("block_read_bytes"),
                "block_write_bytes": st.get("block_write_bytes"),
                "pids": st.get("pids"),
            }
        )

    images_list = []
    for img in images:
        images_list.append(
            {
                "id": (img.get("ID") or img.get("Id") or "")[:12],
                "id_full": img.get("ID") or img.get("Id"),
                "repository": img.get("Repository") or img.get("repository"),
                "tag": img.get("Tag") or img.get("tag"),
                "created": img.get("CreatedAt") or img.get("CreatedSince"),
                "size": img.get("Size"),
                "containers": img.get("Containers"),
                "digest": img.get("Digest"),
            }
        )

    volumes_list = []
    for vol in volumes:
        volumes_list.append(
            {
                "name": vol.get("Name"),
                "driver": vol.get("Driver"),
                "mountpoint": vol.get("Mountpoint"),
                "scope": vol.get("Scope"),
                "labels": vol.get("Labels"),
                "created": vol.get("CreatedAt"),
            }
        )

    networks_list = []
    for net in networks:
        networks_list.append(
            {
                "id": (net.get("ID") or "")[:12],
                "name": net.get("Name"),
                "driver": net.get("Driver"),
                "scope": net.get("Scope"),
                "ipv6": net.get("IPv6"),
                "internal": net.get("Internal"),
                "labels": net.get("Labels"),
                "created": net.get("CreatedAt"),
            }
        )

    host_mem = overview.get("memory_total")
    try:
        host_mem_i = int(host_mem) if host_mem is not None else None
    except (TypeError, ValueError):
        host_mem_i = None
    host_cpus = overview.get("cpus")
    try:
        host_cpus_i = int(host_cpus) if host_cpus is not None else None
    except (TypeError, ValueError):
        host_cpus_i = None

    resources_total = _build_resources_total(
        containers_list,
        host_cpus=host_cpus_i,
        host_memory_bytes=host_mem_i,
        disk_usage=disk_usage,
    )

    return {
        **overview,
        "containers_list": containers_list,
        "stats": stats_list,
        "images_list": images_list,
        "volumes_list": volumes_list,
        "networks_list": networks_list,
        "disk_usage": disk_usage,
        "resources_total": resources_total,
        "info": info,
    }
