"""SSH tunnel gateway: restricted users, keys, permitopen destinations, ssh config templates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pwd
import random
import re
import shutil
import socket
import tempfile
import time
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
        "public_port": int(o.get("public_port") or 22),
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
        "  # RequestTTY no — tunnel only",
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
        "config": "\n".join(lines) + "\n",
        "forwards": forwards,
        "destinations": dests,
        "local_port_mode": mode,
        "usage": usage,
        "public_hostname": hostname,
        "public_port": opts["public_port"],
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


def _collect_forwards(session_pid: int, client_ip: str | None, public_port: int) -> list[dict[str, Any]]:
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
        # Skip the inbound SSH client link
        if client_ip and rip == client_ip and lport == public_port:
            continue
        if lport == public_port:
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
    """
    opts = _opts(options)
    public_port = int(opts["public_port"])
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
        }

    sessions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for c in conns:
        if c.status != psutil.CONN_ESTABLISHED:
            continue
        if not c.laddr or getattr(c.laddr, "port", None) != public_port:
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
        if isinstance(started, (int, float)) and started > 0:
            started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

        forwards = _collect_forwards(int(resolved["pid"]), remote_ip, public_port)
        sessions.append(
            {
                "session_key": session_key,
                "username": username,
                "pid": resolved["pid"],
                "conn_pid": int(c.pid),
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "remote": _fmt_peer(remote_ip, remote_port),
                "local_port": public_port,
                "started_at": started_iso,
                "started_ts": started,
                "cmdline": resolved.get("cmdline"),
                "forwards": forwards,
                "forwards_count": len(forwards),
            }
        )

    sessions.sort(key=lambda s: (s.get("username") or "", s.get("remote_ip") or "", s.get("pid") or 0))
    return {
        "available": True,
        "error": None,
        "active_count": len(sessions),
        "sessions": sessions,
        "public_port": public_port,
        "usernames": sorted({s["username"] for s in sessions}),
    }
