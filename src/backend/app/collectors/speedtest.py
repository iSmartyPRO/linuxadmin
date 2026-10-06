"""Speedtest: browser ↔ panel throughput, host ↔ Internet test, and iperf3 jobs.

Everything that takes longer than one request runs as an in-memory *job*. A job
keeps a bounded list of samples (throughput, latency) plus log lines; the UI
polls ``/api/speedtest/jobs/{id}?since=N`` and receives only new samples.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import statistics
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
import psutil

from app.collectors._exec import run_cmd, run_privileged

# ── Browser test payload / tickets ───────────────────────────────────

# 1 MiB of random bytes, sliced and repeated. Incompressible for gzip/brotli
# windows, so a proxy cannot inflate the measured rate.
_PAYLOAD = os.urandom(1024 * 1024)
DOWNLOAD_CHUNK = 256 * 1024
TICKET_TTL_SECONDS = 15 * 60


def payload_stream(total: int) -> AsyncIterator[bytes]:
    async def _gen() -> AsyncIterator[bytes]:
        sent = 0
        offset = 0
        while sent < total:
            n = min(DOWNLOAD_CHUNK, total - sent)
            if offset + n > len(_PAYLOAD):
                offset = 0
            yield _PAYLOAD[offset : offset + n]
            offset += n
            sent += n

    return _gen()


def _ticket_sig(secret: str, user: str, exp: int) -> str:
    msg = f"speedtest|{user}|{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:40]


def issue_ticket(secret: str, user: str) -> dict[str, Any]:
    """Short-lived HMAC ticket so ping/download/upload skip the DB auth lookup."""
    exp = int(time.time()) + TICKET_TTL_SECONDS
    user = re.sub(r"[^A-Za-z0-9_.@-]", "", user)[:64] or "user"
    return {"ticket": f"{user}.{exp}.{_ticket_sig(secret, user, exp)}", "expires_at": exp}


def verify_ticket(secret: str, ticket: str | None) -> bool:
    if not ticket:
        return False
    parts = ticket.rsplit(".", 2)
    if len(parts) != 3:
        return False
    user, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    return hmac.compare_digest(sig, _ticket_sig(secret, user, exp))


# ── Tools / install ──────────────────────────────────────────────────


def _detect_pkg_manager() -> str | None:
    for name in ("apt-get", "dnf", "yum", "apk", "pacman", "zypper"):
        if shutil.which(name):
            return name
    return None


_IPERF_VERSION: dict[str, Any] = {"path": None, "version": None}
_IPERF_OPTIONS: dict[str, Any] = {"path": None, "options": frozenset()}


async def iperf_version() -> str | None:
    path = shutil.which("iperf3")
    if not path:
        _IPERF_VERSION.update(path=None, version=None)
        return None
    if _IPERF_VERSION.get("path") == path and _IPERF_VERSION.get("version"):
        return _IPERF_VERSION["version"]
    code, out, err = await run_cmd([path, "--version"], timeout=5.0)
    text = (out or err or "").strip()
    m = re.search(r"iperf\s+([\d.]+\S*)", text)
    version = m.group(1) if m else (text.splitlines()[0] if text else None)
    _IPERF_VERSION.update(path=path, version=version)
    return version


async def iperf_options(path: str) -> frozenset[str]:
    """Long options the installed iperf3 understands (older builds lack
    --forceflush, --connect-timeout, --bidir, --idle-timeout)."""
    if _IPERF_OPTIONS.get("path") == path:
        return _IPERF_OPTIONS["options"]
    code, out, err = await run_cmd([path, "--help"], timeout=5.0)
    options = frozenset(re.findall(r"--([a-z][a-z0-9-]+)", f"{out or ''}{err or ''}"))
    _IPERF_OPTIONS.update(path=path, options=options)
    return options


async def tools_status() -> dict[str, Any]:
    return {
        "iperf3": bool(shutil.which("iperf3")),
        "iperf3_path": shutil.which("iperf3"),
        "iperf3_version": await iperf_version(),
        "pkg_manager": _detect_pkg_manager(),
    }


def congestion_algorithms() -> list[str]:
    try:
        raw = Path("/proc/sys/net/ipv4/tcp_available_congestion_control").read_text()
        return [x for x in raw.split() if re.fullmatch(r"[a-z0-9_]+", x)]
    except OSError:
        return []


def current_congestion() -> str | None:
    try:
        return Path("/proc/sys/net/ipv4/tcp_congestion_control").read_text().strip() or None
    except OSError:
        return None


def local_addresses() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stats = psutil.net_if_stats()
    for iface, addrs in psutil.net_if_addrs().items():
        st = stats.get(iface)
        if iface == "lo" or (st and not st.isup):
            continue
        for a in addrs:
            if a.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip = a.address.split("%")[0]
            if ip.startswith("fe80"):
                continue
            out.append(
                {
                    "iface": iface,
                    "ip": ip,
                    "family": 4 if a.family == socket.AF_INET else 6,
                    "speed_mbps": (st.speed if st else 0) or None,
                    "mtu": st.mtu if st else None,
                }
            )
    out.sort(key=lambda x: (x["family"], x["iface"]))
    return out


async def install_iperf(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    if not bool(opts.get("allow_install", True)):
        return {"ok": False, "error": "Package install is disabled in module settings"}
    if shutil.which("iperf3"):
        return {"ok": True, "already": True, "tools": await tools_status()}

    pm = _detect_pkg_manager()
    if not pm:
        return {"ok": False, "error": "No supported package manager found (apt/dnf/yum/apk/pacman/zypper)"}

    if pm == "apt-get":
        # Debian's iperf3 package asks whether to start a daemon — answer "no".
        cmds = [
            ["sh", "-c", "echo 'iperf3 iperf3/start_daemon boolean false' | debconf-set-selections || true"],
            ["apt-get", "update"],
            ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "iperf3"],
        ]
    elif pm == "dnf":
        cmds = [["dnf", "install", "-y", "iperf3"]]
    elif pm == "yum":
        cmds = [["yum", "install", "-y", "iperf3"]]
    elif pm == "apk":
        cmds = [["apk", "add", "--no-cache", "iperf3"]]
    elif pm == "pacman":
        cmds = [["pacman", "-Sy", "--noconfirm", "iperf3"]]
    elif pm == "zypper":
        cmds = [["zypper", "--non-interactive", "install", "iperf"]]
    else:
        return {"ok": False, "error": f"Unsupported package manager: {pm}"}

    logs: list[str] = []
    for cmd in cmds:
        code, out, err = await run_privileged(cmd, timeout=300.0)
        logs.append(f"$ {' '.join(cmd)}\n{(out or '')}{(err or '')}".strip())
        if code != 0 and cmd[0] != "sh" and (cmd[-1] in {"iperf3", "iperf"}):
            return {"ok": False, "error": (err or out or "install failed")[-600:], "log": "\n\n".join(logs)[-8000:]}

    _IPERF_VERSION.update(path=None, version=None)
    _IPERF_OPTIONS.update(path=None, options=frozenset())
    tools = await tools_status()
    ok = bool(tools["iperf3"])
    return {
        "ok": ok,
        "tools": tools,
        "log": "\n\n".join(logs)[-8000:],
        "error": None if ok else "iperf3 still missing after install",
    }


# ── Jobs ─────────────────────────────────────────────────────────────

MAX_SAMPLES = 6000
MAX_LOG = 1500
MAX_FINISHED_JOBS = 30


@dataclass
class Job:
    id: str
    kind: str  # internet | iperf_client | iperf_server
    owner: str
    params: dict[str, Any]
    status: str = "starting"  # starting | running | done | error | stopped
    phase: str = "init"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    sample_base: int = 0  # number of samples dropped from the front
    log: list[str] = field(default_factory=list)
    log_base: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    task: asyncio.Task | None = None
    proc: asyncio.subprocess.Process | None = None
    stop_requested: bool = False

    @property
    def active(self) -> bool:
        return self.status in {"starting", "running"}

    def add_sample(self, sample: dict[str, Any]) -> None:
        sample.setdefault("t", round(time.time() - self.started_at, 3))
        self.samples.append(sample)
        if len(self.samples) > MAX_SAMPLES:
            drop = len(self.samples) - MAX_SAMPLES
            del self.samples[:drop]
            self.sample_base += drop

    def add_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > MAX_LOG:
            drop = len(self.log) - MAX_LOG
            del self.log[:drop]
            self.log_base += drop

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "owner": self.owner,
            "status": self.status,
            "phase": self.phase,
            "params": self.params,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 2),
            "result": self.result,
            "meta": self.meta,
            "error": self.error,
        }

    def snapshot(self, since: int = 0, log_since: int = 0) -> dict[str, Any]:
        s_from = max(0, since - self.sample_base)
        l_from = max(0, log_since - self.log_base)
        return {
            **self.summary(),
            "samples": self.samples[s_from:],
            "next": self.sample_base + len(self.samples),
            "log": self.log[l_from:],
            "log_next": self.log_base + len(self.log),
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def create(self, kind: str, owner: str, params: dict[str, Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, owner=owner, params=params)
        self.jobs[job.id] = job
        self._gc()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active(self, kind: str | None = None) -> list[Job]:
        return [j for j in self.jobs.values() if j.active and (kind is None or j.kind == kind)]

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)

    def _gc(self) -> None:
        finished = [j for j in self.jobs.values() if not j.active]
        finished.sort(key=lambda j: j.started_at)
        for j in finished[: max(0, len(finished) - MAX_FINISHED_JOBS)]:
            self.jobs.pop(j.id, None)

    async def stop(self, job: Job) -> None:
        job.stop_requested = True
        if job.proc and job.proc.returncode is None:
            try:
                job.proc.terminate()
                try:
                    await asyncio.wait_for(job.proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    job.proc.kill()
            except ProcessLookupError:
                pass
        if job.task and not job.task.done() and job.kind == "internet":
            job.task.cancel()

    async def stop_all(self) -> None:
        for job in list(self.jobs.values()):
            if job.active:
                await self.stop(job)


jobs = JobManager()


def _finish(job: Job, status: str, error: str | None = None) -> None:
    if job.stop_requested and status != "error":
        status = "stopped"
    job.status = status
    job.error = error
    job.phase = "done" if status == "done" else status
    job.finished_at = time.time()


# ── History (JSON file under data_dir) ───────────────────────────────


def _history_path(opts: dict[str, Any]) -> Path:
    return Path(str(opts.get("data_dir") or "/var/lib/lnxadmin/speedtest")) / "history.json"


def load_history(opts: dict[str, Any]) -> list[dict[str, Any]]:
    path = _history_path(opts)
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(opts: dict[str, Any], entry: dict[str, Any]) -> None:
    limit = int(opts.get("history_size") or 200)
    path = _history_path(opts)
    items = load_history(opts)
    entry = {"id": entry.get("id") or uuid.uuid4().hex[:12], "at": time.time(), **entry}
    items.insert(0, entry)
    del items[limit:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, default=str))
        os.replace(tmp, path)
    except OSError:
        pass


def delete_history(opts: dict[str, Any], entry_id: str | None = None) -> int:
    path = _history_path(opts)
    items = load_history(opts)
    keep = [] if entry_id is None else [i for i in items if i.get("id") != entry_id]
    removed = len(items) - len(keep)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keep, default=str))
    except OSError:
        pass
    return removed


# ── Host ↔ Internet (Cloudflare speed edge) ──────────────────────────

CF_BASE = "https://speed.cloudflare.com"
_UP_BLOCK = os.urandom(256 * 1024)


def _jitter(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(statistics.fmean(abs(a - b) for a, b in zip(values, values[1:])), 2)


def _cf_client(ip_version: int | None, **kw: Any) -> httpx.AsyncClient:
    local = {4: "0.0.0.0", 6: "::"}.get(ip_version or 0)
    transport = httpx.AsyncHTTPTransport(local_address=local) if local else None
    return httpx.AsyncClient(transport=transport, http2=False, **kw)


def _l4_rtt_ms(resp: httpx.Response) -> float | None:
    """Kernel TCP RTT that Cloudflare measured on this connection (cfL4 server-timing)."""
    m = re.search(r"[?&]rtt=(\d+)", resp.headers.get("server-timing", ""))
    return int(m.group(1)) / 1000.0 if m else None


def _server_ms(resp: httpx.Response) -> float:
    return sum(float(x) for x in re.findall(r"dur=([\d.]+)", resp.headers.get("server-timing", "")))


async def _cf_ping(client: httpx.AsyncClient) -> float | None:
    try:
        t0 = time.perf_counter()
        resp = await client.get(f"{CF_BASE}/__down", params={"bytes": 0})
        dt = (time.perf_counter() - t0) * 1000.0
        if resp.status_code != 200:
            return None
        rtt = _l4_rtt_ms(resp)
        if rtt is not None:
            return max(0.1, rtt)
        return max(0.1, dt - _server_ms(resp))
    except httpx.HTTPError:
        return None


async def _cf_meta(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{CF_BASE}/cdn-cgi/trace")
    kv = dict(line.split("=", 1) for line in resp.text.splitlines() if "=" in line)
    probe = await client.get(f"{CF_BASE}/__down", params={"bytes": 0})
    ray = probe.headers.get("cf-ray", "")
    return {
        "provider": "Cloudflare",
        "public_ip": kv.get("ip") or probe.headers.get("cf-meta-ip"),
        "colo": kv.get("colo") or (ray.rsplit("-", 1)[-1] if "-" in ray else None),
        "country": kv.get("loc") or probe.headers.get("cf-meta-country"),
        "city": probe.headers.get("cf-meta-city"),
        "asn": probe.headers.get("cf-meta-asn"),
        "http": kv.get("http"),
        "tls": kv.get("tls"),
    }


async def _loaded_pinger(
    job: Job, phase: str, bucket: list[float], stop: asyncio.Event, ip_version: int | None
) -> None:
    async with _cf_client(ip_version, timeout=5.0) as client:
        while not stop.is_set():
            ms = await _cf_ping(client)
            if ms is not None:
                bucket.append(ms)
                job.add_sample({"kind": "latency", "phase": phase, "ms": round(ms, 2)})
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass


async def _cf_transfer(
    job: Job,
    direction: str,
    duration: float,
    streams: int,
    ip_version: int | None = None,
) -> dict[str, Any]:
    """Run *streams* parallel connections for *duration* seconds; sample every 250 ms."""
    total = 0
    stop = asyncio.Event()
    started = time.perf_counter()
    grace = min(1.5, duration * 0.2)  # ignore TCP slow start in the final figure
    grace_bytes = 0
    grace_t = 0.0
    grace_seen = False

    def count(n: int) -> None:
        nonlocal total
        total += n

    async def down_worker(client: httpx.AsyncClient) -> None:
        while not stop.is_set():
            try:
                async with client.stream("GET", f"{CF_BASE}/__down", params={"bytes": 25_000_000}) as resp:
                    async for chunk in resp.aiter_raw(65536):
                        count(len(chunk))
                        if stop.is_set():
                            break
            except httpx.HTTPError:
                await asyncio.sleep(0.2)

    async def up_body() -> AsyncIterator[bytes]:
        sent = 0
        while not stop.is_set() and sent < 25_000_000:
            count(len(_UP_BLOCK))
            sent += len(_UP_BLOCK)
            yield _UP_BLOCK

    async def up_worker(client: httpx.AsyncClient) -> None:
        while not stop.is_set():
            try:
                await client.post(
                    f"{CF_BASE}/__up",
                    content=up_body(),
                    headers={"Content-Type": "application/octet-stream"},
                )
            except httpx.HTTPError:
                await asyncio.sleep(0.2)

    loaded: list[float] = []
    clients = [_cf_client(ip_version, timeout=httpx.Timeout(10.0, read=15.0)) for _ in range(streams)]
    worker = down_worker if direction == "download" else up_worker
    tasks = [asyncio.create_task(worker(c)) for c in clients]
    pinger = asyncio.create_task(_loaded_pinger(job, direction, loaded, stop, ip_version))
    peak = 0.0
    last_t, last_b = started, 0
    try:
        while True:
            await asyncio.sleep(0.25)
            now = time.perf_counter()
            el = now - started
            inst = (total - last_b) / max(1e-6, now - last_t)
            last_t, last_b = now, total
            if not grace_seen and el >= grace:
                grace_seen = True
                grace_bytes = total
                grace_t = el
            avg = (
                (total - grace_bytes) / max(1e-6, el - grace_t)
                if grace_seen and el > grace_t + 0.2
                else total / max(1e-6, el)
            )
            peak = max(peak, inst)
            job.add_sample(
                {
                    "kind": "throughput",
                    "phase": direction,
                    "bps": round(inst * 8),
                    "avg_bps": round(avg * 8),
                    "bytes": total,
                    "progress": round(min(1.0, el / duration), 3),
                }
            )
            if el >= duration or job.stop_requested:
                break
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, pinger, return_exceptions=True)
        for c in clients:
            await c.aclose()
    el = time.perf_counter() - started
    final = (total - grace_bytes) / max(1e-6, el - grace_t) if grace_seen else total / max(1e-6, el)
    return {
        "bps": round(final * 8),
        "peak_bps": round(peak * 8),
        "bytes": total,
        "seconds": round(el, 2),
        "loaded_latency_ms": round(statistics.median(loaded), 2) if loaded else None,
        "loaded_jitter_ms": _jitter(loaded),
    }


async def run_internet_test(job: Job, opts: dict[str, Any]) -> None:
    p = job.params
    try:
        job.status = "running"
        job.phase = "connect"
        ipv = p.get("ip_version")
        async with _cf_client(ipv, timeout=8.0) as client:
            try:
                job.meta.update(await _cf_meta(client))
            except httpx.HTTPError as exc:
                _finish(job, "error", f"Cannot reach speed.cloudflare.com: {exc}")
                return
            job.add_log(f"Edge {job.meta.get('colo') or '?'} ({job.meta.get('country') or '?'}) · public IP {job.meta.get('public_ip')}")

            job.phase = "latency"
            pings: list[float] = []
            for _ in range(int(p.get("ping_count") or 20)):
                if job.stop_requested:
                    break
                ms = await _cf_ping(client)
                if ms is not None:
                    pings.append(ms)
                    job.add_sample({"kind": "latency", "phase": "idle", "ms": round(ms, 2)})
                await asyncio.sleep(0.05)
        if pings:
            job.result["ping_ms"] = round(statistics.median(pings), 2)
            job.result["ping_min_ms"] = round(min(pings), 2)
            job.result["jitter_ms"] = _jitter(pings)

        duration = float(p.get("duration") or 10)
        streams = int(p.get("streams") or 6)
        if p.get("download", True) and not job.stop_requested:
            job.phase = "download"
            job.result["download"] = await _cf_transfer(job, "download", duration, streams, ipv)
        if p.get("upload", True) and not job.stop_requested:
            job.phase = "upload"
            job.result["upload"] = await _cf_transfer(job, "upload", duration, max(1, streams // 2 + 1), ipv)
        _finish(job, "done")
        if job.status == "done":
            append_history(
                opts,
                {
                    "kind": "internet",
                    "target": f"Cloudflare {job.meta.get('colo') or ''}".strip(),
                    "ping_ms": job.result.get("ping_ms"),
                    "jitter_ms": job.result.get("jitter_ms"),
                    "download_bps": (job.result.get("download") or {}).get("bps"),
                    "upload_bps": (job.result.get("upload") or {}).get("bps"),
                    "loaded_latency_ms": (job.result.get("download") or {}).get("loaded_latency_ms"),
                    "meta": job.meta,
                    "by": job.owner,
                },
            )
    except asyncio.CancelledError:
        _finish(job, "stopped")
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        _finish(job, "error", str(exc)[:500])


# ── iperf3 ───────────────────────────────────────────────────────────

_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$|^[0-9A-Fa-f:.]+$")
_BITRATE_RE = re.compile(r"^\d+(\.\d+)?[KMGkmg]?$")
_SIZE_RE = re.compile(r"^\d+[KMkm]?$")

_LINE_RE = re.compile(
    r"^\[\s*(?P<id>\d+|SUM)\](?:\[(?P<role>[A-Z]{2}-[CS])\])?\s+"
    r"(?P<start>\d+\.\d+)-(?P<end>\d+\.\d+)\s+sec\s+"
    r"(?P<xfer>[\d.]+)\s+(?P<xu>[KMGT]?Bytes)\s+"
    r"(?P<rate>[\d.]+)\s+(?P<ru>[KMGT]?bits/sec)(?P<rest>.*)$"
)
_UDP_TAIL = re.compile(r"(?P<jitter>[\d.]+)\s+ms\s+(?P<lost>\d+)/(?P<total>\d+)\s+\((?P<pct>[\d.e+-]+)%\)")
_TCP_TAIL = re.compile(r"^\s+(?P<retr>\d+)(?:\s+(?P<cwnd>[\d.]+)\s+(?P<cu>[KMG]?Bytes))?")
_CPU_RE = re.compile(r"CPU Utilization:\s+local/(?P<lrole>\w+)\s+(?P<local>[\d.]+)%.*remote/(?P<rrole>\w+)\s+(?P<remote>[\d.]+)%")
_ACCEPT_RE = re.compile(r"Accepted connection from (?P<ip>[^,]+), port (?P<port>\d+)")

_BIT_MULT = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
_BYTE_MULT = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def _bits(value: str, unit: str) -> float:
    return float(value) * _BIT_MULT.get(unit[0] if unit[0] in "KMGT" else "", 1)


def _bytes(value: str, unit: str) -> float:
    return float(value) * _BYTE_MULT.get(unit[0] if unit[0] in "KMGT" else "", 1)


def valid_host(host: str) -> bool:
    return bool(host) and bool(_HOST_RE.match(host)) and not host.startswith("-")


def _unbuffered(binary: str, supported: frozenset[str]) -> list[str]:
    """Without --forceflush iperf3 block-buffers a pipe; fall back to stdbuf."""
    if "forceflush" in supported:
        return [binary]
    stdbuf = shutil.which("stdbuf")
    return [stdbuf, "-oL", binary] if stdbuf else [binary]


def build_client_argv(binary: str, p: dict[str, Any], supported: frozenset[str]) -> list[str]:
    argv = _unbuffered(binary, supported)
    argv += ["-c", p["host"], "-p", str(p["port"]), "-t", str(p["duration"]), "-i", str(p["interval"])]
    argv += ["-P", str(p["parallel"]), "-V", "-f", "m"]
    if "forceflush" in supported:
        argv.append("--forceflush")
    if p.get("omit"):
        argv += ["-O", str(p["omit"])]
    direction = p.get("direction", "upload")
    if direction == "download":
        argv.append("-R")
    elif direction == "bidir":
        argv.append("--bidir")
    if p.get("protocol") == "udp":
        argv += ["-u", "-b", str(p.get("bitrate") or "100M")]
    elif p.get("bitrate"):
        argv += ["-b", str(p["bitrate"])]
    if p.get("window"):
        argv += ["-w", str(p["window"])]
    if p.get("length"):
        argv += ["-l", str(p["length"])]
    if p.get("mss") and p.get("protocol") != "udp":
        argv += ["-M", str(p["mss"])]
    if p.get("congestion") and p.get("protocol") != "udp":
        argv += ["-C", str(p["congestion"])]
    if p.get("no_delay") and p.get("protocol") != "udp":
        argv.append("-N")
    if p.get("zerocopy"):
        argv.append("-Z")
    if p.get("ip_version") == 4:
        argv.append("-4")
    elif p.get("ip_version") == 6:
        argv.append("-6")
    if p.get("bind"):
        argv += ["-B", str(p["bind"])]
    if p.get("tos"):
        argv += ["-S", str(p["tos"])]
    if p.get("connect_timeout_ms") and "connect-timeout" in supported:
        argv += ["--connect-timeout", str(p["connect_timeout_ms"])]
    return argv


def build_server_argv(binary: str, p: dict[str, Any], supported: frozenset[str]) -> list[str]:
    argv = _unbuffered(binary, supported) + ["-s", "-p", str(p["port"]), "-i", str(p["interval"]), "-f", "m"]
    if "forceflush" in supported:
        argv.append("--forceflush")
    if p.get("bind"):
        argv += ["-B", str(p["bind"])]
    if p.get("one_off"):
        argv.append("-1")
    if p.get("ip_version") == 4:
        argv.append("-4")
    elif p.get("ip_version") == 6:
        argv.append("-6")
    if p.get("idle_timeout") and "idle-timeout" in supported:
        argv += ["--idle-timeout", str(p["idle_timeout"])]
    return argv


class IperfParser:
    """Turns iperf3 text output into interval samples and a final summary.

    Interval lines of one time slot are buffered (per stream + SUM) and flushed
    when the slot is complete: SUM seen, all expected streams seen, a new slot
    starts, or the reader goes quiet.
    """

    def __init__(self, job: Job, expected_streams: int | None) -> None:
        self.job = job
        self.expected = expected_streams
        self.pending: dict[tuple, dict[str, Any]] = {}
        self.session = 0
        self.summary: dict[str, Any] = {}
        self.role_streams: dict[str, set[str]] = {}
        self.emitted: set[tuple] = set()
        # Client mode knows the stream count, so a slot normally completes on
        # its own; the server has to guess and waits briefly for a SUM line.
        self.stale_after = 1.5 if expected_streams else 0.4

    def flush(self, only_other_than: tuple | None = None) -> None:
        for key in list(self.pending):
            if only_other_than is not None and key == only_other_than:
                continue
            self._emit_key(key)

    def flush_stale(self) -> None:
        now = time.monotonic()
        for key, slot in list(self.pending.items()):
            if now - slot["created"] >= self.stale_after:
                self._emit_key(key)

    def _emit_key(self, key: tuple) -> None:
        slot = self.pending.pop(key)
        self.emitted.add(key)
        if len(self.emitted) > 4000:
            self.emitted.clear()
        self._emit(slot)

    def _emit(self, slot: dict[str, Any]) -> None:
        by_role: dict[str, dict[str, Any]] = {}
        for role, data in slot["roles"].items():
            if data.get("sum") is not None:
                agg = data["sum"]
            else:
                streams = data["streams"]
                agg = {
                    "bps": sum(s["bps"] for s in streams),
                    "bytes": sum(s["bytes"] for s in streams),
                    "retr": sum(s.get("retr") or 0 for s in streams) if any("retr" in s for s in streams) else None,
                    "lost": sum(s.get("lost") or 0 for s in streams) if any("lost" in s for s in streams) else None,
                    "packets": sum(s.get("packets") or 0 for s in streams) if any("packets" in s for s in streams) else None,
                    "jitter_ms": max((s.get("jitter_ms") or 0) for s in streams) if any("jitter_ms" in s for s in streams) else None,
                }
            agg["streams"] = [
                {"id": s["id"], "bps": round(s["bps"]), "retr": s.get("retr"), "cwnd": s.get("cwnd")}
                for s in data["streams"]
            ]
            by_role[role] = agg
        sample: dict[str, Any] = {
            "kind": "interval",
            "start": slot["start"],
            "end": slot["end"],
            "session": slot["session"],
            "omitted": slot["omitted"],
        }
        for role, agg in by_role.items():
            prefix = {"TX-C": "tx", "RX-C": "rx", "TX-S": "tx", "RX-S": "rx"}.get(role, "")
            key = f"{prefix}_" if prefix else ""
            sample[f"{key}bps"] = round(agg["bps"])
            sample[f"{key}bytes"] = round(agg.get("bytes") or 0)
            for extra in ("retr", "lost", "packets", "jitter_ms"):
                if agg.get(extra) is not None:
                    sample[f"{key}{extra}"] = agg[extra]
            sample[f"{key}streams"] = agg["streams"]
        if "bps" not in sample and ("tx_bps" in sample or "rx_bps" in sample):
            sample["bps"] = sample.get("tx_bps", 0) + sample.get("rx_bps", 0)
        self.job.add_sample(sample)

    def feed(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        if text.startswith("- - - -"):
            # Separates interval blocks (-P > 1) and precedes the final summary.
            self.flush()
            return
        accept = _ACCEPT_RE.search(text)
        if accept:
            self.flush()
            self.session += 1
            self.role_streams.clear()
            self.job.add_sample(
                {"kind": "event", "event": "client", "ip": accept["ip"], "port": int(accept["port"]), "session": self.session}
            )
            self.job.meta["current_client"] = accept["ip"]
            return
        if "Server listening on" in text:
            if self.summary:
                self.job.add_sample({"kind": "event", "event": "session_end", "session": self.session, "summary": self.summary})
                self.job.meta.setdefault("sessions", []).insert(
                    0, {"session": self.session, "client": self.job.meta.get("current_client"), "at": time.time(), **self.summary}
                )
                del self.job.meta["sessions"][50:]
                self.summary = {}
            self.job.meta["current_client"] = None
            self.job.phase = "listening"
            return
        cpu = _CPU_RE.search(text)
        if cpu:
            self.summary["cpu_local"] = float(cpu["local"])
            self.summary["cpu_remote"] = float(cpu["remote"])
            return
        m = _LINE_RE.match(text)
        if not m:
            return
        role = m["role"] or ""
        rest = m["rest"] or ""
        end_tag = re.search(r"\b(sender|receiver)\s*$", rest)
        is_summary = end_tag is not None
        entry: dict[str, Any] = {
            "id": m["id"],
            "bps": _bits(m["rate"], m["ru"]),
            "bytes": _bytes(m["xfer"], m["xu"]),
        }
        udp = _UDP_TAIL.search(rest)
        if udp:
            entry["jitter_ms"] = float(udp["jitter"])
            entry["lost"] = int(udp["lost"])
            entry["packets"] = int(udp["total"])
        else:
            tcp = _TCP_TAIL.match(rest)
            if tcp:
                if self.job.params.get("protocol") == "udp":
                    entry["packets"] = int(tcp["retr"])  # UDP sender interval: datagram count
                else:
                    entry["retr"] = int(tcp["retr"])
                    if tcp["cwnd"]:
                        entry["cwnd"] = round(_bytes(tcp["cwnd"], tcp["cu"]))
        if is_summary:
            end = end_tag.group(1)
            if m["id"] != "SUM" and len(self.role_streams.get(role, ())) > 1:
                return
            tag = {"TX-C": "tx_", "RX-C": "rx_", "TX-S": "tx_", "RX-S": "rx_"}.get(role, "")
            blk = {
                "bps": round(entry["bps"]),
                "bytes": round(entry["bytes"]),
                "seconds": round(float(m["end"]) - float(m["start"]), 2),
            }
            for extra in ("retr", "jitter_ms", "lost", "packets"):
                if extra in entry:
                    blk[extra] = entry[extra]
            if "packets" in blk and blk["packets"] and "lost" in blk:
                blk["loss_pct"] = round(100.0 * blk["lost"] / blk["packets"], 3)
            self.summary[f"{tag}{end}"] = blk
            return
        omitted = "omitted" in rest
        if m["id"] != "SUM":
            self.role_streams.setdefault(role, set()).add(m["id"])
        slot_key = (self.session, m["start"], m["end"], omitted)
        if slot_key in self.emitted:
            return
        # A new slot means the previous ones are complete.
        self.flush(only_other_than=slot_key)
        slot = self.pending.setdefault(
            slot_key,
            {
                "start": float(m["start"]),
                "end": float(m["end"]),
                "session": self.session,
                "omitted": omitted,
                "roles": {},
                "created": time.monotonic(),
            },
        )
        rdata = slot["roles"].setdefault(role, {"streams": [], "sum": None})
        if m["id"] == "SUM":
            rdata["sum"] = entry
        else:
            rdata["streams"].append(entry)
        bidir = self.job.params.get("direction") == "bidir"
        roles_needed = 2 if bidir else 1
        if self.expected:
            complete_roles = 0
            for r in slot["roles"].values():
                if r["sum"] is not None or (self.expected == 1 and len(r["streams"]) >= 1):
                    complete_roles += 1
            if complete_roles >= roles_needed:
                self.flush()


async def _read_process(job: Job, proc: asyncio.subprocess.Process, parser: IperfParser) -> None:
    assert proc.stdout is not None
    while True:
        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=0.1)
        except asyncio.TimeoutError:
            parser.flush_stale()
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        job.add_log(line)
        if "iperf3: error" in line or line.startswith("iperf3: "):
            job.error = line.replace("iperf3: error - ", "").strip()[:400]
        if job.phase in {"init", "connect"} and _LINE_RE.match(line):
            job.phase = "running"
        if "Connecting to host" in line:
            job.phase = "connect"
        if "Server listening on" in line and job.kind == "iperf_server":
            job.status = "running"
        try:
            parser.feed(line)
        except Exception:  # noqa: BLE001 — never kill the job on a parse hiccup
            pass
    parser.flush()


async def run_iperf_client(job: Job, binary: str, opts: dict[str, Any]) -> None:
    argv = build_client_argv(binary, job.params, await iperf_options(binary))
    job.meta["command"] = " ".join(argv[argv.index(binary) :]).replace(binary, "iperf3", 1)
    job.add_log("$ " + job.meta["command"])
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
    except OSError as exc:
        _finish(job, "error", str(exc))
        return
    job.proc = proc
    job.status = "running"
    job.phase = "connect"
    parser = IperfParser(job, expected_streams=int(job.params.get("parallel") or 1))
    hard_limit = float(job.params["duration"]) + float(job.params.get("omit") or 0) + 30
    try:
        await asyncio.wait_for(_read_process(job, proc, parser), timeout=hard_limit)
    except asyncio.TimeoutError:
        proc.kill()
        job.error = job.error or "iperf3 did not finish in time"
    await proc.wait()
    job.result = parser.summary
    ok = proc.returncode == 0 and not job.stop_requested
    if ok:
        job.error = None
    _finish(job, "done" if ok else ("stopped" if job.stop_requested else "error"), None if ok else (job.error or f"iperf3 exited with code {proc.returncode}"))
    if job.status == "done":
        p = job.params
        s = parser.summary
        down = up = None
        if p.get("direction") == "bidir":
            up = (s.get("tx_receiver") or s.get("tx_sender") or {}).get("bps")
            down = (s.get("rx_receiver") or s.get("rx_sender") or {}).get("bps")
        elif p.get("direction") == "download":
            down = (s.get("receiver") or s.get("sender") or {}).get("bps")
        else:
            up = (s.get("receiver") or s.get("sender") or {}).get("bps")
        append_history(
            opts,
            {
                "kind": "iperf",
                "target": f"{p['host']}:{p['port']}",
                "protocol": p.get("protocol"),
                "direction": p.get("direction"),
                "parallel": p.get("parallel"),
                "download_bps": down,
                "upload_bps": up,
                "jitter_ms": (s.get("receiver") or {}).get("jitter_ms"),
                "loss_pct": (s.get("receiver") or {}).get("loss_pct"),
                "retr": (s.get("sender") or s.get("tx_sender") or {}).get("retr"),
                "by": job.owner,
            },
        )


async def run_iperf_server(job: Job, binary: str) -> None:
    argv = build_server_argv(binary, job.params, await iperf_options(binary))
    job.meta["command"] = " ".join(argv[argv.index(binary) :]).replace(binary, "iperf3", 1)
    job.meta["sessions"] = []
    job.add_log("$ " + job.meta["command"])
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )
    except OSError as exc:
        _finish(job, "error", str(exc))
        return
    job.proc = proc
    job.phase = "listening"
    parser = IperfParser(job, expected_streams=None)
    max_lifetime = float(job.params.get("max_lifetime") or 0)
    try:
        if max_lifetime > 0:
            await asyncio.wait_for(_read_process(job, proc, parser), timeout=max_lifetime)
        else:
            await _read_process(job, proc, parser)
    except asyncio.TimeoutError:
        job.stop_requested = True
        proc.terminate()
        job.add_log(f"Server stopped after max lifetime ({int(max_lifetime)} s)")
    await proc.wait()
    if job.stop_requested or proc.returncode in (0, -15):
        _finish(job, "stopped" if not job.params.get("one_off") or job.stop_requested else "done")
    else:
        _finish(job, "error", job.error or f"iperf3 exited with code {proc.returncode}")


def spawn(job: Job, coro_factory: Callable[[], Any]) -> None:
    job.task = asyncio.create_task(coro_factory(), name=f"speedtest-{job.kind}-{job.id}")

