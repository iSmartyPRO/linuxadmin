#!/usr/bin/env python3
"""Validate bootstrap settings before production start."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    get_settings.cache_clear()
    cfg = get_settings()
    print(f"env={cfg.app_env} bind={cfg.bind_host}:{cfg.bind_port} docs_disabled={cfg.docs_disabled}")
    warnings = cfg.security_warnings()
    errors = cfg.security_errors()
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print("Security check FAILED")
        return 1
    if warnings:
        print("Security check OK (with warnings)")
    else:
        print("Security check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
