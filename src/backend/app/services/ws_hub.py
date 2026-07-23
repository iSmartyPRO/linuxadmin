from __future__ import annotations

import asyncio
import json
from typing import Any, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class MetricsHub:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.latest: dict[str, Any] | None = None

    async def connect(self, ws: WebSocket, *, already_accepted: bool = False) -> None:
        if not already_accepted and ws.client_state != WebSocketState.CONNECTED:
            await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        if self.latest:
            try:
                await ws.send_text(json.dumps(self.latest, default=str))
            except Exception:
                await self.disconnect(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        self.latest = payload
        data = json.dumps(payload, default=str)
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


metrics_hub = MetricsHub()
