from __future__ import annotations

import asyncio
import grp
import pwd
import re
import shutil
from pathlib import Path
from typing import Any

try:
    import spwd  # type: ignore
except ImportError:  # pragma: no cover
    spwd = None  # type: ignore

NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SHELL_RE = re.compile(r"^/[A-Za-z0-9_./+-]+$")


def _valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def _valid_shell(shell: str) -> bool:
    return bool(SHELL_RE.fullmatch(shell or "")) and Path(shell).is_absolute()


async def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
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


async def _run_privileged(argv: list[str]) -> tuple[int, str, str]:
    """Try as current user, then sudo -n with the same argv."""
    code, out, err = await _run(argv)
    if code == 0:
        return code, out, err
    combined = (err or out or "").lower()
    needs_priv = any(
        x in combined
        for x in ("permission denied", "operation not permitted", "must be root", "only root")
    )
    if not needs_priv and code == 0:
        return code, out, err
    sudo = shutil.which("sudo")
    if not sudo:
        return code, out, err or "Permission denied (root or sudo required)"
    # sudo -n = non-interactive
    return await _run([sudo, "-n", *argv])


def _shadow_locked(username: str) -> bool | None:
    """Return True/False if readable, None if shadow inaccessible."""
    if spwd is None:
        return None
    try:
        entry = spwd.getspnam(username)
        pw = entry.sp_pwd or ""
        return pw.startswith("!") or pw.startswith("*")
    except (PermissionError, KeyError, AttributeError, OSError):
        return None


def _read_shells() -> list[str]:
    shells: list[str] = []
    try:
        with open("/etc/shells", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith("/"):
                    shells.append(line)
    except OSError:
        pass
    if not shells:
        shells = ["/bin/bash", "/bin/sh", "/usr/sbin/nologin", "/bin/false"]
    return shells


def collect_users_overview(options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    show_system = bool(opts.get("show_system_accounts", False))
    min_uid = int(opts.get("min_uid") or 1000)

    users: list[dict[str, Any]] = []
    for p in pwd.getpwall():
        if not show_system and p.pw_uid < min_uid:
            continue
        locked = _shadow_locked(p.pw_name)
        try:
            gids = [g.gr_name for g in grp.getgrall() if p.pw_name in g.gr_mem]
            primary = grp.getgrgid(p.pw_gid).gr_name
            if primary not in gids:
                gids.insert(0, primary)
        except KeyError:
            gids = []
            primary = str(p.pw_gid)
        users.append(
            {
                "username": p.pw_name,
                "uid": p.pw_uid,
                "gid": p.pw_gid,
                "primary_group": primary,
                "gecos": p.pw_gecos,
                "home": p.pw_dir,
                "shell": p.pw_shell,
                "locked": locked,
                "groups": gids,
                "system": p.pw_uid < min_uid,
            }
        )

    users.sort(key=lambda u: (u["system"], u["uid"], u["username"]))

    groups: list[dict[str, Any]] = []
    for g in grp.getgrall():
        if not show_system and g.gr_gid < min_uid:
            continue
        groups.append(
            {
                "name": g.gr_name,
                "gid": g.gr_gid,
                "members": list(g.gr_mem),
                "members_count": len(g.gr_mem),
                "system": g.gr_gid < min_uid,
            }
        )
    groups.sort(key=lambda g: (g["system"], g["gid"], g["name"]))

    return {
        "available": True,
        "users_count": len(users),
        "groups_count": len(groups),
        "users": users,
        "groups": groups,
        "shells": _read_shells(),
        "min_uid": min_uid,
        "show_system_accounts": show_system,
        "can_read_shadow": any(u.get("locked") is not None for u in users),
    }


def collect_user_details(username: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _valid_name(username):
        return {"available": False, "error": "Invalid username"}
    overview = collect_users_overview({**(options or {}), "show_system_accounts": True})
    user = next((u for u in overview["users"] if u["username"] == username), None)
    if not user:
        # try direct lookup even if filtered
        try:
            p = pwd.getpwnam(username)
        except KeyError:
            return {"available": False, "error": f"User {username} not found"}
        locked = _shadow_locked(username)
        try:
            gids = [g.gr_name for g in grp.getgrall() if username in g.gr_mem]
            primary = grp.getgrgid(p.pw_gid).gr_name
            if primary not in gids:
                gids.insert(0, primary)
        except KeyError:
            gids = []
            primary = str(p.pw_gid)
        user = {
            "username": p.pw_name,
            "uid": p.pw_uid,
            "gid": p.pw_gid,
            "primary_group": primary,
            "gecos": p.pw_gecos,
            "home": p.pw_dir,
            "shell": p.pw_shell,
            "locked": locked,
            "groups": gids,
            "system": p.pw_uid < int((options or {}).get("min_uid") or 1000),
        }
    return {"available": True, "user": user, "shells": overview["shells"]}


def collect_group_details(name: str) -> dict[str, Any]:
    if not _valid_name(name):
        return {"available": False, "error": "Invalid group name"}
    try:
        g = grp.getgrnam(name)
    except KeyError:
        return {"available": False, "error": f"Group {name} not found"}
    # Primary members (users whose primary gid matches)
    primary_members = []
    for p in pwd.getpwall():
        if p.pw_gid == g.gr_gid:
            primary_members.append(p.pw_name)
    return {
        "available": True,
        "group": {
            "name": g.gr_name,
            "gid": g.gr_gid,
            "members": list(g.gr_mem),
            "primary_members": primary_members,
            "members_count": len(g.gr_mem),
        },
    }


def _deny_system_user(username: str, min_uid: int, allow_system: bool) -> str | None:
    try:
        p = pwd.getpwnam(username)
    except KeyError:
        return f"User {username} not found"
    if p.pw_uid == 0:
        return "Operations on root are forbidden"
    if not allow_system and p.pw_uid < min_uid:
        return f"System accounts (uid < {min_uid}) are protected by settings"
    return None


async def create_user(
    *,
    username: str,
    password: str | None = None,
    shell: str = "/bin/bash",
    home: str | None = None,
    groups: list[str] | None = None,
    create_home: bool = True,
    comment: str = "",
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid username"}
    if not _valid_shell(shell):
        return {"ok": False, "error": "Invalid shell"}
    for g in groups or []:
        if not _valid_name(g):
            return {"ok": False, "error": f"Invalid group name: {g}"}
    if home and not Path(home).is_absolute():
        return {"ok": False, "error": "home must be an absolute path"}

    binary = shutil.which("useradd") or "/usr/sbin/useradd"
    cmd = [binary]
    if create_home:
        cmd.append("-m")
    if shell:
        cmd.extend(["-s", shell])
    if home:
        cmd.extend(["-d", home])
    if comment:
        # strip unsafe
        safe_comment = re.sub(r"[^\w\s.@+-]", "", comment)[:64]
        cmd.extend(["-c", safe_comment])
    if groups:
        cmd.extend(["-G", ",".join(groups)])
    cmd.append(username)

    code, out, err = await _run_privileged(cmd)
    if code != 0:
        return {"ok": False, "error": (err or out or "useradd failed").strip()[:400]}

    if password:
        # chpasswd via stdin
        chpasswd = shutil.which("chpasswd") or "/usr/sbin/chpasswd"
        try:
            proc = await asyncio.create_subprocess_exec(
                *(["sudo", "-n", chpasswd] if shutil.which("sudo") else [chpasswd]),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            payload = f"{username}:{password}\n".encode()
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=10)
            if (proc.returncode or 0) != 0:
                return {
                    "ok": True,
                    "warning": (stderr.decode() or stdout.decode() or "password not set").strip()[
                        :300
                    ],
                    "username": username,
                }
        except Exception as exc:
            return {"ok": True, "warning": f"user created, password not set: {exc}", "username": username}

    return {"ok": True, "username": username}


async def delete_user(username: str, *, remove_home: bool, min_uid: int, allow_system: bool) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    deny = _deny_system_user(username, min_uid, allow_system)
    if deny:
        return {"ok": False, "error": deny}
    binary = shutil.which("userdel") or "/usr/sbin/userdel"
    cmd = [binary]
    if remove_home:
        cmd.append("-r")
    cmd.append(username)
    code, out, err = await _run_privileged(cmd)
    if code != 0:
        return {"ok": False, "error": (err or out or "userdel failed").strip()[:400]}
    return {"ok": True}


async def set_user_locked(username: str, locked: bool, *, min_uid: int, allow_system: bool) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    deny = _deny_system_user(username, min_uid, allow_system)
    if deny:
        return {"ok": False, "error": deny}
    binary = shutil.which("usermod") or "/usr/sbin/usermod"
    flag = "-L" if locked else "-U"
    code, out, err = await _run_privileged([binary, flag, username])
    if code != 0:
        return {"ok": False, "error": (err or out or "usermod failed").strip()[:400]}
    return {"ok": True, "locked": locked}


async def set_user_shell(username: str, shell: str, *, min_uid: int, allow_system: bool) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    if not _valid_shell(shell):
        return {"ok": False, "error": "Invalid shell"}
    deny = _deny_system_user(username, min_uid, allow_system)
    if deny:
        return {"ok": False, "error": deny}
    binary = shutil.which("usermod") or "/usr/sbin/usermod"
    code, out, err = await _run_privileged([binary, "-s", shell, username])
    if code != 0:
        return {"ok": False, "error": (err or out or "usermod failed").strip()[:400]}
    return {"ok": True, "shell": shell}


async def set_user_groups(
    username: str,
    groups: list[str],
    *,
    min_uid: int,
    allow_system: bool,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    for g in groups:
        if not _valid_name(g):
            return {"ok": False, "error": f"Invalid group: {g}"}
    deny = _deny_system_user(username, min_uid, allow_system)
    if deny:
        return {"ok": False, "error": deny}
    binary = shutil.which("usermod") or "/usr/sbin/usermod"
    code, out, err = await _run_privileged([binary, "-G", ",".join(groups), username])
    if code != 0:
        return {"ok": False, "error": (err or out or "usermod failed").strip()[:400]}
    return {"ok": True, "groups": groups}


async def set_user_password(
    username: str,
    password: str,
    *,
    min_uid: int,
    allow_system: bool,
) -> dict[str, Any]:
    if not _valid_name(username):
        return {"ok": False, "error": "Invalid name"}
    if not password:
        return {"ok": False, "error": "Empty password"}
    deny = _deny_system_user(username, min_uid, allow_system)
    if deny:
        return {"ok": False, "error": deny}
    chpasswd = shutil.which("chpasswd") or "/usr/sbin/chpasswd"
    try:
        sudo = shutil.which("sudo")
        cmd = [sudo, "-n", chpasswd] if sudo else [chpasswd]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = f"{username}:{password}\n".encode()
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=10)
        if (proc.returncode or 0) != 0:
            return {
                "ok": False,
                "error": (stderr.decode() or stdout.decode() or "chpasswd failed").strip()[:400],
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:400]}
    return {"ok": True}


async def create_group(name: str) -> dict[str, Any]:
    if not _valid_name(name):
        return {"ok": False, "error": "Invalid group name"}
    binary = shutil.which("groupadd") or "/usr/sbin/groupadd"
    code, out, err = await _run_privileged([binary, name])
    if code != 0:
        return {"ok": False, "error": (err or out or "groupadd failed").strip()[:400]}
    return {"ok": True, "name": name}


async def delete_group(name: str, *, min_gid: int, allow_system: bool) -> dict[str, Any]:
    if not _valid_name(name):
        return {"ok": False, "error": "Invalid group name"}
    try:
        g = grp.getgrnam(name)
    except KeyError:
        return {"ok": False, "error": "Group not found"}
    if g.gr_gid == 0:
        return {"ok": False, "error": "Deleting the root group is forbidden"}
    if not allow_system and g.gr_gid < min_gid:
        return {"ok": False, "error": f"System groups (gid < {min_gid}) are protected"}
    binary = shutil.which("groupdel") or "/usr/sbin/groupdel"
    code, out, err = await _run_privileged([binary, name])
    if code != 0:
        return {"ok": False, "error": (err or out or "groupdel failed").strip()[:400]}
    return {"ok": True}


async def add_user_to_group(username: str, group: str) -> dict[str, Any]:
    if not _valid_name(username) or not _valid_name(group):
        return {"ok": False, "error": "Invalid name"}
    binary = shutil.which("gpasswd") or "/usr/bin/gpasswd"
    code, out, err = await _run_privileged([binary, "-a", username, group])
    if code != 0:
        return {"ok": False, "error": (err or out or "gpasswd failed").strip()[:400]}
    return {"ok": True}


async def remove_user_from_group(username: str, group: str) -> dict[str, Any]:
    if not _valid_name(username) or not _valid_name(group):
        return {"ok": False, "error": "Invalid name"}
    binary = shutil.which("gpasswd") or "/usr/bin/gpasswd"
    code, out, err = await _run_privileged([binary, "-d", username, group])
    if code != 0:
        return {"ok": False, "error": (err or out or "gpasswd failed").strip()[:400]}
    return {"ok": True}
