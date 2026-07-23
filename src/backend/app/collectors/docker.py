from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any


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
        "info": None,
    }
    if not overview.get("installed") or not overview.get("available"):
        return empty

    binary = overview["binary"]

    tasks = [
        _docker_json_lines(
            binary,
            ["ps", "-a", "--no-trunc", "--format", "{{json .}}"],
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

    # Normalize container rows for the UI
    containers_list = []
    for c in containers:
        containers_list.append(
            {
                "id": (c.get("ID") or c.get("Id") or "")[:12],
                "id_full": c.get("ID") or c.get("Id"),
                "names": (c.get("Names") or c.get("Name") or "").lstrip("/"),
                "image": c.get("Image"),
                "status": c.get("Status"),
                "state": c.get("State"),
                "ports": c.get("Ports"),
                "created": c.get("CreatedAt") or c.get("Created"),
                "command": c.get("Command"),
                "size": c.get("Size"),
                "networks": c.get("Networks"),
                "mounts": c.get("Mounts"),
                "labels": c.get("Labels"),
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

    stats_list = []
    for s in stats:
        stats_list.append(
            {
                "id": (s.get("ID") or s.get("Container") or "")[:12],
                "name": (s.get("Name") or "").lstrip("/"),
                "cpu_percent": s.get("CPUPerc") or s.get("CPUPercentage"),
                "mem_usage": s.get("MemUsage") or s.get("MemoryUsage"),
                "mem_percent": s.get("MemPerc") or s.get("MemoryPercentage"),
                "net_io": s.get("NetIO") or s.get("NetworkIO"),
                "block_io": s.get("BlockIO"),
                "pids": s.get("PIDs"),
            }
        )

    return {
        **overview,
        "containers_list": containers_list,
        "stats": stats_list,
        "images_list": images_list,
        "volumes_list": volumes_list,
        "networks_list": networks_list,
        "disk_usage": disk_usage,
        "info": info,
    }
