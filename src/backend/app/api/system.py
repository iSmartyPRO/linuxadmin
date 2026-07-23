from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.collectors.system import collect_system_metrics
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.principal import require_module, resolve_bearer
from app.services.ws_hub import metrics_hub

router = APIRouter(tags=["system"])


@router.get("/api/system/snapshot")
async def system_snapshot(_: object = Depends(require_module("overview", "read"))):
    return await asyncio.to_thread(collect_system_metrics)


@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    """Authenticate via first JSON message: {"type":"auth","token":"..."}.

    JWT or API key accepted. Token is not taken from the URL query string.
    """
    settings = get_settings()
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4401)
        return

    token = ""
    try:
        msg = json.loads(raw)
        if isinstance(msg, dict) and msg.get("type") == "auth":
            token = str(msg.get("token") or "")
    except (json.JSONDecodeError, TypeError, ValueError):
        token = ""

    if not token or AsyncSessionLocal is None:
        await websocket.close(code=4401)
        return

    try:
        async with AsyncSessionLocal() as db:
            principal = await resolve_bearer(token, db, settings)
            if not principal.can("overview", "read"):
                await websocket.close(code=4403)
                return
    except Exception:
        await websocket.close(code=4401)
        return

    try:
        await websocket.send_json({"type": "auth_ok"})
    except Exception:
        await websocket.close(code=1011)
        return

    # Socket already accepted above for the auth handshake — do not accept again.
    await metrics_hub.connect(websocket, already_accepted=True)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await metrics_hub.disconnect(websocket)
    except Exception:
        await metrics_hub.disconnect(websocket)
