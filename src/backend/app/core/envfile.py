"""Atomic helpers for reading/writing the project `.env` file."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip("'").strip('"')
    return data


def upsert_env_file(path: Path, updates: dict[str, str | int | bool]) -> None:
    """Update or append keys in `.env`, preserving comments and unknown keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    normalized = {str(k): _format_value(v) for k, v in updates.items() if v is not None}
    seen: set[str] = set()
    out: list[str] = []

    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in normalized:
            out.append(f"{key}={normalized[key]}")
            seen.add(key)
        else:
            out.append(raw)

    for key, value in normalized.items():
        if key not in seen:
            out.append(f"{key}={value}")

    text = "\n".join(out).rstrip() + "\n"
    # .env holds the DB password and JWT secret: keep its mode (0600 if new).
    mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            os.fchmod(fh.fileno(), mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _format_value(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value)
    if any(ch in s for ch in ' \t#"\'\\'):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s
