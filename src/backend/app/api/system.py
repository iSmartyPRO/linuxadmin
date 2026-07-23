from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from app.collectors.system import collect_system_metrics
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.services.ws_hub import metrics_hub

router = APIRouter(tags=["system"])


@router.get("/api/system/snapshot")
async def system_snapshot(_: str = Depends(get_current_user)):
    return await asyncio.to_thread(collect_system_metrics)


@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket, token: str = Query(default="")):
    settings = get_settings()
    if not token:
        await websocket.close(code=4401)
        return
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if not payload.get("sub"):
            await websocket.close(code=4401)
            return
    except JWTError:
        await websocket.close(code=4401)
        return

    await metrics_hub.connect(websocket)
    try:
        while True:
            # Keep connection alive; client may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        await metrics_hub.disconnect(websocket)
    except Exception:
        await metrics_hub.disconnect(websocket)
