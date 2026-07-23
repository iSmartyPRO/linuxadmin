"""Simple in-memory rate limiting for auth / setup endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    """Per-key sliding window + optional lockout after too many failures."""

    def __init__(
        self,
        *,
        max_attempts: int = 8,
        window_seconds: float = 300.0,
        lockout_seconds: float = 900.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lockouts: dict[str, float] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> None:
        q = self._hits[key]
        cutoff = now - self.window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        until = self._lockouts.get(key)
        if until is not None and until <= now:
            self._lockouts.pop(key, None)

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            until = self._lockouts.get(key)
            if until is not None and until > now:
                retry = int(until - now) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many attempts. Try again in {retry}s",
                    headers={"Retry-After": str(retry)},
                )
            if len(self._hits[key]) >= self.max_attempts:
                self._lockouts[key] = now + self.lockout_seconds
                retry = int(self.lockout_seconds)
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many attempts. Locked for {retry}s",
                    headers={"Retry-After": str(retry)},
                )

    def hit(self, key: str) -> None:
        """Record an attempt (failed login / setup probe)."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._hits[key].append(now)
            if len(self._hits[key]) >= self.max_attempts:
                self._lockouts[key] = now + self.lockout_seconds

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._lockouts.pop(key, None)


login_limiter = SlidingWindowLimiter(max_attempts=8, window_seconds=300.0, lockout_seconds=900.0)
setup_limiter = SlidingWindowLimiter(max_attempts=20, window_seconds=600.0, lockout_seconds=1800.0)


def client_ip(request: Request, *, trust_proxy: bool = False) -> str:
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip() or "unknown"
        real = (request.headers.get("x-real-ip") or "").strip()
        if real:
            return real
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
