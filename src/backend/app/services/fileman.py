"""Jailed file manager: every path stays inside a configured mount."""

from __future__ import annotations

import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
_BLOCKED_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/boot")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif", ".svg"}
MARKDOWN_EXT = {".md", ".mdx", ".markdown"}
PDF_EXT = {".pdf"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
VIDEO_EXT = {".mp4", ".webm", ".ogv", ".mov", ".mkv"}
TEXT_EXT = {
    ".txt", ".log", ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg",
    ".env", ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".scss", ".js", ".jsx",
    ".mjs", ".cjs", ".ts", ".tsx", ".py", ".sh", ".bash", ".zsh", ".sql", ".go", ".rs",
    ".rb", ".php", ".vue", ".rst", ".service", ".list", ".gitignore", ".dockerignore",
    ".editorconfig", ".properties", ".gradle", ".lock",
}
TEXT_NAMES = {
    "dockerfile", "makefile", "license", "readme", "changelog", "authors", "copying",
    "gemfile", "rakefile", "procfile", "nginx.conf",
}

_HARD_TEXT_CAP = 8 * 1024 * 1024
_HARD_UPLOAD_CAP = 200 * 1024 * 1024
_MAX_LIST = 4000


class FileManError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def mount_block_reason(path: Path) -> str | None:
    text = str(path)
    if path == Path("/"):
        return "The filesystem root cannot be mounted"
    for prefix in _BLOCKED_PREFIXES:
        if text == prefix or text.startswith(prefix + "/"):
            return "This path cannot be mounted"
    return None


def validate_root_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw.startswith("/") or "\x00" in raw:
        raise FileManError("Path must be an absolute directory")
    try:
        real = Path(raw).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileManError(f"Directory does not exist: {raw}") from exc
    except OSError as exc:
        raise FileManError(f"Cannot open path: {exc}") from exc
    if not real.is_dir():
        raise FileManError("Path is not a directory")
    reason = mount_block_reason(real)
    if reason:
        raise FileManError("Mounting the filesystem root is not allowed" if real == Path("/") else reason)
    return str(real)


def browse_directories(path: str, *, show_hidden: bool = False) -> dict[str, Any]:
    """List child directories anywhere on the host. Used only to pick a mount in settings."""
    raw = (path or "/").strip() or "/"
    if "\x00" in raw or not raw.startswith("/"):
        raise FileManError("Invalid path")
    try:
        real = Path(raw).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileManError("Directory does not exist", 404) from exc
    except OSError as exc:
        raise FileManError(f"Cannot open path: {exc}") from exc
    if not real.is_dir():
        raise FileManError("Path is not a directory")

    shown = "/" if real == Path("/") else str(real)
    parent = None if real == Path("/") else ("/" if real.parent == Path("/") else str(real.parent))
    reason = mount_block_reason(real)
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(real) as it:
            for entry in it:
                name = entry.name
                if name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
                    continue
                if name.startswith(".") and not show_hidden:
                    continue
                try:
                    is_link = entry.is_symlink()
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                    child = Path(os.path.realpath(entry.path))
                except OSError:
                    continue
                if not child.is_dir():
                    continue
                child_reason = mount_block_reason(child)
                entries.append({
                    "name": name,
                    "path": "/" if child == Path("/") else str(child),
                    "symlink": is_link,
                    "blocked": child_reason is not None,
                    "reason": child_reason,
                })
                if len(entries) >= 2000:
                    truncated = True
                    break
    except PermissionError as exc:
        raise FileManError("Permission denied", 403) from exc
    except OSError as exc:
        raise FileManError(f"Cannot list folder: {exc}") from exc
    entries.sort(key=lambda row: row["name"].casefold())
    return {
        "path": shown,
        "parent": parent,
        "selectable": reason is None,
        "reason": reason,
        "truncated": truncated,
        "entries": entries,
    }


def normalize_roots(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FileManError("Mounted folders must be a list")
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise FileManError("Each mounted folder must have a name and a path")
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if not name or not path:
            raise FileManError("Each mounted folder needs a name and an absolute path")
        if len(name) > 48:
            raise FileManError("Folder name must be 48 characters or fewer")
        if any(ord(ch) < 32 for ch in name):
            raise FileManError("Folder name contains invalid characters")
        resolved = validate_root_path(path)
        if resolved in seen_paths:
            raise FileManError(f"Duplicate folder: {resolved}")
        rid = str(item.get("id") or "").strip().lower()
        if not _ID_RE.fullmatch(rid):
            rid = uuid.uuid4().hex[:12]
        while rid in seen_ids:
            rid = uuid.uuid4().hex[:12]
        seen_ids.add(rid)
        seen_paths.add(resolved)
        out.append({
            "id": rid,
            "name": name,
            "path": resolved,
            "read_only": bool(item.get("read_only")),
        })
    if len(out) > 24:
        raise FileManError("At most 24 folders can be mounted")
    return out


def public_roots(mod: dict[str, Any]) -> list[dict[str, Any]]:
    raw = mod.get("roots") or []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or "")
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if not rid or not name or not path:
            continue
        exists = False
        writable = False
        try:
            real = Path(path).resolve(strict=True)
            exists = real.is_dir()
            writable = exists and os.access(real, os.W_OK) and not bool(item.get("read_only"))
            path = str(real) if exists else path
        except OSError:
            exists = False
        out.append({
            "id": rid,
            "name": name,
            "path": path,
            "read_only": bool(item.get("read_only")),
            "exists": exists,
            "writable": writable and bool(mod.get("allow_mutations")),
        })
    return out


def _limits(mod: dict[str, Any]) -> tuple[int, int]:
    try:
        preview = int(mod.get("max_preview_mb") or 2) * 1024 * 1024
    except (TypeError, ValueError):
        preview = 2 * 1024 * 1024
    try:
        upload = int(mod.get("max_upload_mb") or 50) * 1024 * 1024
    except (TypeError, ValueError):
        upload = 50 * 1024 * 1024
    preview = max(64 * 1024, min(preview, _HARD_TEXT_CAP))
    upload = max(1024 * 1024, min(upload, _HARD_UPLOAD_CAP))
    return preview, upload


def _root_record(mod: dict[str, Any], root_id: str) -> dict[str, Any]:
    rid = (root_id or "").strip()
    for item in public_roots(mod):
        if item["id"] == rid:
            if not item["exists"]:
                raise FileManError("Mounted folder is missing on disk", 404)
            return item
    raise FileManError("Unknown mounted folder", 404)


def clean_name(name: str) -> str:
    text = (name or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise FileManError("Invalid name")
    if len(text) > 255 or any(ord(ch) < 32 for ch in text):
        raise FileManError("Invalid name")
    return text


def _split_rel(rel: str) -> list[str]:
    raw = (rel or "").replace("\\", "/").strip()
    if "\x00" in raw or raw.startswith("/"):
        raise FileManError("Invalid path")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." or "/" in part or "\\" in part:
            raise FileManError("Invalid path")
        parts.append(part)
    return parts


def _rel_of(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise FileManError("Path escapes the mounted folder", 403) from exc
    # Root itself is "" so clients can key the folder tree consistently.
    if rel in {".", "./"}:
        return ""
    if rel.startswith("./"):
        return rel[2:]
    return rel


def resolve_rel(root_real: Path, rel: str, *, must_exist: bool = True, expect: str | None = None) -> Path:
    """Resolve a relative path and refuse anything outside the mount, including via symlinks."""
    current = root_real
    parts = _split_rel(rel)
    if not parts:
        if expect == "file":
            raise FileManError("Path is not a file")
        return root_real
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        candidate = current / part
        try:
            lst = candidate.lstat()
        except FileNotFoundError:
            if must_exist or not last:
                raise FileManError("Path does not exist", 404)
            if not _inside(root_real, current):
                raise FileManError("Path escapes the mounted folder", 403)
            return candidate
        except OSError as exc:
            raise FileManError(f"Cannot read path: {exc}") from exc
        if stat.S_ISLNK(lst.st_mode):
            try:
                target = Path(os.path.realpath(candidate))
            except OSError as exc:
                raise FileManError(f"Broken link: {exc}") from exc
            if not target.exists():
                raise FileManError("Broken symbolic link", 404)
            if not _inside(root_real, target):
                raise FileManError("Symbolic link points outside the mounted folder", 403)
            current_target = target
            if last and expect == "dir" and not current_target.is_dir():
                raise FileManError("Path is not a folder")
            if last and expect == "file" and not current_target.is_file():
                raise FileManError("Path is not a file")
            if not last and not current_target.is_dir():
                raise FileManError("Path is not a folder")
            current = current_target if (not last or expect != "file") else current_target
            if last:
                return current_target
            continue
        if stat.S_ISDIR(lst.st_mode):
            if last and expect == "file":
                raise FileManError("Path is not a file")
            try:
                current = candidate.resolve(strict=True)
            except OSError as exc:
                raise FileManError(f"Cannot read path: {exc}") from exc
            if not _inside(root_real, current):
                raise FileManError("Path escapes the mounted folder", 403)
            continue
        if not last:
            raise FileManError("Path is not a folder")
        if expect == "dir":
            raise FileManError("Path is not a folder")
        if not stat.S_ISREG(lst.st_mode):
            raise FileManError("Only regular files can be opened")
        if not _inside(root_real, candidate):
            raise FileManError("Path escapes the mounted folder", 403)
        return candidate
    return current


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


def classify(name: str) -> dict[str, Any]:
    ext = _ext(name)
    base = name.lower()
    if ext in IMAGE_EXT:
        preview = "image"
    elif ext in PDF_EXT:
        preview = "pdf"
    elif ext in MARKDOWN_EXT:
        preview = "markdown"
    elif ext in AUDIO_EXT:
        preview = "audio"
    elif ext in VIDEO_EXT:
        preview = "video"
    elif ext in TEXT_EXT or base in TEXT_NAMES:
        preview = "text"
    else:
        preview = "none"
    editable = preview in {"markdown", "text"} or ext == ".svg"
    return {"ext": ext.lstrip("."), "preview": preview, "editable": editable}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _entry(root_real: Path, dir_rel: str, entry: os.DirEntry[str]) -> dict[str, Any] | None:
    name = entry.name
    if name in {".", ".."} or "/" in name or "\x00" in name:
        return None
    rel = f"{dir_rel}/{name}" if dir_rel else name
    try:
        lst = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    is_link = stat.S_ISLNK(lst.st_mode)
    kind = "symlink" if is_link else "dir" if stat.S_ISDIR(lst.st_mode) else "file" if stat.S_ISREG(lst.st_mode) else "other"
    escaped = False
    broken = False
    link_rel = None
    link_dir = False
    size = lst.st_size if kind == "file" else None
    if is_link:
        try:
            target = Path(os.path.realpath(entry.path))
            if not target.exists():
                broken = True
            elif not _inside(root_real, target):
                escaped = True
            else:
                link_rel = _rel_of(root_real, target)
                link_dir = target.is_dir()
                if target.is_file():
                    size = target.stat().st_size
                    kind = "symlink"
        except OSError:
            broken = True
    meta = classify(name)
    return {
        "name": name,
        "rel": rel,
        "kind": kind,
        "hidden": name.startswith("."),
        "size": size,
        "mtime": _iso(lst.st_mtime),
        "mtime_ts": lst.st_mtime,
        "symlink": is_link,
        "escaped": escaped,
        "broken": broken,
        "link_rel": link_rel,
        "link_dir": link_dir,
        **meta,
    }


def list_dir(mod: dict[str, Any], root_id: str, rel: str, *, show_hidden: bool | None = None) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    root_real = Path(root["path"]).resolve(strict=True)
    directory = resolve_rel(root_real, rel, expect="dir")
    dir_rel = _rel_of(root_real, directory)
    hidden = bool(mod.get("show_hidden")) if show_hidden is None else show_hidden
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(directory) as it:
            for item in it:
                if len(entries) >= _MAX_LIST:
                    truncated = True
                    break
                row = _entry(root_real, dir_rel, item)
                if row is None:
                    continue
                if row["hidden"] and not hidden:
                    continue
                entries.append(row)
    except PermissionError as exc:
        raise FileManError("Permission denied", 403) from exc
    except OSError as exc:
        raise FileManError(f"Cannot list folder: {exc}") from exc
    entries.sort(key=lambda row: (0 if row["kind"] == "dir" or row.get("link_dir") else 1, row["name"].casefold()))
    parent = str(Path(dir_rel).parent.as_posix()) if dir_rel else None
    if parent == ".":
        parent = ""
    return {
        "root": {"id": root["id"], "name": root["name"], "path": root["path"], "read_only": root["read_only"], "writable": root["writable"]},
        "rel": dir_rel,
        "parent": parent,
        "truncated": truncated,
        "entries": entries,
    }


def _file_path(mod: dict[str, Any], root_id: str, rel: str) -> tuple[dict[str, Any], Path, Path]:
    root = _root_record(mod, root_id)
    root_real = Path(root["path"]).resolve(strict=True)
    path = resolve_rel(root_real, rel, expect="file")
    if not path.is_file():
        raise FileManError("Path is not a file", 404)
    if not _inside(root_real, path.resolve()):
        raise FileManError("Path escapes the mounted folder", 403)
    return root, root_real, path


def read_text(mod: dict[str, Any], root_id: str, rel: str) -> dict[str, Any]:
    _root, _root_real, path = _file_path(mod, root_id, rel)
    preview_cap, _upload = _limits(mod)
    size = path.stat().st_size
    if size > preview_cap:
        raise FileManError(f"File is too large to preview ({size} bytes)", 413)
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise FileManError("This file is binary and cannot be opened as text", 415)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileManError("File is not valid UTF-8 text", 415) from exc
    meta = classify(path.name)
    return {"rel": rel, "name": path.name, "size": size, "text": text, **meta}


def read_raw_path(mod: dict[str, Any], root_id: str, rel: str) -> Path:
    _root, _root_real, path = _file_path(mod, root_id, rel)
    _preview, upload_cap = _limits(mod)
    # Preview/download cap follows the upload ceiling so PDFs and images still open.
    if path.stat().st_size > max(upload_cap, 40 * 1024 * 1024):
        raise FileManError("File is too large to preview", 413)
    return path


def _require_write(mod: dict[str, Any], root: dict[str, Any]) -> None:
    if not mod.get("allow_mutations"):
        raise FileManError("File changes are disabled in module settings", 403)
    if root.get("read_only"):
        raise FileManError("This folder is mounted read-only", 403)
    if not os.access(root["path"], os.W_OK):
        raise FileManError("The server user cannot write to this folder", 403)


def _unique_name(directory: Path, name: str) -> str:
    candidate = directory / name
    if not candidate.exists():
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for n in range(2, 100):
        alt = f"{stem} ({n}){suffix}"
        if not (directory / alt).exists():
            return alt
    raise FileManError("Too many files with the same name")


def write_text(mod: dict[str, Any], root_id: str, rel: str, content: str) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    preview_cap, _upload = _limits(mod)
    data = content.encode("utf-8")
    if len(data) > preview_cap:
        raise FileManError("Content is larger than the preview limit", 413)
    root_real = Path(root["path"]).resolve(strict=True)
    path = resolve_rel(root_real, rel, must_exist=True, expect="file")
    if not path.is_file():
        raise FileManError("Path is not a file", 404)
    tmp = path.with_name(path.name + ".lnxadmin-tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise FileManError(f"Cannot save file: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, path), "size": len(data)}


def make_dir(mod: dict[str, Any], root_id: str, parent_rel: str, name: str) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    root_real = Path(root["path"]).resolve(strict=True)
    parent = resolve_rel(root_real, parent_rel, expect="dir")
    folder = clean_name(name)
    dest = parent / folder
    if dest.exists() or dest.is_symlink():
        raise FileManError("An item with that name already exists")
    try:
        dest.mkdir()
    except OSError as exc:
        raise FileManError(f"Cannot create folder: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, dest)}


def make_file(mod: dict[str, Any], root_id: str, parent_rel: str, name: str) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    root_real = Path(root["path"]).resolve(strict=True)
    parent = resolve_rel(root_real, parent_rel, expect="dir")
    filename = clean_name(name)
    dest = parent / filename
    if dest.exists() or dest.is_symlink():
        raise FileManError("An item with that name already exists")
    try:
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
    except OSError as exc:
        raise FileManError(f"Cannot create file: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, dest)}


def _unlink_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def delete_path(mod: dict[str, Any], root_id: str, rel: str) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    if not _split_rel(rel):
        raise FileManError("The mounted folder itself cannot be deleted", 403)
    root_real = Path(root["path"]).resolve(strict=True)
    # Resolve through safe parents but delete the final node, not an outside symlink target.
    parts = _split_rel(rel)
    parent = resolve_rel(root_real, "/".join(parts[:-1]), expect="dir")
    target = parent / parts[-1]
    try:
        lst = target.lstat()
    except FileNotFoundError as exc:
        raise FileManError("Path does not exist", 404) from exc
    if stat.S_ISLNK(lst.st_mode):
        target.unlink()
        return {"ok": True}
    if not _inside(root_real, target.resolve(strict=True)):
        raise FileManError("Path escapes the mounted folder", 403)
    try:
        _unlink_tree(target)
    except OSError as exc:
        raise FileManError(f"Cannot delete: {exc}") from exc
    return {"ok": True}


def move_path(mod: dict[str, Any], root_id: str, rel: str, dest_rel: str, new_name: str | None = None) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    if not _split_rel(rel):
        raise FileManError("The mounted folder itself cannot be moved", 403)
    root_real = Path(root["path"]).resolve(strict=True)
    parts = _split_rel(rel)
    parent = resolve_rel(root_real, "/".join(parts[:-1]), expect="dir")
    source = parent / parts[-1]
    try:
        source.lstat()
    except FileNotFoundError as exc:
        raise FileManError("Path does not exist", 404) from exc
    if source.is_symlink():
        source_real = source
    else:
        source_real = source.resolve(strict=True)
        if not _inside(root_real, source_real):
            raise FileManError("Path escapes the mounted folder", 403)
    dest_dir = resolve_rel(root_real, dest_rel, expect="dir")
    if source.is_dir() and not source.is_symlink():
        if dest_dir == source_real or _inside(source_real, dest_dir):
            raise FileManError("Cannot move a folder into itself")
    name = clean_name(new_name) if new_name else parts[-1]
    destination = dest_dir / name
    if destination.exists() or destination.is_symlink():
        raise FileManError("An item with that name already exists")
    if not _inside(root_real, dest_dir):
        raise FileManError("Path escapes the mounted folder", 403)
    try:
        shutil.move(str(source), str(destination))
    except OSError as exc:
        raise FileManError(f"Cannot move: {exc}") from exc
    final = destination.resolve(strict=False)
    if final.exists() and not destination.is_symlink() and not _inside(root_real, final):
        raise FileManError("Move escaped the mounted folder", 403)
    return {"ok": True, "rel": _rel_of(root_real, destination if destination.exists() or destination.is_symlink() else final)}


def save_upload(mod: dict[str, Any], root_id: str, parent_rel: str, filename: str, data: bytes) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    _preview, upload_cap = _limits(mod)
    if len(data) > upload_cap:
        raise FileManError("File is larger than the upload limit", 413)
    root_real = Path(root["path"]).resolve(strict=True)
    parent = resolve_rel(root_real, parent_rel, expect="dir")
    safe = clean_name(Path(filename).name)
    name = _unique_name(parent, safe)
    dest = parent / name
    tmp = parent / f".{name}.lnxadmin-up"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise FileManError(f"Cannot upload file: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, dest), "name": name, "size": len(data)}
