"""Jailed file manager: every path stays inside a configured mount."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import tarfile
import uuid
import zipfile
from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from typing import Any

ProgressFn = Callable[[int, int, str], None]

_ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
_BLOCKED_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/boot")

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif", ".svg"}
MARKDOWN_EXT = {".md", ".mdx", ".markdown"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
XLSX_EXT = {".xlsx"}
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
_MAX_ARCHIVE_FILES = 4000
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_ARCHIVE_SUFFIXES = (
    ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".zip", ".tar",
)


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
    elif ext in DOCX_EXT:
        preview = "docx"
    elif ext in XLSX_EXT:
        preview = "xlsx"
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


def _component_limit(directory: Path) -> int:
    """Bytes allowed in one filename on this directory's filesystem.

    Linux NAME_MAX is 255 bytes, not characters. Cyrillic UTF-8 uses two bytes
    per letter, and encrypted home directories can be tighter still.
    """
    try:
        limit = os.pathconf(directory, "PC_NAME_MAX")
    except (OSError, ValueError):
        return 255
    if not isinstance(limit, int) or limit < 16:
        return 255
    return min(limit, 255)


def _truncate_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    raw = raw[:max_bytes]
    while raw:
        try:
            return raw.decode("utf-8").rstrip(" .")
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ""


def _filename_suffix(name: str) -> tuple[str, str]:
    archive = _archive_suffix(name)
    if archive:
        return name[: -len(archive)], archive
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return name, ""
    ext = name[dot:]
    if len(ext.encode("utf-8")) > 32:
        return name, ""
    return name[:dot], ext


def _fit_filename(name: str, max_bytes: int) -> str:
    text = name.strip()
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    stem, ext = _filename_suffix(text)
    if len(ext.encode("utf-8")) >= max_bytes:
        stem, ext = text, ""
    fitted = _truncate_utf8(stem, max_bytes - len(ext.encode("utf-8")))
    if not fitted or fitted in {".", ".."}:
        fitted = "file"
        if len((fitted + ext).encode("utf-8")) > max_bytes:
            ext = ""
    return fitted + ext


def _unique_name(directory: Path, name: str, max_bytes: int | None = None) -> str:
    limit = _component_limit(directory) if max_bytes is None else max_bytes
    name = _fit_filename(name, limit)
    candidate = directory / name
    if not candidate.exists() and not candidate.is_symlink():
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for n in range(2, 100):
        marker = f" ({n})"
        room = limit - len(marker.encode("utf-8")) - len(suffix.encode("utf-8"))
        alt = f"{_truncate_utf8(stem, room) or 'file'}{marker}{suffix}"
        if not (directory / alt).exists() and not (directory / alt).is_symlink():
            return alt
    raise FileManError("Too many files with the same name")


def _atomic_write(dest: Path, data: bytes, like: os.stat_result | None = None) -> None:
    """Write via a fresh, randomly named temp file next to *dest*, then rename.

    mkstemp creates the file with O_EXCL, so a symlink planted by a local user
    is never followed (the panel runs as root). Mode and owner come from *like*
    (the file being replaced) or default to 0644.
    """
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".lnxadmin-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
            os.fchmod(fh.fileno(), stat.S_IMODE(like.st_mode) if like else 0o644)
            if like is not None:
                try:
                    os.fchown(fh.fileno(), like.st_uid, like.st_gid)
                except PermissionError:
                    pass
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    try:
        _atomic_write(path, data, like=path.stat())
    except OSError as exc:
        raise FileManError(f"Cannot save file: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, path), "size": len(data)}


def _ensure_dirs_under(root_real: Path, parent: Path, rel: str) -> None:
    """Create every missing directory in rel under parent. Existing directories are kept."""
    current = parent
    for part in _split_rel(rel):
        clean_name(part)
        candidate = current / part
        try:
            lst = candidate.lstat()
        except FileNotFoundError:
            lst = None
        if lst is None:
            try:
                parent_real = current.resolve(strict=True)
            except OSError as exc:
                raise FileManError(f"Cannot create folder: {exc}") from exc
            if not _inside(root_real, parent_real):
                raise FileManError("Path escapes the mounted folder", 403)
            try:
                candidate.mkdir()
            except FileExistsError:
                try:
                    lst = candidate.lstat()
                except OSError as exc:
                    raise FileManError(f"Cannot create folder: {exc}") from exc
            except OSError as exc:
                raise FileManError(f"Cannot create folder: {exc}") from exc
            else:
                current = candidate
                continue
        if lst is None:
            raise FileManError("Cannot create folder")
        if stat.S_ISLNK(lst.st_mode):
            try:
                target = Path(os.path.realpath(candidate))
            except OSError as exc:
                raise FileManError(f"Broken link: {exc}") from exc
            if not target.is_dir() or not _inside(root_real, target):
                raise FileManError("Symbolic link points outside the mounted folder", 403)
            current = target
            continue
        if not stat.S_ISDIR(lst.st_mode):
            raise FileManError("An item with that name already exists")
        try:
            current = candidate.resolve(strict=True)
        except OSError as exc:
            raise FileManError(f"Cannot create folder: {exc}") from exc
        if not _inside(root_real, current):
            raise FileManError("Path escapes the mounted folder", 403)


def ensure_dirs(mod: dict[str, Any], root_id: str, parent_rel: str, paths: list[str]) -> dict[str, Any]:
    """Create nested folders inside a mount. Used when a whole directory is uploaded."""
    if not isinstance(paths, list) or len(paths) > 4000:
        raise FileManError("Too many folders in one upload")
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    root_real = Path(root["path"]).resolve(strict=True)
    parent = resolve_rel(root_real, parent_rel, expect="dir")
    seen: set[str] = set()
    ordered = sorted((str(raw) for raw in paths), key=lambda item: (item.count("/"), item))
    for raw in ordered:
        if len(raw) > 4096:
            raise FileManError("Invalid folder path")
        parts = _split_rel(raw)
        if not parts:
            continue
        if len(parts) > 48:
            raise FileManError("Folder path is too deep")
        key = "/".join(parts)
        if key in seen:
            continue
        seen.add(key)
        _ensure_dirs_under(root_real, parent, key)
    return {"ok": True, "count": len(seen)}


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
    try:
        _atomic_write(dest, data)
    except OSError as exc:
        raise FileManError(f"Cannot upload file: {exc}") from exc
    return {"ok": True, "rel": _rel_of(root_real, dest), "name": name, "size": len(data)}


def _archive_suffix(name: str) -> str | None:
    lower = name.lower()
    for suffix in _ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    return None


def _archive_stem(name: str) -> str:
    suffix = _archive_suffix(name)
    stem = name[: -len(suffix)] if suffix else Path(name).stem
    stem = stem.strip()
    if not stem or stem in {".", ".."}:
        return "archive"
    return stem


def _unique_filename(directory: Path, filename: str, max_bytes: int | None = None) -> str:
    limit = _component_limit(directory) if max_bytes is None else max_bytes
    suffix = _archive_suffix(filename) or ""
    if not suffix:
        return _unique_name(directory, filename, limit)
    filename = _fit_filename(filename, limit)
    suffix = _archive_suffix(filename) or ""
    if not (directory / filename).exists() and not (directory / filename).is_symlink():
        return filename
    stem = filename[: -len(suffix)] if suffix else filename
    for n in range(2, 100):
        marker = f" ({n})"
        room = limit - len(marker.encode("utf-8")) - len(suffix.encode("utf-8"))
        alt = f"{_truncate_utf8(stem, room) or 'archive'}{marker}{suffix}"
        if not (directory / alt).exists() and not (directory / alt).is_symlink():
            return alt
    raise FileManError("Too many files with the same name")


def _node_in_root(root_real: Path, rel: str) -> Path:
    parts = _split_rel(rel)
    if not parts:
        raise FileManError("Choose a file or folder")
    parent = resolve_rel(root_real, "/".join(parts[:-1]), expect="dir")
    source = parent / parts[-1]
    try:
        lst = source.lstat()
    except FileNotFoundError as exc:
        raise FileManError("Path does not exist", 404) from exc
    if stat.S_ISLNK(lst.st_mode):
        raise FileManError("Symbolic links cannot be packed or extracted", 403)
    if not _inside(root_real, source.resolve(strict=True)):
        raise FileManError("Path escapes the mounted folder", 403)
    return source


def _iter_pack(root_real: Path, source: Path) -> tuple[list[tuple[Path, str]], list[str], int]:
    """Return (files as path/arcname, directory arcnames, total bytes). Symlinks are skipped."""
    files: list[tuple[Path, str]] = []
    dirs: list[str] = []
    total = 0
    prefix = source.name

    def add_file(path: Path, arcname: str) -> None:
        nonlocal total
        if path.is_symlink() or not path.is_file():
            return
        real = path.resolve(strict=True)
        if not _inside(root_real, real):
            raise FileManError("Path escapes the mounted folder", 403)
        size = path.stat().st_size
        if size > _MAX_ARCHIVE_BYTES or total + size > _MAX_ARCHIVE_BYTES:
            raise FileManError("Folder is too large to pack", 413)
        total += size
        if len(files) >= _MAX_ARCHIVE_FILES:
            raise FileManError("Too many files to pack")
        files.append((path, arcname))

    if source.is_file():
        add_file(source, prefix)
        return files, dirs, total
    if not source.is_dir():
        raise FileManError("Only a file or folder can be packed")

    dirs.append(f"{prefix}/")
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for dirname in dirnames:
            child = current / dirname
            if child.is_symlink():
                continue
            try:
                if not child.is_dir() or not _inside(root_real, child.resolve(strict=True)):
                    continue
            except OSError:
                continue
            kept.append(dirname)
            rel = child.relative_to(source).as_posix()
            dirs.append(f"{prefix}/{rel}/")
        dirnames[:] = kept
        for filename in filenames:
            path = current / filename
            try:
                rel = path.relative_to(source).as_posix()
            except ValueError as exc:
                raise FileManError("Path escapes the mounted folder", 403) from exc
            add_file(path, f"{prefix}/{rel}")
    return files, dirs, total


def _write_zip_member(archive: zipfile.ZipFile, path: Path, arcname: str, on_chunk: Callable[[int], None]) -> None:
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits |= 0x800
    with path.open("rb") as src, archive.open(info, "w") as dest:
        while True:
            buf = src.read(256 * 1024)
            if not buf:
                break
            dest.write(buf)
            on_chunk(len(buf))


def _write_tar_member(archive: tarfile.TarFile, path: Path, arcname: str, on_chunk: Callable[[int], None]) -> None:
    info = archive.gettarinfo(str(path), arcname=arcname)
    with path.open("rb") as src:
        archive.addfile(info, _ChunkReader(src, on_chunk))


class _ChunkReader:
    def __init__(self, raw, on_chunk: Callable[[int], None]):
        self._raw = raw
        self._on_chunk = on_chunk

    def read(self, n: int = -1) -> bytes:
        buf = self._raw.read(256 * 1024 if n is None or n < 0 else n)
        if buf:
            self._on_chunk(len(buf))
        return buf


class _ByteCounter:
    """File-like wrapper that reports how much of an archive has been read."""

    def __init__(self, raw, size: int, on_progress: ProgressFn | None, label: str):
        self._raw = raw
        self.size = max(size, 1)
        self._on_progress = on_progress
        self.label = label
        self._last_pct = -1

    def _emit(self, force: bool = False) -> None:
        if not self._on_progress:
            return
        pos = self._raw.tell()
        pct = int(pos * 100 / self.size)
        if not force and pct == self._last_pct:
            return
        self._last_pct = pct
        self._on_progress(pos, self.size, self.label)

    def read(self, n: int = -1) -> bytes:
        buf = self._raw.read(n)
        self._emit()
        return buf

    def seek(self, offset: int, whence: int = 0) -> int:
        pos = self._raw.seek(offset, whence)
        self._emit()
        return pos

    def tell(self) -> int:
        return self._raw.tell()

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def close(self) -> None:
        self._raw.close()


def pack_path(
    mod: dict[str, Any],
    root_id: str,
    rel: str,
    fmt: str,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    kind = (fmt or "zip").strip().lower()
    if kind not in {"zip", "tar.gz"}:
        raise FileManError("Choose zip or tar.gz")
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    root_real = Path(root["path"]).resolve(strict=True)
    source = _node_in_root(root_real, rel)
    parent = source.parent
    files, dirs, total_bytes = _iter_pack(root_real, source)
    suffix = ".zip" if kind == "zip" else ".tar.gz"
    filename = _unique_filename(parent, f"{source.name}{suffix}")
    dest = parent / filename
    tmp = parent / f".{filename}.lnxadmin-up"
    packed = 0

    def tick(amount: int, label: str) -> None:
        nonlocal packed
        packed += amount
        if on_progress:
            on_progress(packed, total_bytes, label)

    if on_progress:
        on_progress(0, total_bytes, source.name)
    try:
        if kind == "zip":
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for arcname in dirs:
                    archive.writestr(arcname, "")
                for path, arcname in files:
                    _write_zip_member(archive, path, arcname, lambda n, name=path.name: tick(n, name))
        else:
            with tarfile.open(tmp, "w:gz") as archive:
                for arcname in dirs:
                    info = tarfile.TarInfo(arcname)
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                for path, arcname in files:
                    _write_tar_member(archive, path, arcname, lambda n, name=path.name: tick(n, name))
        os.replace(tmp, dest)
    except FileManError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise FileManError(f"Cannot pack archive: {exc}") from exc
    if not _inside(root_real, dest.resolve(strict=True)):
        raise FileManError("Path escapes the mounted folder", 403)
    return {"ok": True, "rel": _rel_of(root_real, dest), "name": filename, "size": dest.stat().st_size}


def _zip_is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _stream_member(fd: int, reader, total: int) -> int:
    written = 0
    while True:
        buf = reader.read(1024 * 1024)
        if not buf:
            break
        written += len(buf)
        if written > _MAX_ARCHIVE_BYTES or total + written > _MAX_ARCHIVE_BYTES:
            raise FileManError("Archive is too large to extract", 413)
        os.write(fd, buf)
    return written


def _archive_parts(rel: str) -> list[str]:
    try:
        parts = _split_rel(rel)
    except FileManError as exc:
        raise FileManError("Archive contains an unsafe path") from exc
    if len(parts) > 48:
        raise FileManError("Archive contains an unsafe path")
    return parts


def _fit_archive_parts(
    parts: list[str],
    used: dict[tuple[str, ...], tuple[str, ...]],
    limit: int,
    renamed: list[int],
) -> list[str]:
    """Shorten each archive path component so it fits NAME_MAX, stably for this extract."""
    fitted: list[str] = []
    for index, part in enumerate(parts):
        key = tuple(parts[: index + 1])
        cached = used.get(key)
        if cached is not None:
            fitted = list(cached)
            continue
        text = part.strip()
        if (
            not text
            or text in {".", ".."}
            or "/" in text
            or "\\" in text
            or "\x00" in text
            or any(ord(ch) < 32 for ch in text)
        ):
            raise FileManError("Archive contains an unsafe path")
        safe = _fit_filename(text, limit)
        taken = {
            item[-1]
            for item in used.values()
            if len(item) == index + 1 and item[:-1] == tuple(fitted)
        }
        changed = safe != text
        if safe in taken:
            changed = True
            for n in range(2, 1000):
                marker = f" ({n})"
                stem, ext = _filename_suffix(safe)
                room = limit - len(marker.encode("utf-8")) - len(ext.encode("utf-8"))
                alt = f"{_truncate_utf8(stem, room) or 'file'}{marker}{ext}"
                if alt not in taken and len(alt.encode("utf-8")) <= limit:
                    safe = alt
                    break
            else:
                raise FileManError("Too many files with the same name")
        if changed:
            renamed[0] += 1
        fitted.append(safe)
        used[key] = tuple(fitted)
    return fitted


def _extract_file(root_real: Path, folder: Path, rel: str, reader, total: int, name_limit: int) -> int:
    parts = _archive_parts(rel)
    if not parts:
        raise FileManError("Archive contains an unsafe path")
    parent_rel = "/".join(parts[:-1])
    if parent_rel:
        _ensure_dirs_under(root_real, folder, parent_rel)
    parent = folder.joinpath(*parts[:-1]) if len(parts) > 1 else folder
    parent_real = parent.resolve(strict=True)
    if not _inside(root_real, parent_real):
        raise FileManError("Path escapes the mounted folder", 403)
    name = _unique_filename(parent_real, clean_name(parts[-1]), name_limit)
    target = parent_real / name
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o644)
    try:
        return _stream_member(fd, reader, total)
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def extract_path(
    mod: dict[str, Any],
    root_id: str,
    rel: str,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    root = _root_record(mod, root_id)
    _require_write(mod, root)
    root_real = Path(root["path"]).resolve(strict=True)
    source = _node_in_root(root_real, rel)
    if not source.is_file():
        raise FileManError("Choose an archive file")
    if source.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise FileManError("Archive is too large to extract", 413)
    suffix = _archive_suffix(source.name)
    if suffix is None:
        raise FileManError("This file is not a supported archive (zip, tar, tar.gz, tar.bz2, tar.xz)")
    parent = source.parent
    name_limit = _component_limit(parent)
    folder_name = _unique_filename(parent, clean_name(_archive_stem(source.name)), name_limit)
    dest = parent / folder_name
    dest.mkdir()
    files = 0
    total = 0
    skipped = 0
    renamed = [0]
    fitted_paths: dict[tuple[str, ...], tuple[str, ...]] = {}
    raw = source.open("rb")
    counter = _ByteCounter(raw, source.stat().st_size, on_progress, source.name)
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(counter) as archive:
                for info in archive.infolist():
                    if info.flag_bits & 0x1:
                        raise FileManError("Encrypted archives are not supported")
                    if _zip_is_symlink(info):
                        skipped += 1
                        continue
                    name = info.filename.replace("\\", "/")
                    member_parts = _fit_archive_parts(_archive_parts(name), fitted_paths, name_limit, renamed)
                    fitted_name = "/".join(member_parts)
                    if name.endswith("/"):
                        if fitted_name:
                            _ensure_dirs_under(root_real, dest, fitted_name)
                        continue
                    if files >= _MAX_ARCHIVE_FILES:
                        raise FileManError("Archive has too many files")
                    counter.label = member_parts[-1] if member_parts else source.name
                    counter._emit(force=True)
                    with archive.open(info, "r") as reader:
                        total += _extract_file(root_real, dest, fitted_name, reader, total, name_limit)
                    files += 1
        else:
            mode = {".tar": "r:", ".tar.gz": "r:gz", ".tgz": "r:gz", ".tar.bz2": "r:bz2", ".tbz2": "r:bz2", ".tar.xz": "r:xz", ".txz": "r:xz"}[suffix]
            with tarfile.open(fileobj=counter, mode=mode) as archive:
                for member in archive:
                    if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                        skipped += 1
                        continue
                    member_name = member.name.replace("\\", "/")
                    member_parts = _fit_archive_parts(_archive_parts(member_name), fitted_paths, name_limit, renamed)
                    fitted_name = "/".join(member_parts)
                    if member.isdir():
                        if fitted_name:
                            _ensure_dirs_under(root_real, dest, fitted_name)
                        continue
                    if member.size < 0 or member.size > _MAX_ARCHIVE_BYTES or total + member.size > _MAX_ARCHIVE_BYTES:
                        raise FileManError("Archive is too large to extract", 413)
                    if files >= _MAX_ARCHIVE_FILES:
                        raise FileManError("Archive has too many files")
                    counter.label = member_parts[-1] if member_parts else source.name
                    counter._emit(force=True)
                    reader = archive.extractfile(member)
                    if reader is None:
                        skipped += 1
                        continue
                    with reader:
                        total += _extract_file(root_real, dest, fitted_name, reader, total, name_limit)
                    files += 1
    except FileManError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except (OSError, tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise FileManError(f"Cannot extract archive: {exc}") from exc
    finally:
        try:
            raw.close()
        except OSError:
            pass
    if not _inside(root_real, dest.resolve(strict=True)):
        shutil.rmtree(dest, ignore_errors=True)
        raise FileManError("Path escapes the mounted folder", 403)
    return {
        "ok": True,
        "rel": _rel_of(root_real, dest),
        "name": folder_name,
        "files": files,
        "skipped": skipped,
        "renamed": renamed[0],
    }
