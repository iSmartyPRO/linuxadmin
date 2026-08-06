"""SSH tunnel gateway: restricted users, keys, permitopen destinations, ssh config templates."""

from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import os
import pwd
import random
import re
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import psutil

NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(
    r"^(?:(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"|(?:\d{1,3}\.){3}\d{1,3}|\[?[0-9a-fA-F:]+\]?)$"
)
PUBKEY_RE = re.compile(
    r"^(ssh-(?:ed25519|rsa|dss)|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com|"
    r"sk-ecdsa-sha2-nistp256@openssh\.com)\s+[A-Za-z0-9+/=]+(?:\s+.*)?$"
)

DEFAULT_DATA_DIR = "/var/lib/lnxadmin/ssh-tunnels"
DEFAULT_GROUP = "lnxadmin-tunnel"
DEFAULT_SSHD_DROPIN = "/etc/ssh/sshd_config.d/99-lnxadmin-tunnels.conf"
MANAGED_MARKER = "# managed-by: lnxadmin-ssh-tunnel"
SSHD_USER_RE = re.compile(r"sshd:\s*([^\s@\[]+)(?:@|\s|\[|$)")
SS_BYTES_SENT_RE = re.compile(r"bytes_sent:(\d+)")
SS_BYTES_RECV_RE = re.compile(r"bytes_received:(\d+)")
# session_key -> (monotonic_ts, bytes_sent, bytes_recv) for rate calculation
_IO_RATE_CACHE: dict[str, tuple[float, int, int]] = {}


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


async def _run_privileged(argv: list[str], timeout: float = 20.0) -> tuple[int, str, str]:
    code, out, err = await _run(argv, timeout=timeout)
    if code == 0:
        return code, out, err
    combined = (err or out or "").lower()
    needs_priv = any(
        x in combined
        for x in ("permission denied", "operation not permitted", "must be root", "only root")
    )
    if not needs_priv and code != 0:
        # still try sudo for install/useradd failures that mention nothing clear
        if any(x in argv[0] for x in ("useradd", "userdel", "groupadd", "install", "chown", "chmod", "sshd")):
            needs_priv = True
        elif argv[0].endswith(("useradd", "userdel", "groupadd", "install", "tee")):
            needs_priv = True
    if not needs_priv:
        # Always attempt sudo for known admin tools when first attempt failed
        base = Path(argv[0]).name
        if base in {
            "useradd",
            "userdel",
            "groupadd",
            "usermod",
            "install",
            "tee",
            "chmod",
            "chown",
            "mkdir",
            "systemctl",
            "sshd",
            "rm",
        }:
            needs_priv = True
    if not needs_priv:
        return code, out, err
    sudo = shutil.which("sudo")
    if not sudo:
        return code, out, err or "Permission denied (root or sudo required)"
    return await _run([sudo, "-n", *argv], timeout=timeout)


def _opts(options: dict[str, Any] | None) -> dict[str, Any]:
    o = options or {}
    return {
        "data_dir": o.get("data_dir") or DEFAULT_DATA_DIR,
        "group": o.get("group") or DEFAULT_GROUP,
        "sshd_dropin": o.get("sshd_dropin") or DEFAULT_SSHD_DROPIN,
        "username_prefix": o.get("username_prefix") or "tun-",
        "public_hostname": (o.get("public_hostname") or "").strip()
        or socket.getfqdn()
        or socket.gethostname(),
        # Port clients connect to (may be external NAT / firewall map).
        "public_port": int(o.get("public_port") or 22),
        # Local port where sshd actually listens (used for live session detection).
        "listen_port": int(o.get("listen_port") or 22),
        "shell": o.get("shell") or "/usr/sbin/nologin",
        "home_base": o.get("home_base") or "/var/lib/lnxadmin/ssh-homes",
    }


def _valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def _valid_host(host: str) -> bool:
    h = (host or "").strip()
    if not h or len(h) > 253:
        return False
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return bool(HOST_RE.fullmatch(h)) or bool(re.fullmatch(r"[a-zA-Z0-9._-]+", h))


def _valid_port(port: Any) -> bool:
    try:
        p = int(port)
    except (TypeError, ValueError):
        return False
    return 1 <= p <= 65535


def _normalize_destinations(raw: list[Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            if ":" not in item:
                return None, f"Invalid destination: {item}"
            host, _, port_s = item.rpartition(":")
            label = ""
            port: Any = port_s
        elif isinstance(item, dict):
            host = str(item.get("host") or "").strip()
            port = item.get("port")
            label = str(item.get("label") or "").strip()[:64]
        else:
            return None, "Invalid destination format"
        if not _valid_host(host):
            return None, f"Invalid host: {host}"
        if not _valid_port(port):
            return None, f"Invalid port: {port}"
        key = f"{host}:{int(port)}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"host": host, "port": int(port), "label": label})
    return out, None


def _meta_path(data_dir: str, username: str) -> Path:
    return Path(data_dir) / f"{username}.json"


def _load_meta(data_dir: str, username: str) -> dict[str, Any] | None:
    path = _meta_path(data_dir, username)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _list_managed_usernames(data_dir: str) -> list[str]:
    root = Path(data_dir)
    if not root.is_dir():
        return []
    names: list[str] = []
    for p in sorted(root.glob("*.json")):
        if p.name.startswith("."):
            continue
        names.append(p.stem)
    return names


async def _ensure_dir(path: str, mode: str = "0755") -> tuple[bool, str]:
    p = Path(path)
    if p.is_dir():
        return True, ""
    code, out, err = await _run_privileged(["mkdir", "-p", path])
    if code != 0:
        return False, (err or out or "mkdir failed").strip()
    await _run_privileged(["chmod", mode, path])
    return True, ""


async def _write_file(
    path: str,
    content: str,
    *,
    mode: str = "0644",
    owner: str | None = None,
    group: str | None = None,
) -> tuple[bool, str]:
    parent = str(Path(path).parent)
    ok, err = await _ensure_dir(parent)
    if not ok:
        return False, err
    fd, tmp = tempfile.mkstemp(prefix="lnxadmin-ssh-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        cmd = ["install", f"-m{mode}"]
        if owner:
            cmd.extend(["-o", owner])
        if group:
            cmd.extend(["-g", group])
        cmd.extend([tmp, path])
        code, out, err = await _run_privileged(cmd)
        if code != 0:
            return False, (err or out or "install failed").strip()[:400]
        return True, ""
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


async def _save_meta(data_dir: str, username: str, meta: dict[str, Any]) -> tuple[bool, str]:
    ok, err = await _ensure_dir(data_dir)
    if not ok:
        return False, err
    payload = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    return await _write_file(str(_meta_path(data_dir, username)), payload, mode="0640")


def _parse_pubkey_line(line: str) -> dict[str, Any] | None:
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    # Strip leading options (may contain commas and quotes)
    key_types = (
        "ssh-ed25519",
        "ssh-rsa",
        "ssh-dss",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    )
    options = ""
    rest = line
    for kt in key_types:
        idx = line.find(kt + " ")
        if idx == 0:
            rest = line
            options = ""
            break
        if idx > 0:
            options = line[:idx].rstrip().rstrip(",")
            rest = line[idx:]
            break
    parts = rest.split(None, 2)
    if len(parts) < 2:
        return None
    ktype, blob = parts[0], parts[1]
    comment = parts[2] if len(parts) > 2 else ""
    if ktype not in key_types:
        return None
    fp = _fingerprint_from_blob(ktype, blob)
    return {
        "type": ktype,
        "key": blob,
        "comment": comment,
        "options": options,
        "fingerprint": fp,
        "line": f"{ktype} {blob}" + (f" {comment}" if comment else ""),
    }


def _fingerprint_from_blob(ktype: str, blob: str) -> str:
    raw = f"{ktype} {blob}".encode()
    digest = hashlib.sha256(raw).digest()
    import base64

    b64 = base64.b64encode(digest).decode().rstrip("=")
    return f"SHA256:{b64}"


async def _fingerprint_ssh_keygen(pubkey_line: str) -> str | None:
    binary = shutil.which("ssh-keygen")
    if not binary:
        return None
    fd, tmp = tempfile.mkstemp(prefix="lnxadmin-pub-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(pubkey_line.strip() + "\n")
        code, out, _ = await _run([binary, "-lf", tmp])
        if code != 0:
            return None
        # format: 256 SHA256:xxx comment (ED25519)
        parts = (out or "").strip().split()
        for p in parts:
            if p.startswith("SHA256:"):
                return p
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _build_auth_options(destinations: list[dict[str, Any]]) -> str:
    """OpenSSH authorized_keys options for tunnel-only access."""
    parts = ["restrict", "port-forwarding"]
    for d in destinations:
        host = d["host"]
        port = int(d["port"])
        # IPv6 in permitopen needs brackets sometimes; keep simple hostnames/IPv4
        if ":" in host and not host.startswith("["):
            target = f"[{host}]:{port}"
        else:
            target = f"{host}:{port}"
        parts.append(f'permitopen="{target}"')
    if not destinations:
        # restrict without port-forwarding — no forwards allowed
        return "restrict"
    return ",".join(parts)


def _authorized_keys_path(home: str) -> Path:
    return Path(home) / ".ssh" / "authorized_keys"


def _read_authorized_keys(home: str) -> list[dict[str, Any]]:
    path = _authorized_keys_path(home)
    keys: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys
    for line in text.splitlines():
        parsed = _parse_pubkey_line(line)
        if parsed:
            keys.append(parsed)
    return keys


async def _rewrite_authorized_keys(
    username: str,
    home: str,
    destinations: list[dict[str, Any]],
    pubkeys: list[dict[str, Any]],
) -> tuple[bool, str]:
    ssh_dir = str(Path(home) / ".ssh")
    ok, err = await _ensure_dir(ssh_dir, "0700")
    if not ok:
        return False, err
    await _run_privileged(["chown", f"{username}:{username}", ssh_dir])
    await _run_privileged(["chmod", "700", ssh_dir])

    opts = _build_auth_options(destinations)
    dest_comment = ", ".join(f"{d['host']}:{d['port']}" for d in destinations) or "(none)"
    lines = [
        f"{MANAGED_MARKER}",
        f"# destinations: {dest_comment}",
    ]
    for k in pubkeys:
        base = f"{k['type']} {k['key']}"
        comment = (k.get("comment") or "").strip()
        if comment:
            base = f"{base} {comment}"
        lines.append(f"{opts} {base}")

    content = "\n".join(lines) + "\n"
    path = str(_authorized_keys_path(home))
    ok, err = await _write_file(path, content, mode="0600", owner=username, group=username)
    if not ok:
        return False, err
    await _run_privileged(["chmod", "600", path])
    return True, ""


def _sshd_dropin_content(group: str) -> str:
    return f"""{MANAGED_MARKER}
# Tunnel-only accounts in group {group}
Match Group {group}
    AllowTcpForwarding local
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    GatewayPorts no
    ForceCommand /bin/false
    PasswordAuthentication no
"""


def _user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def _user_home(username: str) -> str | None:
    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError:
        return None


def _in_group(username: str, group: str) -> bool | None:
    try:
        import grp

        g = grp.getgrnam(group)
        if username in g.gr_mem:
            return True
        try:
            return pwd.getpwnam(username).pw_gid == g.gr_gid
        except KeyError:
            return False
    except KeyError:
        return None
    except OSError:
        return None


async def collect_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = _opts(options)
    data_dir = opts["data_dir"]
    group = opts["group"]
    dropin = Path(opts["sshd_dropin"])

    group_exists = False
    try:
        import grp

        grp.getgrnam(group)
        group_exists = True
    except KeyError:
        group_exists = False

    users: list[dict[str, Any]] = []
    for username in _list_managed_usernames(data_dir):
        meta = _load_meta(data_dir, username) or {}
        exists = _user_exists(username)
        home = _user_home(username) if exists else meta.get("home")
        keys = _read_authorized_keys(home) if home and exists else []
        dests = meta.get("destinations") or []
        users.append(
            {
                "username": username,
                "comment": meta.get("comment") or "",
                "enabled": bool(meta.get("enabled", True)),
                "exists": exists,
                "home": home,
                "in_group": _in_group(username, group) if exists else False,
                "destinations": dests,
                "destinations_count": len(dests),
                "keys_count": len(keys),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
            }
        )

    dropin_ok = False
    dropin_managed = False
    if dropin.is_file():
        dropin_ok = True
        try:
            text = dropin.read_text(encoding="utf-8", errors="replace")
            dropin_managed = MANAGED_MARKER in text
        except OSError:
            pass

    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    sshd_installed = Path(sshd).exists() or bool(shutil.which("sshd"))

    sessions_info: dict[str, Any] = {"available": False, "active_count": 0, "sessions": []}
    if options is None or options.get("show_sessions", True):
        sessions_info = await asyncio.to_thread(collect_active_sessions, options)

    return {
        "available": True,
        "group": group,
        "group_exists": group_exists,
        "data_dir": data_dir,
        "sshd_dropin": str(dropin),
        "sshd_dropin_exists": dropin_ok,
        "sshd_dropin_managed": dropin_managed,
        "sshd_installed": sshd_installed,
        "public_hostname": opts["public_hostname"],
        "public_port": opts["public_port"],
        "username_prefix": opts["username_prefix"],
        "users": users,
        "count": len(users),
        "active_sessions": sessions_info.get("active_count", 0),
        "sessions": sessions_info.get("sessions") or [],
        "sessions_available": bool(sessions_info.get("available")),
        "sessions_error": sessions_info.get("error"),
    }


async def collect_user_detail(username: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _valid_name(username):
        return {"available": False, "error": "Invalid username"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None and not _user_exists(username):
        return {"available": False, "error": "Tunnel user not found"}

    meta = meta or {"username": username, "destinations": [], "comment": ""}
    exists = _user_exists(username)
    home = _user_home(username) if exists else meta.get("home")
    keys_raw = _read_authorized_keys(home) if home and exists else []
    keys = [
        {
            "fingerprint": k["fingerprint"],
            "type": k["type"],
            "comment": k["comment"],
            "key_preview": (k["key"][:24] + "…") if len(k["key"]) > 24 else k["key"],
        }
        for k in keys_raw
    ]
    return {
        "available": True,
        "user": {
            "username": username,
            "comment": meta.get("comment") or "",
            "enabled": bool(meta.get("enabled", True)),
            "exists": exists,
            "home": home,
            "in_group": _in_group(username, opts["group"]) if exists else False,
            "destinations": meta.get("destinations") or [],
            "keys": keys,
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
        },
        "public_hostname": opts["public_hostname"],
        "public_port": opts["public_port"],
    }


async def ensure_infra(options: dict[str, Any] | None = None, *, reload_sshd: bool = False) -> dict[str, Any]:
    opts = _opts(options)
    group = opts["group"]
    warnings: list[str] = []

    ok, err = await _ensure_dir(opts["data_dir"])
    if not ok:
        return {"ok": False, "error": f"data_dir: {err}"}
    ok, err = await _ensure_dir(opts["home_base"])
    if not ok:
        return {"ok": False, "error": f"home_base: {err}"}

    # group
    try:
        import grp

        grp.getgrnam(group)
    except KeyError:
        binary = shutil.which("groupadd") or "/usr/sbin/groupadd"
        code, out, err = await _run_privileged([binary, group])
        if code != 0:
            return {"ok": False, "error": (err or out or "groupadd failed").strip()[:400]}

    content = _sshd_dropin_content(group)
    ok, err = await _write_file(opts["sshd_dropin"], content, mode="0644")
    if not ok:
        return {"ok": False, "error": f"sshd drop-in: {err}"}

    # validate sshd config
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    if Path(sshd).exists():
        code, out, err = await _run_privileged([sshd, "-t"])
        if code != 0:
            return {
                "ok": False,
                "error": f"sshd -t failed: {(err or out).strip()[:400]}",
            }

    reloaded = False
    if reload_sshd:
        code, out, err = await _run_privileged(["systemctl", "reload", "ssh"])
        if code != 0:
            code2, out2, err2 = await _run_privileged(["systemctl", "reload", "sshd"])
            if code2 != 0:
                warnings.append(
                    f"Config written, but reload failed: {(err2 or err or out2 or out).strip()[:200]}"
                )
            else:
                reloaded = True
        else:
            reloaded = True

    return {
        "ok": True,
        "group": group,
        "sshd_dropin": opts["sshd_dropin"],
        "reloaded": reloaded,
        "warnings": warnings,
    }


async def create_tunnel_user(
    username: str,
    *,
    comment: str = "",
    destinations: list[Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid username"}
    opts = _opts(options)
    prefix = opts["username_prefix"]
    if prefix and not username.startswith(prefix):
        return {
            "ok": False,
            "error": f"Name must start with the “{prefix}” prefix (configured in the module)",
        }
    if _user_exists(username) or _load_meta(opts["data_dir"], username):
        return {"ok": False, "error": "User already exists"}

    dests, derr = _normalize_destinations(destinations or [])
    if derr:
        return {"ok": False, "error": derr}

    infra = await ensure_infra(options, reload_sshd=False)
    if not infra.get("ok"):
        return infra

    home = str(Path(opts["home_base"]) / username)
    shell = opts["shell"]
    if not Path(shell).exists():
        shell = "/bin/false"

    binary = shutil.which("useradd") or "/usr/sbin/useradd"
    cmd = [
        binary,
        "-m",
        "-d",
        home,
        "-s",
        shell,
        "-G",
        opts["group"],
        "-c",
        re.sub(r"[^\w\s.@+-]", "", comment or "SSH tunnel")[:64] or "SSH tunnel",
        username,
    ]
    code, out, err = await _run_privileged(cmd)
    if code != 0:
        return {"ok": False, "error": (err or out or "useradd failed").strip()[:400]}

    # lock password — key-only
    passwd = shutil.which("passwd") or "/usr/bin/passwd"
    await _run_privileged([passwd, "-l", username])

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = {
        "username": username,
        "comment": comment or "",
        "enabled": True,
        "home": home,
        "destinations": dests or [],
        "created_at": now,
        "updated_at": now,
    }
    ok, err = await _save_meta(opts["data_dir"], username, meta)
    if not ok:
        return {"ok": False, "error": f"user created, meta not saved: {err}"}

    ok, err = await _rewrite_authorized_keys(username, home, dests or [], [])
    if not ok:
        return {"ok": True, "warning": f"authorized_keys: {err}", "username": username}

    return {"ok": True, "username": username, "home": home}


async def delete_tunnel_user(
    username: str,
    *,
    remove_home: bool = True,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None and not _user_exists(username):
        return {"ok": False, "error": "Not found"}

    if _user_exists(username):
        binary = shutil.which("userdel") or "/usr/sbin/userdel"
        cmd = [binary]
        if remove_home:
            cmd.append("-r")
        cmd.append(username)
        code, out, err = await _run_privileged(cmd)
        if code != 0:
            return {"ok": False, "error": (err or out or "userdel failed").strip()[:400]}

    meta_path = _meta_path(opts["data_dir"], username)
    if meta_path.exists():
        code, out, err = await _run_privileged(["rm", "-f", str(meta_path)])
        if code != 0:
            return {"ok": True, "warning": f"user deleted, meta left behind: {err or out}"}

    return {"ok": True}


async def set_destinations(
    username: str,
    destinations: list[Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None:
        return {"ok": False, "error": "Tunnel user not found in registry"}
    if not _user_exists(username):
        return {"ok": False, "error": "System user is missing"}

    dests, derr = _normalize_destinations(destinations)
    if derr:
        return {"ok": False, "error": derr}

    home = _user_home(username) or meta.get("home")
    if not home:
        return {"ok": False, "error": "Could not determine home directory"}

    keys = _read_authorized_keys(home)
    ok, err = await _rewrite_authorized_keys(username, home, dests or [], keys)
    if not ok:
        return {"ok": False, "error": err}

    meta["destinations"] = dests or []
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ok, err = await _save_meta(opts["data_dir"], username, meta)
    if not ok:
        return {"ok": False, "error": err}
    return {"ok": True, "destinations": dests}


async def add_public_key(
    username: str,
    public_key: str,
    *,
    comment: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None or not _user_exists(username):
        return {"ok": False, "error": "Tunnel user not found"}

    line = (public_key or "").strip()
    # Allow pasting full authorized_keys line — take last key-looking part
    if not line:
        return {"ok": False, "error": "Empty key"}
    parsed = _parse_pubkey_line(line)
    if not parsed:
        # try if user pasted only type+key without options
        if not PUBKEY_RE.match(line.split("\n")[0].strip()):
            return {"ok": False, "error": "Invalid SSH public key format"}
        parsed = _parse_pubkey_line(line.split("\n")[0].strip())
    if not parsed:
        return {"ok": False, "error": "Failed to parse key"}

    if comment:
        parsed["comment"] = re.sub(r"[^\w\s.@+()/-]", "", comment)[:128]

    fp = await _fingerprint_ssh_keygen(f"{parsed['type']} {parsed['key']}")
    if fp:
        parsed["fingerprint"] = fp

    home = _user_home(username) or meta.get("home")
    if not home:
        return {"ok": False, "error": "home not found"}

    existing = _read_authorized_keys(home)
    if any(k["key"] == parsed["key"] for k in existing):
        return {"ok": False, "error": "This key is already added"}

    existing.append(parsed)
    dests = meta.get("destinations") or []
    ok, err = await _rewrite_authorized_keys(username, home, dests, existing)
    if not ok:
        return {"ok": False, "error": err}

    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await _save_meta(opts["data_dir"], username, meta)
    return {
        "ok": True,
        "fingerprint": parsed["fingerprint"],
        "type": parsed["type"],
        "comment": parsed.get("comment") or "",
    }


async def remove_public_key(
    username: str,
    fingerprint: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None or not _user_exists(username):
        return {"ok": False, "error": "Tunnel user not found"}
    home = _user_home(username) or meta.get("home")
    if not home:
        return {"ok": False, "error": "home not found"}

    existing = _read_authorized_keys(home)
    fp = (fingerprint or "").strip()
    kept = [k for k in existing if k["fingerprint"] != fp and not k["key"].startswith(fp)]
    # also allow match by key prefix
    if len(kept) == len(existing):
        kept = [k for k in existing if fp not in (k["fingerprint"], k["key"][:16])]
    if len(kept) == len(existing):
        return {"ok": False, "error": "Key not found"}

    ok, err = await _rewrite_authorized_keys(
        username, home, meta.get("destinations") or [], kept
    )
    if not ok:
        return {"ok": False, "error": err}
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await _save_meta(opts["data_dir"], username, meta)
    return {"ok": True}


async def generate_keypair(
    username: str,
    *,
    comment: str | None = None,
    key_type: str = "rsa",
    bits: int = 4096,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key_type = (key_type or "rsa").strip().lower()
    if key_type not in ("ed25519", "rsa"):
        return {"ok": False, "error": "Only rsa and ed25519 are supported"}
    binary = shutil.which("ssh-keygen")
    if not binary:
        return {"ok": False, "error": "ssh-keygen not found"}

    opts = _opts(options)
    host = opts["public_hostname"]
    # Useful identifying comment for authorized_keys / client handoff
    default_comment = f"{username}@{host} (ssh-tunnel)"
    comment_s = re.sub(r"[^\w\s.@+()/-]", "", (comment or default_comment).strip())[:128]
    if not comment_s:
        comment_s = default_comment[:128]

    bits_i = int(bits or 4096)
    if key_type == "rsa":
        bits_i = max(2048, min(8192, bits_i))
        if bits_i < 4096:
            # Prefer RSA 4096 for tunnel keys unless explicitly ≥4096
            bits_i = 4096

    tmpdir = tempfile.mkdtemp(prefix="lnxadmin-keygen-")
    key_path = str(Path(tmpdir) / "id_key")
    try:
        cmd = [binary, "-t", key_type, "-f", key_path, "-N", "", "-C", comment_s]
        if key_type == "rsa":
            cmd.extend(["-b", str(bits_i)])
        code, out, err = await _run(cmd, timeout=90)
        if code != 0:
            return {"ok": False, "error": (err or out or "ssh-keygen failed").strip()[:400]}

        private = Path(key_path).read_text(encoding="utf-8")
        public = Path(key_path + ".pub").read_text(encoding="utf-8").strip()
        added = await add_public_key(username, public, comment=comment_s, options=options)
        if not added.get("ok"):
            return added

        suffix = f"rsa{bits_i}" if key_type == "rsa" else "ed25519"
        return {
            "ok": True,
            "private_key": private,
            "public_key": public,
            "fingerprint": added.get("fingerprint"),
            "type": key_type,
            "bits": bits_i if key_type == "rsa" else None,
            "comment": comment_s,
            "suggested_filename": f"{username}_{suffix}",
            "warning": "Private key is shown once and is not stored on the server",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _allocate_local_ports(
    destinations: list[dict[str, Any]],
    *,
    mode: str = "random",
    custom: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    mode:
      - random: high ephemeral local ports (default — avoid client conflicts)
      - same: local_port == remote port (if <1024 → random instead)
      - custom: use local_port from `custom` / destinations when provided; else same
    """
    mode = (mode or "random").strip().lower()
    if mode not in ("random", "same", "custom"):
        mode = "random"

    custom_by_key: dict[str, int] = {}
    for item in custom or []:
        host = str(item.get("host") or "").strip()
        try:
            rport = int(item.get("port"))
            lport = int(item.get("local_port"))
        except (TypeError, ValueError):
            continue
        if host and 1 <= lport <= 65535 and 1 <= rport <= 65535:
            custom_by_key[f"{host}:{rport}"] = lport

    used: set[int] = set()
    forwards: list[dict[str, Any]] = []

    def _rand_port() -> int:
        # Prefer high range unlikely to clash with local services
        for _ in range(64):
            p = random.randint(20000, 49999)
            if p not in used:
                return p
        p = 20000
        while p in used and p < 65000:
            p += 1
        return p

    for d in destinations:
        host = d["host"]
        rport = int(d["port"])
        key = f"{host}:{rport}"
        label = d.get("label") or ""

        if mode == "custom" and key in custom_by_key:
            lp = custom_by_key[key]
        elif mode == "custom" and d.get("local_port") is not None:
            try:
                lp = int(d["local_port"])
            except (TypeError, ValueError):
                lp = rport if rport >= 1024 else _rand_port()
        elif mode == "same":
            lp = rport if rport >= 1024 else _rand_port()
        else:  # random
            lp = _rand_port()

        if lp in used:
            lp = _rand_port()
        used.add(lp)
        forwards.append(
            {
                "local_port": lp,
                "host": host,
                "port": rport,
                "label": label,
                "mode": mode,
            }
        )
    return forwards


def build_ssh_config(
    username: str,
    *,
    options: dict[str, Any] | None = None,
    local_forwards: list[dict[str, Any]] | None = None,
    local_port_mode: str = "random",
    identity_file: str | None = None,
    host_alias: str | None = None,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    opts = _opts(options)
    meta = _load_meta(opts["data_dir"], username)
    if meta is None:
        return {"ok": False, "error": "Tunnel user not found"}

    dests = meta.get("destinations") or []
    alias = host_alias or f"tunnel-{username}"
    # Default identity matches generated RSA 4096 filename convention
    identity = identity_file or f"~/.ssh/{username}_rsa4096"
    hostname = opts["public_hostname"]
    ssh_port = opts["public_port"]
    mode = (local_port_mode or "random").strip().lower()

    if local_forwards is not None:
        # Explicit list from client — fill missing local_port by mode
        normalized: list[dict[str, Any]] = []
        used: set[int] = set()
        for fw in local_forwards:
            host = str(fw.get("host") or "").strip()
            try:
                rport = int(fw.get("port"))
            except (TypeError, ValueError):
                continue
            if not host or not (1 <= rport <= 65535):
                continue
            lp_raw = fw.get("local_port")
            if lp_raw is None or lp_raw == "":
                if mode == "same" and rport >= 1024:
                    lp = rport
                else:
                    lp = random.randint(20000, 49999)
                    while lp in used:
                        lp = random.randint(20000, 49999)
            else:
                try:
                    lp = int(lp_raw)
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"Invalid local_port for {host}:{rport}"}
            if not (1 <= lp <= 65535):
                return {"ok": False, "error": f"local_port out of range: {lp}"}
            if lp in used:
                return {"ok": False, "error": f"Duplicate local_port {lp}"}
            used.add(lp)
            normalized.append(
                {
                    "local_port": lp,
                    "host": host,
                    "port": rport,
                    "label": fw.get("label") or "",
                }
            )
        forwards = normalized
    else:
        forwards = _allocate_local_ports(dests, mode=mode)

    lines = [
        f"# SSH tunnel via {hostname} — user {username}",
        f"# Generated by Linux Admin",
        f"# Local ports mode: {mode} — on client conflict, change the left LocalForward port",
        f"Host {alias}",
        f"  HostName {hostname}",
        f"  User {username}",
        f"  Port {ssh_port}",
        f"  IdentityFile {identity}",
        "  IdentitiesOnly yes",
        "  ExitOnForwardFailure yes",
        "  ServerAliveInterval 30",
        "  ServerAliveCountMax 3",
        "  RequestTTY no",
    ]

    for fw in forwards:
        lp = int(fw["local_port"])
        host = fw["host"]
        rport = int(fw["port"])
        label = (fw.get("label") or "").strip()
        note = f" — {label}" if label else ""
        if lp != rport:
            lines.append(f"  # localhost:{lp} → {host}:{rport}{note}")
        else:
            lines.append(f"  # same port{note}")
        lines.append(f"  LocalForward {lp} {host}:{rport}")

    lines.append("")
    lines.append(f"# Connect: ssh -N {alias}")
    lines.append("# Connect to the service on the client: localhost:<local_port>")

    identity_base = identity.replace("\\", "/").rstrip("/").split("/")[-1]
    user_owned_key = identity_base in {"id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"} or identity_base.startswith(
        "id_"
    )
    if user_owned_key:
        usage = [
            f"1. Use your existing private key at {identity} (chmod 600) — not included when only pubkey was added",
            "2. Add the Host block to ~/.ssh/config (adjust IdentityFile if your key path differs)",
            f"3. Start the tunnel: ssh -N {alias}",
            "4. Local ports can be changed in LocalForward (left number) if they are busy on the PC",
        ]
    else:
        usage = [
            f"1. Save the private key to {identity} (chmod 600)",
            "2. Add the Host block to ~/.ssh/config",
            f"3. Start the tunnel: ssh -N {alias}",
            "4. Local ports can be changed in LocalForward (left number) if they are busy on the PC",
        ]
    for fw in forwards:
        usage.append(
            f"   → localhost:{fw['local_port']} → {fw['host']}:{fw['port']}"
            + (f" ({fw['label']})" if fw.get("label") else "")
        )

    return {
        "ok": True,
        "username": username,
        "host_alias": alias,
        "identity_file": identity,
        "config": "\n".join(lines) + "\n",
        "forwards": forwards,
        "destinations": dests,
        "local_port_mode": mode,
        "usage": usage,
        "public_hostname": hostname,
        "public_port": opts["public_port"],
    }


def _identity_basename(identity_file: str, username: str) -> str:
    name = (identity_file or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", ".."):
        return f"{username}_rsa4096"
    # keep only safe filename chars
    safe = re.sub(r"[^\w.+=@-]", "_", name)
    return safe[:120] or f"{username}_rsa4096"


def _looks_like_private_key(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("-----BEGIN") and "PRIVATE KEY-----" in t and "-----END" in t


def build_instructions_html(pack: dict[str, Any]) -> str:
    """Premium standalone HTML guide for the client ZIP package."""
    username = html.escape(str(pack.get("username") or ""))
    alias = html.escape(str(pack.get("host_alias") or f"tunnel-{pack.get('username')}"))
    hostname = html.escape(str(pack.get("public_hostname") or ""))
    port = int(pack.get("public_port") or 22)
    identity = html.escape(str(pack.get("identity_file") or f"~/.ssh/{pack.get('username')}_rsa4096"))
    key_name = html.escape(
        str(
            pack.get("private_key_filename")
            or _identity_basename(identity, str(pack.get("username") or "tunnel"))
        )
    )
    has_key = bool(pack.get("has_private_key"))
    config = html.escape(str(pack.get("config") or ""))
    forwards = pack.get("forwards") or []

    forward_rows = []
    forward_cards = []
    for fw in forwards:
        lp = int(fw.get("local_port") or 0)
        host = html.escape(str(fw.get("host") or ""))
        rport = int(fw.get("port") or 0)
        label = html.escape(str(fw.get("label") or "").strip() or "Service")
        forward_rows.append(
            f"<tr><td>{label}</td><td><code>localhost:{lp}</code></td>"
            f"<td><code>{host}:{rport}</code></td>"
            f"<td><code>ssh -p {lp} user@127.0.0.1</code></td></tr>"
        )
        forward_cards.append(
            f'<div class="map"><span class="pill">localhost:{lp}</span>'
            f'<span class="arrow">→</span><span class="pill dim">{host}:{rport}</span>'
            f'<span class="lbl">{label}</span></div>'
        )
    forwards_table = "\n".join(forward_rows) or (
        "<tr><td colspan='4'>Назначения ещё не заданы — попросите администратора добавить destinations.</td></tr>"
    )
    forwards_maps = "\n".join(forward_cards) or '<p class="muted">Нет LocalForward в этом пакете.</p>'

    first_lp = int(forwards[0]["local_port"]) if forwards else 22022
    first_label = html.escape(str((forwards[0].get("label") if forwards else None) or "remote host"))
    # Example hosts/ports for LocalForward syntax section (prefer real pack destinations)
    ex_http = next((fw for fw in forwards if int(fw.get("port") or 0) in (80, 443, 8080)), None)
    ex_api = next((fw for fw in forwards if int(fw.get("port") or 0) in (8000, 8443, 3000)), None)
    ex_ssh = next((fw for fw in forwards if int(fw.get("port") or 0) == 22), forwards[0] if forwards else None)
    ex_http_host = html.escape(str((ex_http or {}).get("host") or "192.168.130.8"))
    ex_http_rport = int((ex_http or {}).get("port") or 80)
    ex_http_lport = int((ex_http or {}).get("local_port") or 8080)
    ex_api_host = html.escape(str((ex_api or {}).get("host") or "192.168.130.8"))
    ex_api_rport = int((ex_api or {}).get("port") or 8000)
    ex_api_lport = int((ex_api or {}).get("local_port") or 8000)
    ex_ssh_host = html.escape(str((ex_ssh or {}).get("host") or "192.168.130.8"))
    ex_ssh_rport = int((ex_ssh or {}).get("port") or 22)
    ex_ssh_lport = int((ex_ssh or {}).get("local_port") or first_lp)

    # Host blocks for IDE Remote SSH (destinations that look like SSH)
    ide_host_blocks: list[str] = []
    ide_ssh_forwards = [
        fw
        for fw in forwards
        if int(fw.get("port") or 0) == 22
        or "ssh" in str(fw.get("label") or "").lower()
    ]
    if not ide_ssh_forwards and forwards:
        # still show an example using the first forward
        ide_ssh_forwards = [forwards[0]]
    for idx, fw in enumerate(ide_ssh_forwards):
        lp = int(fw.get("local_port") or 0)
        label_raw = str(fw.get("label") or "").strip() or f"host-{idx + 1}"
        safe_alias = re.sub(r"[^\w.-]+", "-", label_raw.lower()).strip("-")[:40] or f"dev-{idx + 1}"
        host_alias_ide = f"via-tunnel-{safe_alias}"
        ide_host_blocks.append(
            f"Host {host_alias_ide}\n"
            f"  HostName 127.0.0.1\n"
            f"  Port {lp}\n"
            f"  User yourlogin\n"
            f"  # IdentityFile ~/.ssh/id_ed25519   # ключ УЧЁТКИ на целевом сервере\n"
            f"  IdentitiesOnly yes"
        )
    ide_hosts_pre = html.escape(
        "\n\n".join(ide_host_blocks)
        if ide_host_blocks
        else (
            f"Host via-tunnel-dev\n"
            f"  HostName 127.0.0.1\n"
            f"  Port {first_lp}\n"
            f"  User yourlogin\n"
            f"  IdentitiesOnly yes"
        )
    )
    first_ide_alias = "via-tunnel-dev"
    if ide_host_blocks:
        m = re.search(r"^Host\s+(\S+)", ide_host_blocks[0], re.M)
        if m:
            first_ide_alias = html.escape(m.group(1))

    if has_key:
        key_chip = f'<div class="chip">Key in ZIP <strong class="mono">{key_name}</strong></div>'
        key_file_card = (
            f"<div class='file'><div class='ico'>03</div><div><strong>{key_name}</strong>"
            f"<div class='muted'>Приватный SSH-ключ из архива. Храните только у себя.</div></div></div>"
        )
        install_key_section = f"""
      <section id="install-key">
        <h2>1. Установка приватного ключа</h2>
        <p class="lead">В архиве есть файл ключа <code>{key_name}</code> — скопируйте его в <code>~/.ssh/</code>.</p>
        <div class="steps">
          <div class="step">
            <div>
              <strong>Создайте каталог ~/.ssh (если его нет)</strong>
              <pre>mkdir -p ~/.ssh
chmod 700 ~/.ssh</pre>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Скопируйте ключ и ограничьте права</strong>
              <pre>cp {key_name} ~/.ssh/{key_name}
chmod 600 ~/.ssh/{key_name}</pre>
              <p>На Windows (OpenSSH): свойства файла → безопасность → доступ только вашей учётной записи.</p>
            </div>
          </div>
        </div>
        <div class="callout warn">
          Без <code>chmod 600</code> OpenSSH часто отказывается использовать ключ
          (<em>WARNING: UNPROTECTED PRIVATE KEY FILE</em>).
        </div>
      </section>"""
        windows_key_steps = f"""mkdir $env:USERPROFILE\\.ssh
copy {key_name} $env:USERPROFILE\\.ssh\\{key_name}
# права: только ваша учётка (Properties → Security)

notepad $env:USERPROFILE\\.ssh\\config
# вставьте содержимое ssh_config; IdentityFile должен указывать на ключ:
# IdentityFile C:\\Users\\YOU\\.ssh\\{key_name}

ssh -N {alias}"""
        unix_key_steps = f"""chmod 700 ~/.ssh
cp {key_name} {identity}
chmod 600 {identity}
cat ssh_config >> ~/.ssh/config
chmod 600 ~/.ssh/config
ssh -N {alias}"""
        identity_callout = (
            f"Параметр <code>IdentityFile {identity}</code> должен указывать на файл ключа из архива. "
            "Если положили ключ в другое место — поправьте путь."
        )
        hero_note = (
            "В этом пакете <strong>есть приватный ключ</strong>. Не пересылайте ZIP в открытых чатах — "
            "лучше передать архив защищённым каналом."
        )
    else:
        key_chip = (
            '<div class="chip">Key mode <strong>свой ключ (BYOK)</strong></div>'
        )
        key_file_card = (
            "<div class='file'><div class='ico'>03</div><div><strong>Приватный ключ — не в архиве</strong>"
            "<div class='muted'>Вы (или разработчик) прислали администратору только <em>публичный</em> ключ. "
            "Приватный ключ остаётся у вас на ПК — в ZIP его нет и не должно быть.</div></div></div>"
        )
        install_key_section = f"""
      <section id="install-key">
        <h2>1. Ваш приватный ключ (BYOK)</h2>
        <p class="lead">
          Администратор добавил на jump-хост <strong>ваш публичный ключ</strong>.
          Приватный ключ <strong>не входит</strong> в этот ZIP — он уже должен быть у вас
          (типичные пути: <code>~/.ssh/id_ed25519</code>, <code>~/.ssh/id_rsa</code>).
        </p>
        <div class="callout">
          Это нормальный и предпочтительный сценарий для разработчиков:
          вы генерируете пару ключей у себя → отправляете только <code>.pub</code> →
          получаете пакет с <code>ssh_config</code> и инструкцией.
        </div>
        <div class="steps">
          <div class="step">
            <div>
              <strong>Проверьте, что приватный ключ на месте</strong>
              <pre>ls -la ~/.ssh/
# ожидайте файл без суффикса .pub, например:
# id_ed25519     ← приватный (никому не отправлять)
# id_ed25519.pub ← публичный (его как раз принимают на сервере)</pre>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Укажите путь в IdentityFile</strong>
              <p>В <code>ssh_config</code> сейчас задано:</p>
              <pre>IdentityFile {identity}</pre>
              <p>Если ваш ключ лежит иначе — поправьте строку, например:</p>
              <pre>IdentityFile ~/.ssh/id_ed25519
# или
IdentityFile ~/.ssh/id_rsa
# или
IdentityFile ~/.ssh/my_work_key</pre>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Права на ключ</strong>
              <pre>chmod 700 ~/.ssh
chmod 600 {identity}</pre>
            </div>
          </div>
        </div>
        <div class="callout warn">
          Публичный и приватный ключ — пара. Если на сервере лежит не тот <code>.pub</code>,
          или <code>IdentityFile</code> указывает не на парный приватный файл, будет
          <em>Permission denied (publickey)</em>.
        </div>
      </section>"""
        windows_key_steps = f"""# Приватный ключ уже у вас — в ZIP его нет.
# Убедитесь, что файл существует, например:
#   C:\\Users\\YOU\\.ssh\\id_ed25519

notepad $env:USERPROFILE\\.ssh\\config
# вставьте ssh_config и при необходимости поправьте:
# IdentityFile C:\\Users\\YOU\\.ssh\\id_ed25519

ssh -N {alias}"""
        unix_key_steps = f"""# Приватный ключ уже у вас (не копируется из ZIP)
ls -la {identity}
chmod 600 {identity}
cat ssh_config >> ~/.ssh/config
chmod 600 ~/.ssh/config
# при необходимости отредактируйте IdentityFile в ~/.ssh/config
ssh -N {alias}"""
        identity_callout = (
            f"Режим <strong>свой ключ</strong>: <code>IdentityFile {identity}</code> должен указывать "
            "на <em>ваш</em> существующий приватный ключ (тот, чья публичная часть уже на сервере)."
        )
        hero_note = (
            "Приватный ключ <strong>не включён</strong> в пакет — использован ваш публичный ключ (BYOK). "
            "Настройте <code>IdentityFile</code> на путь к своему приватному ключу."
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SSH Tunnel — {username}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
:root {{
  --bg0: #07111f;
  --bg1: #0c1a2e;
  --bg2: #12263f;
  --card: rgba(18, 38, 63, 0.72);
  --line: rgba(148, 163, 184, 0.18);
  --text: #e8eef7;
  --muted: #94a3b8;
  --accent: #14b8a6;
  --accent2: #38bdf8;
  --warn: #f59e0b;
  --danger: #f43f5e;
  --ok: #34d399;
  --shadow: 0 24px 80px rgba(0,0,0,.45);
  --radius: 18px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  font-family: Outfit, "Segoe UI", sans-serif;
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(20,184,166,.22), transparent 55%),
    radial-gradient(900px 500px at 90% 0%, rgba(56,189,248,.16), transparent 50%),
    linear-gradient(180deg, var(--bg0), var(--bg1) 40%, #081525);
  line-height: 1.55;
}}
a {{ color: var(--accent2); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code, pre, .mono {{ font-family: "IBM Plex Mono", ui-monospace, monospace; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }}
.hero {{
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 6px);
  background: linear-gradient(145deg, rgba(20,184,166,.12), rgba(15,23,42,.55) 45%, rgba(56,189,248,.08));
  box-shadow: var(--shadow);
  padding: 36px 32px 28px;
  margin-bottom: 22px;
}}
.hero::after {{
  content: "";
  position: absolute; inset: auto -20% -40% 40%;
  height: 220px;
  background: radial-gradient(circle, rgba(20,184,166,.25), transparent 65%);
  pointer-events: none;
}}
.eyebrow {{
  display: inline-flex; gap: 8px; align-items: center;
  font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin-bottom: 12px;
}}
.hero h1 {{
  margin: 0 0 10px; font-size: clamp(1.8rem, 4vw, 2.5rem); letter-spacing: -0.03em; font-weight: 700;
}}
.hero p {{ margin: 0; max-width: 62ch; color: var(--muted); font-size: 1.05rem; }}
.meta {{
  display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px;
}}
.chip {{
  border: 1px solid var(--line); background: rgba(2,8,23,.35);
  border-radius: 999px; padding: 8px 14px; font-size: 13px; color: var(--muted);
}}
.chip strong {{ color: var(--text); font-weight: 600; }}
.layout {{ display: grid; grid-template-columns: 240px 1fr; gap: 18px; }}
@media (max-width: 860px) {{ .layout {{ grid-template-columns: 1fr; }} .toc {{ position: static !important; }} }}
.toc {{
  position: sticky; top: 18px; align-self: start;
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--card); backdrop-filter: blur(10px);
  padding: 18px 16px;
}}
.toc h2 {{ margin: 0 0 12px; font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }}
.toc ol {{ margin: 0; padding-left: 18px; }}
.toc li {{ margin: 8px 0; }}
.toc a {{ color: var(--text); font-size: 14px; }}
.toc a:hover {{ color: var(--accent); }}
main section {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--card); backdrop-filter: blur(10px);
  padding: 26px 24px; margin-bottom: 16px;
  scroll-margin-top: 18px;
}}
main h2 {{
  margin: 0 0 8px; font-size: 1.35rem; letter-spacing: -0.02em;
}}
main h3 {{ margin: 22px 0 8px; font-size: 1.05rem; color: #dbeafe; }}
.lead {{ color: var(--muted); margin: 0 0 16px; }}
.steps {{ counter-reset: step; display: grid; gap: 12px; }}
.step {{
  counter-increment: step;
  display: grid; grid-template-columns: 36px 1fr; gap: 12px;
  padding: 14px; border-radius: 14px; border: 1px solid var(--line);
  background: rgba(2,8,23,.28);
}}
.step::before {{
  content: counter(step);
  width: 36px; height: 36px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(145deg, var(--accent), #0f766e);
  color: #042f2e; font-weight: 700;
}}
.step strong {{ display: block; margin-bottom: 4px; }}
.step p {{ margin: 0; color: var(--muted); font-size: 14px; }}
pre {{
  margin: 12px 0 0; padding: 14px 16px; overflow: auto;
  border-radius: 12px; border: 1px solid var(--line);
  background: #020617; color: #e2e8f0; font-size: 12.5px; line-height: 1.5;
}}
.callout {{
  border-left: 3px solid var(--accent);
  background: rgba(20,184,166,.08);
  padding: 12px 14px; border-radius: 0 12px 12px 0;
  color: var(--muted); margin: 14px 0;
}}
.callout.warn {{ border-left-color: var(--warn); background: rgba(245,158,11,.08); }}
.callout.danger {{ border-left-color: var(--danger); background: rgba(244,63,94,.08); }}
table {{
  width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 10px;
}}
th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; }}
.map {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px;
  background: rgba(2,8,23,.28); margin: 8px 0;
}}
.pill {{
  font-family: "IBM Plex Mono", monospace; font-size: 12px;
  padding: 5px 10px; border-radius: 999px;
  background: rgba(20,184,166,.15); color: #99f6e4; border: 1px solid rgba(20,184,166,.35);
}}
.pill.dim {{ background: rgba(56,189,248,.12); color: #bae6fd; border-color: rgba(56,189,248,.3); }}
.arrow {{ color: var(--muted); }}
.lbl {{ color: var(--muted); font-size: 13px; margin-left: 4px; }}
.muted {{ color: var(--muted); }}
.files {{ display: grid; gap: 10px; }}
.file {{
  display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: start;
  padding: 12px; border-radius: 12px; border: 1px solid var(--line); background: rgba(2,8,23,.25);
}}
.file .ico {{
  width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
  background: rgba(20,184,166,.15); color: var(--accent); font-size: 14px;
}}
.topbar {{
  display: flex; justify-content: space-between; gap: 12px; align-items: center;
  margin-bottom: 18px; flex-wrap: wrap;
}}
.brand {{ font-weight: 700; letter-spacing: -0.02em; }}
.brand span {{ color: var(--accent); }}
.footer {{
  margin-top: 28px; color: var(--muted); font-size: 13px; text-align: center;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand">Linux Admin <span>·</span> SSH Tunnel</div>
    <a href="#toc">К разделам ↓</a>
  </div>

  <header class="hero" id="overview">
    <div class="eyebrow">Client setup pack</div>
    <h1>Инструкция по SSH-туннелю</h1>
    <p>
      Этот пакет настраивает безопасный доступ через jump-хост
      <strong>{hostname}</strong> под учётной записью <strong class="mono">{username}</strong>.
      Туннель не даёт shell на сервере — только проброс портов к разрешённым сервисам.
    </p>
    <p style="margin:14px 0 0;color:var(--muted);max-width:70ch">{hero_note}</p>
    <div class="meta">
      <div class="chip">Host alias <strong class="mono">{alias}</strong></div>
      <div class="chip">Jump <strong class="mono">{hostname}:{port}</strong></div>
      {key_chip}
      <div class="chip">IdentityFile <strong class="mono">{identity}</strong></div>
      <div class="chip">Mode <strong>ssh -N</strong></div>
    </div>
  </header>

  <div class="layout">
    <nav class="toc" id="toc" aria-label="Содержание">
      <h2>Содержание</h2>
      <ol>
        <li><a href="#overview">Обзор</a></li>
        <li><a href="#contents">Содержимое ZIP</a></li>
        <li><a href="#install-key">Ключ (свой / из ZIP)</a></li>
        <li><a href="#ssh-config">SSH config</a></li>
        <li><a href="#start-tunnel">Запуск туннеля</a></li>
        <li><a href="#use-services">Доступ к сервисам</a></li>
        <li><a href="#localforward">Синтаксис LocalForward</a></li>
        <li><a href="#examples">Примеры</a></li>
        <li><a href="#ide">VS Code / Cursor / IDE</a></li>
        <li><a href="#windows">Windows</a></li>
        <li><a href="#macos-linux">macOS / Linux</a></li>
        <li><a href="#troubleshooting">Проблемы</a></li>
        <li><a href="#security">Безопасность</a></li>
      </ol>
    </nav>

    <main>
      <section id="contents">
        <h2>Содержимое ZIP</h2>
        <p class="lead">Распакуйте архив в удобное место. Откройте этот файл (<code>instructions.html</code>) в браузере.</p>
        <div class="files">
          <div class="file"><div class="ico">01</div><div><strong>instructions.html</strong><div class="muted">Эта инструкция со всеми разделами и примерами.</div></div></div>
          <div class="file"><div class="ico">02</div><div><strong>ssh_config</strong><div class="muted">Блок <code>Host</code> для вставки в <code>~/.ssh/config</code>.</div></div></div>
          {key_file_card}
          <div class="file"><div class="ico">04</div><div><strong>README.txt</strong><div class="muted">Краткая шпаргалка на случай, если HTML не открывается.</div></div></div>
        </div>
      </section>

      {install_key_section}

      <section id="ssh-config">
        <h2>2. Добавление SSH config</h2>
        <p class="lead">
          Откройте (или создайте) файл <code>~/.ssh/config</code> и добавьте блок из <code>ssh_config</code>.
          Либо скопируйте фрагмент ниже целиком.
        </p>
        <div class="steps">
          <div class="step">
            <div>
              <strong>Linux / macOS</strong>
              <pre>nano ~/.ssh/config
# вставьте блок Host … затем:
chmod 600 ~/.ssh/config</pre>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Быстрая склейка из файла пакета</strong>
              <pre>cat ssh_config >> ~/.ssh/config
chmod 600 ~/.ssh/config</pre>
            </div>
          </div>
        </div>
        <h3>Готовый блок для этого пользователя</h3>
        <pre>{config}</pre>
        <div class="callout">
          {identity_callout}
        </div>
      </section>

      <section id="start-tunnel">
        <h2>3. Запуск туннеля</h2>
        <p class="lead">
          Учётная запись туннеля <strong>не даёт интерактивный shell</strong>.
          Всегда используйте флаг <code>-N</code> (no remote command).
        </p>
        <pre>ssh -N {alias}</pre>
        <p class="muted">Команда «зависает» без приглашения — это нормально: туннель работает, пока окно открыто.</p>
        <div class="callout">
          Фоновый запуск (Linux/macOS): <code>ssh -fN {alias}</code><br/>
          Проверка: <code>ssh -N -v {alias}</code> (подробный лог).
        </div>
        <h3>Карта пробросов</h3>
        {forwards_maps}
      </section>

      <section id="use-services">
        <h2>4. Подключение к сервисам через localhost</h2>
        <p class="lead">
          После старта туннеля сервисы доступны на <strong>вашем компьютере</strong> как
          <code>localhost:&lt;локальный_порт&gt;</code>. Не подключайтесь напрямую к внутренним IP из интернета.
        </p>
        <table>
          <thead>
            <tr><th>Сервис</th><th>Локально</th><th>Куда ведёт</th><th>Пример</th></tr>
          </thead>
          <tbody>
            {forwards_table}
          </tbody>
        </table>
        <div class="callout warn">
          Если локальный порт занят — измените <em>левое</em> число в <code>LocalForward</code>
          (например <code>41736</code> → <code>45001</code>) и перезапустите туннель.
        </div>
      </section>

      <section id="localforward">
        <h2>Синтаксис LocalForward (важно)</h2>
        <p class="lead">
          Формат OpenSSH: слева — <strong>порт на вашем ПК</strong>, справа — куда идти с jump-хоста.
        </p>
        <pre>LocalForward &lt;локальный_порт&gt; &lt;хост&gt;:&lt;порт&gt;

# правильно — веб на http://127.0.0.1:{ex_http_lport}
LocalForward {ex_http_lport} {ex_http_host}:{ex_http_rport}

# правильно — API/панель на http://127.0.0.1:{ex_api_lport}
LocalForward {ex_api_lport} {ex_api_host}:{ex_api_rport}

# правильно — SSH на целевой сервер
LocalForward {ex_ssh_lport} {ex_ssh_host}:{ex_ssh_rport}</pre>
        <div class="callout danger">
          <strong>Частая ошибка:</strong> писать IP слева или одинаковые «удалённые» адреса с обеих сторон.
          Так <em>не работает</em>:
          <pre style="margin-top:10px"># НЕПРАВИЛЬНО — слева должен быть локальный порт ПК, не 192.168.x.x
LocalForward {ex_http_host}:{ex_http_rport} {ex_http_host}:{ex_http_rport}
LocalForward {ex_api_host}:{ex_api_rport} {ex_api_host}:{ex_api_rport}</pre>
        </div>
        <h3>Почему не открывается «localhost:80»</h3>
        <ul>
          <li>В браузере нужен адрес вида <code>http://127.0.0.1:{ex_http_lport}</code> — тот порт, что <em>слева</em> в <code>LocalForward</code>.</li>
          <li>Порт <strong>80</strong> на вашем ПК часто занят (IIS, Skype, другой nginx) или требует прав администратора. Поэтому обычно используют высокий порт (например <strong>{ex_http_lport}</strong>), а не 80.</li>
          <li>Не открывайте в браузере внутренний IP <code>http://{ex_http_host}</code> с домашнего ПК — он недоступен без туннеля. Работает только через <code>127.0.0.1:&lt;локальный_порт&gt;</code>.</li>
          <li>Не дописывайте свои <code>LocalForward</code> «наугад»: справа разрешены только destinations из панели администратора. Иначе будет <em>administratively prohibited</em>.</li>
        </ul>
        <div class="callout">
          Лучше взять готовый блок из файла <code>ssh_config</code> этого ZIP (или заново скачать пакет в Linux Admin),
          чем править порты вручную.
        </div>
      </section>

      <section id="examples">
        <h2>Примеры использования</h2>
        <h3>SSH на внутренний хост (типичный PTO / server)</h3>
        <pre># 1) в одном терминале:
ssh -N {alias}

# 2) в другом терминале — SSH на сервис за туннелем:
ssh -p {first_lp} yourlogin@127.0.0.1
# ({first_label})</pre>
        <h3>SCP / SFTP через тот же порт</h3>
        <pre>scp -P {first_lp} ./file.txt yourlogin@127.0.0.1:/tmp/
sftp -P {first_lp} yourlogin@127.0.0.1</pre>
        <h3>RDP / веб / БД</h3>
        <pre># RDP (если проброшен 3389 → локальный порт L):
# подключайтесь к 127.0.0.1:L в клиенте Remote Desktop

# HTTP/HTTPS:
# http://127.0.0.1:L

# PostgreSQL / другой TCP:
# host=127.0.0.1  port=L</pre>
        <h3>Проверка, что порт слушает</h3>
        <pre># Linux/macOS
nc -vz 127.0.0.1 {first_lp}

# или
ssh -N -v {alias}   # ищите Local forwarding listening</pre>
      </section>

      <section id="ide">
        <h2>VS Code, Cursor и другие IDE (Remote SSH)</h2>
        <p class="lead">
          Редакторы вроде <strong>VS Code</strong>, <strong>Cursor</strong>, VSCodium, а также JetBrains Gateway
          умеют открывать папку на удалённом Linux-хосте по SSH. Через этот туннель вы подключаетесь
          не к jump-пользователю, а к <strong>целевому серверу</strong> на <code>localhost:&lt;порт&gt;</code>.
        </p>

        <div class="callout danger">
          <strong>Не подключайте Remote SSH к аккаунту туннеля</strong>
          (<code>{username}</code> / alias <code>{alias}</code>).
          У него shell <code>nologin</code> — IDE получит
          «This account is currently not available» / PTY failed.
          Сначала поднимите туннель <code>ssh -N</code>, затем в IDE открывайте
          <em>хост за пробросом</em> (обычно порт 22 внутреннего сервера).
        </div>

        <div class="steps">
          <div class="step">
            <div>
              <strong>Запустите туннель и оставьте его работать</strong>
              <pre>ssh -N {alias}</pre>
              <p>Пока туннель жив, на ПК слушает локальный порт (например <code>{first_lp}</code> → {first_label}).</p>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Добавьте Host для IDE в ~/.ssh/config</strong>
              <p>
                Это <em>отдельный</em> блок от tunnel-alias: он смотрит на <code>127.0.0.1</code>
                и использует логин/ключ <strong>учётной записи на целевом сервере</strong>
                (не ключ jump-туннеля, если это разные ключи).
              </p>
              <pre>{ide_hosts_pre}</pre>
              <p class="muted">Замените <code>yourlogin</code> и при необходимости <code>IdentityFile</code>.</p>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>VS Code</strong>
              <p>Расширение <em>Remote - SSH</em> (Microsoft).</p>
              <pre>1. F1 / Ctrl+Shift+P → “Remote-SSH: Connect to Host…”
2. Выберите {first_ide_alias} (или введите yourlogin@127.0.0.1:{first_lp})
3. Откройте папку проекта на сервере (Open Folder)</pre>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Cursor</strong>
              <p>Тот же Remote SSH (командная палитра как в VS Code).</p>
              <pre>1. Ctrl+Shift+P (Cmd+Shift+P на macOS)
2. “Remote-SSH: Connect to Host…” → {first_ide_alias}
3. Дождитесь установки VS Code Server / Cursor server на удалённой машине
4. File → Open Folder</pre>
              <p class="muted">
                Убедитесь, что на целевом хосте есть исходящий доступ для скачивания server-компонента
                (или офлайн-установка по документации Cursor/VS Code).
              </p>
            </div>
          </div>
          <div class="step">
            <div>
              <strong>Проверка из терминала IDE</strong>
              <pre># после Connect to Host в встроенном терминале IDE вы уже на удалённом хосте:
hostname
pwd</pre>
            </div>
          </div>
        </div>

        <h3>JetBrains (Gateway / IDEA / PyCharm)</h3>
        <pre># 1) ssh -N {alias}
# 2) JetBrains Gateway → SSH → New Connection
#    Host: 127.0.0.1
#    Port: {first_lp}
#    Username: yourlogin
#    Authentication: ключ учётной записи на целевом сервере</pre>

        <h3>Одной схемой</h3>
        <pre>Ваш ПК
  │
  ├─ ssh -N {alias}          ← туннель (jump, без shell)
  │     LocalForward {first_lp} → внутренний SSH
  │
  └─ VS Code / Cursor Remote-SSH
        Host {first_ide_alias} = 127.0.0.1:{first_lp}
        User yourlogin         ← обычный пользователь целевого сервера</pre>

        <div class="callout warn">
          Если IDE пишет <em>Could not establish connection</em> — чаще всего не запущен
          <code>ssh -N {alias}</code>, занят/изменён локальный порт, или неверный User/ключ
          для <em>целевого</em> хоста (не для jump).
        </div>
      </section>

      <section id="windows">
        <h2>Windows</h2>
        <p class="lead">Подойдёт встроенный OpenSSH (Windows 10/11) или клиент вроде PuTTY/Bitvise.</p>
        <h3>OpenSSH (рекомендуется)</h3>
        <pre>{windows_key_steps}</pre>
        <h3>Путь к config</h3>
        <p class="muted">Обычно: <code>C:\\Users\\&lt;User&gt;\\.ssh\\config</code></p>
      </section>

      <section id="macos-linux">
        <h2>macOS / Linux</h2>
        <pre>{unix_key_steps}</pre>
        <div class="callout">
          Первый раз SSH спросит fingerprint хоста <code>{hostname}</code> — сравните с тем, что дал администратор, затем введите <code>yes</code>.
        </div>
      </section>

      <section id="troubleshooting">
        <h2>Типичные проблемы</h2>
        <h3>«This account is currently not available» / PTY allocation failed</h3>
        <p class="muted">Запустили без <code>-N</code>. Нужно: <code>ssh -N {alias}</code>.</p>
        <h3>«Permission denied (publickey)»</h3>
        <p class="muted">
          Неверный ключ, путь в <code>IdentityFile</code>, или права на файл не 600.
          {" В режиме своего ключа проверьте, что на сервере добавлен именно парный .pub к вашему приватному файлу." if not has_key else ""}
          Добавьте <code>-v</code> для диагностики.
        </p>
        <h3>«bind: Address already in use»</h3>
        <p class="muted">Локальный порт занят. Смените левый порт в <code>LocalForward</code>.</p>
        <h3>«channel … administratively prohibited»</h3>
        <p class="muted">
          Проброс на <code>host:port</code>, которого нет в разрешённых destinations, либо опечатка в IP/порту справа
          (например <code>192.168.130.8:8000</code> вместо того, что задал администратор).
          См. также <a href="#localforward">синтаксис LocalForward</a>.
        </p>
        <h3>Веб не открывается на localhost:80 / «сам дописал LocalForward»</h3>
        <p class="muted">
          Слева в <code>LocalForward</code> должен быть порт на ПК (например <code>{ex_http_lport}</code>), не
          <code>{ex_http_host}:{ex_http_rport}</code>. В браузере:
          <code>http://127.0.0.1:{ex_http_lport}</code>
          (и <code>http://127.0.0.1:{ex_api_lport}</code> для бэкенда).
          Подробнее — <a href="#localforward">раздел LocalForward</a>.
        </p>
        <h3>Туннель сразу закрывается</h3>
        <p class="muted">Проверьте сеть/VPN до <code>{hostname}:{port}</code>, время на ПК, и что ключ соответствует пользователю <code>{username}</code>.</p>
        <h3>VS Code / Cursor: «Could not establish connection» / nologin</h3>
        <p class="muted">
          IDE подключили к jump-пользователю <code>{username}</code> или туннель не запущен.
          Нужно: (1) <code>ssh -N {alias}</code>, (2) Remote-SSH на <code>127.0.0.1:{first_lp}</code>
          под логином целевого сервера — см. <a href="#ide">раздел IDE</a>.
        </p>
      </section>

      <section id="security">
        <h2>Безопасность</h2>
        <ul>
          <li>Приватный ключ — как пароль. Не публикуйте его в Telegram/почте без шифрования.</li>
          <li>Не копируйте ключ на чужие компьютеры.</li>
          <li>При компрометации — сразу сообщите администратору: ключ отзовут и выдадут новый.</li>
          <li>Туннель даёт доступ только к явно разрешённым <code>host:port</code>, не ко всей сети.</li>
          <li>Закрывайте сессию <code>ssh -N</code>, когда работа закончена (Ctrl+C).</li>
        </ul>
        <div class="callout danger">
          Если ключ мог попасть к посторонним — считайте его скомпрометированным и запросите перевыпуск.
        </div>
      </section>
    </main>
  </div>

  <p class="footer">
    Generated by Linux Admin · user <span class="mono">{username}</span> ·
    <a href="#toc">к содержанию</a> · <a href="#overview">наверх</a>
  </p>
</div>
</body>
</html>
"""


def build_readme_txt(pack: dict[str, Any]) -> str:
    username = str(pack.get("username") or "")
    alias = str(pack.get("host_alias") or f"tunnel-{username}")
    identity = str(pack.get("identity_file") or f"~/.ssh/{username}_rsa4096")
    key_name = str(pack.get("private_key_filename") or _identity_basename(identity, username))
    has_key = bool(pack.get("has_private_key"))
    lines = [
        f"SSH Tunnel pack — {username}",
        "",
        "1) Open instructions.html in a browser (full guide).",
    ]
    if has_key:
        lines.append(f"2) Save private key from ZIP as {identity} (chmod 600). File: {key_name}")
    else:
        lines.append(
            "2) Private key is NOT in this ZIP (BYOK — you sent only the public key). "
            f"Point IdentityFile to your existing key (default in config: {identity})."
        )
    lines.extend(
        [
            "3) Append ssh_config to ~/.ssh/config",
            f"4) Start tunnel: ssh -N {alias}",
            "5) Use services via localhost:<LocalForward port>",
            "",
        ]
    )
    for fw in pack.get("forwards") or []:
        label = f" ({fw.get('label')})" if fw.get("label") else ""
        lines.append(f"   localhost:{fw.get('local_port')} -> {fw.get('host')}:{fw.get('port')}{label}")
    lines.append("")
    return "\n".join(lines)


def build_client_pack(
    username: str,
    *,
    options: dict[str, Any] | None = None,
    local_forwards: list[dict[str, Any]] | None = None,
    local_port_mode: str = "random",
    identity_file: str | None = None,
    host_alias: str | None = None,
    private_key: str | None = None,
    private_key_filename: str | None = None,
) -> dict[str, Any]:
    """Build a ZIP: instructions.html + ssh_config + optional private key (BYOK if omitted)."""
    key_text = (private_key or "").strip()
    has_key = bool(key_text) and _looks_like_private_key(key_text)
    if key_text and not has_key:
        return {"ok": False, "error": "private_key does not look like a PEM private key"}

    # Resolve IdentityFile before generating config:
    # - with key in pack → ~/.ssh/<filename>
    # - BYOK (user pubkey only) → ~/.ssh/id_ed25519 unless admin overrides
    explicit_identity = (identity_file or "").strip() or None
    if explicit_identity:
        resolved_identity = explicit_identity
        key_filename = _identity_basename(private_key_filename or resolved_identity, username)
    elif has_key:
        key_filename = _identity_basename(
            private_key_filename or f"{username}_rsa4096", username
        )
        resolved_identity = f"~/.ssh/{key_filename}"
    else:
        key_filename = "id_ed25519"
        resolved_identity = "~/.ssh/id_ed25519"

    cfg = build_ssh_config(
        username,
        options=options,
        local_forwards=local_forwards,
        local_port_mode=local_port_mode,
        identity_file=resolved_identity,
        host_alias=host_alias,
    )
    if not cfg.get("ok"):
        return cfg

    pack_meta = {
        **cfg,
        "has_private_key": has_key,
        "private_key_filename": key_filename,
        "identity_file": resolved_identity,
        "key_mode": "included" if has_key else "user_owned",
    }
    instructions = build_instructions_html(pack_meta)
    readme = build_readme_txt(pack_meta)

    folder = f"ssh-tunnel-{username}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/instructions.html", instructions)
        zf.writestr(f"{folder}/ssh_config", str(cfg.get("config") or ""))
        zf.writestr(f"{folder}/README.txt", readme)
        if has_key:
            info = zipfile.ZipInfo(f"{folder}/{key_filename}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, key_text if key_text.endswith("\n") else key_text + "\n")

    data = buf.getvalue()
    return {
        "ok": True,
        "filename": f"{folder}.zip",
        "content_type": "application/zip",
        "bytes": data,
        "size": len(data),
        "has_private_key": has_key,
        "key_mode": "included" if has_key else "user_owned",
        "identity_file": resolved_identity,
        "host_alias": cfg.get("host_alias"),
        "forwards": cfg.get("forwards"),
        "username": username,
    }


def _fmt_peer(ip: str | None, port: int | None) -> str:
    if not ip:
        return "—"
    if port is None:
        return ip
    if ":" in ip and not ip.startswith("["):
        return f"[{ip}]:{port}"
    return f"{ip}:{port}"


def _tunnel_usernames(options: dict[str, Any] | None) -> set[str]:
    opts = _opts(options)
    names = set(_list_managed_usernames(opts["data_dir"]))
    prefix = opts["username_prefix"] or "tun-"
    # Also include live OS users matching prefix (in case meta json missing)
    try:
        for ent in pwd.getpwall():
            if ent.pw_name.startswith(prefix):
                names.add(ent.pw_name)
    except Exception:
        pass
    return names


def _sshd_user_from_text(text: str) -> str | None:
    m = SSHD_USER_RE.search(text or "")
    if not m:
        return None
    name = m.group(1).strip()
    if not name or name in ("sshd", "root"):
        return None
    return name


def _resolve_sshd_session(pid: int) -> dict[str, Any] | None:
    """Map sshd connection pid to tunnel session process (prefer user@notty)."""
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None

    try:
        tree = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        tree = [root]

    best: dict[str, Any] | None = None
    for proc in tree:
        try:
            cmdline_list = proc.cmdline() or []
            cmdline = " ".join(cmdline_list)
            name = proc.name() or ""
            if "sshd" not in name.lower() and "sshd" not in cmdline.lower():
                continue
            username = _sshd_user_from_text(cmdline) or _sshd_user_from_text(name)
            if not username:
                try:
                    u = proc.username()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    u = None
                if u and u not in ("root",):
                    username = u
            if not username:
                continue
            is_priv = "[priv]" in cmdline
            info = {
                "username": username,
                "pid": int(proc.pid),
                "ppid": int(proc.ppid()) if proc.ppid() else None,
                "cmdline": (cmdline or name)[:200],
                "started_at": float(proc.create_time()),
                "is_priv": is_priv,
            }
            if best is None:
                best = info
            elif best.get("is_priv") and not is_priv:
                best = info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return best


def _sshd_listen_ports(configured: int | None = None) -> set[int]:
    """Local ports where sshd is listening (public_port may be external NAT)."""
    ports: set[int] = set()
    if configured is not None and 1 <= int(configured) <= 65535:
        ports.add(int(configured))
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.status != psutil.CONN_LISTEN:
                continue
            if not c.laddr or not c.pid:
                continue
            try:
                proc = psutil.Process(int(c.pid))
                name = (proc.name() or "").lower()
                cmdline = " ".join(proc.cmdline() or []).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if "sshd" in name or "/sshd" in cmdline or "sshd " in cmdline:
                port = getattr(c.laddr, "port", None)
                if port is not None:
                    ports.add(int(port))
    except (psutil.AccessDenied, PermissionError):
        pass
    if not ports:
        ports.add(22)
    return ports


def _parse_ss_peer(token: str) -> tuple[str | None, int | None]:
    token = (token or "").strip()
    if not token or token == "*:*":
        return None, None
    if token.startswith("["):
        # [ipv6]:port
        end = token.rfind("]")
        if end < 0:
            return None, None
        ip = token[1:end]
        rest = token[end + 1 :]
        if not rest.startswith(":"):
            return ip, None
        try:
            return ip, int(rest[1:])
        except ValueError:
            return ip, None
    # host:port — split from the right (IPv4 / hostname)
    if ":" not in token:
        return token, None
    host, _, port_s = token.rpartition(":")
    if not host:
        return None, None
    try:
        return host, int(port_s)
    except ValueError:
        return host, None


def _collect_ss_tcp_bytes() -> dict[tuple[str, int], tuple[int, int]]:
    """
    Map (remote_ip, remote_port) -> (bytes_sent, bytes_recv) via `ss -Hti`.
    bytes_sent/recv are from the server side of the TCP session (tunnel client link).
    """
    ss = shutil.which("ss")
    if not ss:
        return {}
    try:
        out = subprocess.check_output(
            [ss, "-Hti"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return {}

    result: dict[tuple[str, int], tuple[int, int]] = {}
    lines = out.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line or line[:1].isspace():
            continue
        parts = line.split()
        # State Recv-Q Send-Q Local Peer [Process…]
        if len(parts) < 5:
            continue
        peer_ip, peer_port = _parse_ss_peer(parts[4])
        if not peer_ip or peer_port is None:
            continue
        detail = ""
        if i < len(lines) and lines[i][:1].isspace():
            detail = lines[i]
            i += 1
        ms = SS_BYTES_SENT_RE.search(detail)
        mr = SS_BYTES_RECV_RE.search(detail)
        if not ms or not mr:
            continue
        result[(peer_ip, int(peer_port))] = (int(ms.group(1)), int(mr.group(1)))
    return result


def _process_io_chars(session_pid: int) -> tuple[int | None, int | None]:
    """Fallback: cumulative read_chars/write_chars over session process tree + priv parent."""
    try:
        root = psutil.Process(session_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None, None
    procs = [root]
    try:
        procs.extend(root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        parent = psutil.Process(root.ppid())
        pname = " ".join(parent.cmdline() or [])
        if "sshd" in pname and "[priv]" in pname:
            procs.append(parent)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    read_chars = 0
    write_chars = 0
    any_ok = False
    for proc in procs:
        try:
            io = proc.io_counters()
            # Linux: chars include socket traffic; bytes are block-device only.
            rc = getattr(io, "read_chars", None)
            wc = getattr(io, "write_chars", None)
            if rc is None or wc is None:
                continue
            read_chars += int(rc)
            write_chars += int(wc)
            any_ok = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, AttributeError):
            continue
    if not any_ok:
        return None, None
    # write_chars ≈ bytes sent by process; read_chars ≈ bytes received
    return write_chars, read_chars


def _with_io_rates(
    session_key: str,
    bytes_sent: int | None,
    bytes_recv: int | None,
) -> tuple[float | None, float | None]:
    now = time.monotonic()
    sent_rate: float | None = None
    recv_rate: float | None = None
    prev = _IO_RATE_CACHE.get(session_key)
    if (
        prev
        and bytes_sent is not None
        and bytes_recv is not None
        and bytes_sent >= prev[1]
        and bytes_recv >= prev[2]
    ):
        dt = now - prev[0]
        if dt >= 0.5:
            sent_rate = (bytes_sent - prev[1]) / dt
            recv_rate = (bytes_recv - prev[2]) / dt
    if bytes_sent is not None and bytes_recv is not None:
        _IO_RATE_CACHE[session_key] = (now, bytes_sent, bytes_recv)
    # Drop stale cache entries for closed sessions (best-effort)
    if len(_IO_RATE_CACHE) > 500:
        stale = [k for k, v in _IO_RATE_CACHE.items() if now - v[0] > 3600]
        for k in stale:
            _IO_RATE_CACHE.pop(k, None)
    return sent_rate, recv_rate


def _collect_forwards(
    session_pid: int,
    client_ip: str | None,
    listen_ports: set[int],
) -> list[dict[str, Any]]:
    """Outbound ESTABLISHED from session process tree (= active LocalForwards)."""
    try:
        root = psutil.Process(session_pid)
        pids = {session_pid, *(c.pid for c in root.children(recursive=True))}
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pids = {session_pid}

    forwards: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return []

    for c in conns:
        if c.pid not in pids:
            continue
        if c.status != psutil.CONN_ESTABLISHED:
            continue
        if not c.raddr:
            continue
        rip = getattr(c.raddr, "ip", None)
        rport = getattr(c.raddr, "port", None)
        lip = getattr(c.laddr, "ip", None) if c.laddr else None
        lport = getattr(c.laddr, "port", None) if c.laddr else None
        # Skip the inbound SSH client link (local sshd listen port, or back to client IP)
        if lport is not None and int(lport) in listen_ports:
            continue
        if client_ip and rip == client_ip:
            continue
        key = f"{rip}:{rport}"
        if key in seen:
            continue
        seen.add(key)
        forwards.append(
            {
                "host": str(rip) if rip else None,
                "port": int(rport) if rport is not None else None,
                "local_ip": str(lip) if lip else None,
                "local_port": int(lport) if lport is not None else None,
                "peer": _fmt_peer(str(rip) if rip else None, int(rport) if rport is not None else None),
            }
        )
    return forwards


def collect_active_sessions(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Live SSH tunnel sessions via psutil (TTY-less -N tunnels appear here, not in who/w).

    Matches connections on the local sshd listen port(s), not public_port — the latter
    may be an external NAT/firewall port that never appears in local sockets.
    """
    opts = _opts(options)
    public_port = int(opts["public_port"])
    listen_port = int(opts["listen_port"])
    listen_ports = _sshd_listen_ports(listen_port)
    allowed = _tunnel_usernames(options)
    prefix = opts["username_prefix"] or "tun-"

    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        return {
            "available": False,
            "error": f"No permission to read connections: {exc}",
            "active_count": 0,
            "sessions": [],
            "public_port": public_port,
            "listen_port": listen_port,
            "listen_ports": sorted(listen_ports),
        }

    ss_bytes = _collect_ss_tcp_bytes()
    now_ts = time.time()
    sessions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for c in conns:
        if c.status != psutil.CONN_ESTABLISHED:
            continue
        lport = getattr(c.laddr, "port", None) if c.laddr else None
        if lport is None or int(lport) not in listen_ports:
            continue
        if not c.pid:
            continue
        resolved = _resolve_sshd_session(int(c.pid))
        if not resolved:
            continue
        username = resolved["username"]
        if username not in allowed and not username.startswith(prefix):
            continue

        rip = getattr(c.raddr, "ip", None) if c.raddr else None
        rport = getattr(c.raddr, "port", None) if c.raddr else None
        remote_ip = str(rip) if rip else None
        remote_port = int(rport) if rport is not None else None
        session_key = f"{username}|{remote_ip}|{remote_port}"
        if session_key in seen_keys:
            continue
        seen_keys.add(session_key)

        started = resolved.get("started_at")
        started_iso = None
        duration_seconds = None
        if isinstance(started, (int, float)) and started > 0:
            started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
            duration_seconds = max(0, int(now_ts - float(started)))

        bytes_sent: int | None = None
        bytes_recv: int | None = None
        bytes_source = None
        if remote_ip and remote_port is not None:
            pair = ss_bytes.get((remote_ip, int(remote_port)))
            if pair:
                bytes_sent, bytes_recv = pair
                bytes_source = "ss"
        if bytes_sent is None:
            bytes_sent, bytes_recv = _process_io_chars(int(resolved["pid"]))
            if bytes_sent is not None:
                bytes_source = "proc_io"

        sent_rate, recv_rate = _with_io_rates(session_key, bytes_sent, bytes_recv)

        forwards = _collect_forwards(int(resolved["pid"]), remote_ip, listen_ports)
        sessions.append(
            {
                "session_key": session_key,
                "username": username,
                "pid": resolved["pid"],
                "conn_pid": int(c.pid),
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "remote": _fmt_peer(remote_ip, remote_port),
                "local_port": int(lport),
                "started_at": started_iso,
                "started_ts": started,
                "duration_seconds": duration_seconds,
                "cmdline": resolved.get("cmdline"),
                "forwards": forwards,
                "forwards_count": len(forwards),
                "bytes_sent": bytes_sent,
                "bytes_recv": bytes_recv,
                "bytes_sent_rate": sent_rate,
                "bytes_recv_rate": recv_rate,
                "bytes_source": bytes_source,
            }
        )

    # Prune rate cache for sessions that are gone
    live = {s["session_key"] for s in sessions}
    for key in list(_IO_RATE_CACHE.keys()):
        if key not in live:
            _IO_RATE_CACHE.pop(key, None)

    sessions.sort(key=lambda s: (s.get("username") or "", s.get("remote_ip") or "", s.get("pid") or 0))
    bytes_sent_total = sum(int(s["bytes_sent"]) for s in sessions if s.get("bytes_sent") is not None)
    bytes_recv_total = sum(int(s["bytes_recv"]) for s in sessions if s.get("bytes_recv") is not None)
    bytes_sent_rate_total = sum(
        float(s["bytes_sent_rate"]) for s in sessions if s.get("bytes_sent_rate") is not None
    )
    bytes_recv_rate_total = sum(
        float(s["bytes_recv_rate"]) for s in sessions if s.get("bytes_recv_rate") is not None
    )
    return {
        "available": True,
        "error": None,
        "active_count": len(sessions),
        "sessions": sessions,
        "public_port": public_port,
        "listen_port": listen_port,
        "listen_ports": sorted(listen_ports),
        "usernames": sorted({s["username"] for s in sessions}),
        "bytes_sent_total": bytes_sent_total,
        "bytes_recv_total": bytes_recv_total,
        "bytes_sent_rate_total": bytes_sent_rate_total,
        "bytes_recv_rate_total": bytes_recv_rate_total,
    }
