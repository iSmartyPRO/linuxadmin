from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.collectors.system import collect_system_metrics
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services.persistence import (
    cleanup_old_metrics,
    get_app_config,
    get_modules,
    get_setting,
    persist_pg_snapshots,
    persist_ssh_tunnel_history,
    persist_system_snapshot,
    persist_wireguard_history,
    DEFAULT_PG_SETTINGS,
)
from app.services.ws_hub import metrics_hub

logger = logging.getLogger("lnxadmin.worker")


class BackgroundWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="lnxadmin-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _load_runtime(self) -> tuple[float, float, dict[str, Any]]:
        env = get_settings()
        async with AsyncSessionLocal() as session:
            app_cfg = await get_app_config(session)
            modules = await get_modules(session)
        metrics_interval = float(app_cfg.get("metrics_interval_seconds") or env.metrics_interval)
        history_interval = float(app_cfg.get("history_interval_seconds") or env.history_interval)
        return metrics_interval, history_interval, modules

    async def _run(self) -> None:
        env = get_settings()
        collect_system_metrics()
        last_history = 0.0
        last_pg = 0.0
        last_ssh = 0.0
        last_wg = 0.0
        last_cleanup = 0.0
        last_cfg_refresh = 0.0
        metrics_interval = float(env.metrics_interval)
        history_interval = float(env.history_interval)
        modules: dict[str, Any] = {}
        loop = asyncio.get_event_loop()

        while not self._stop.is_set():
            started = loop.time()
            try:
                if started - last_cfg_refresh >= 5.0 or not modules:
                    metrics_interval, history_interval, modules = await self._load_runtime()
                    last_cfg_refresh = started

                overview = modules.get("overview", {})
                history = modules.get("history", {})
                want_live = overview.get("enabled", True) and overview.get("live_metrics", True)
                want_record = history.get("enabled", True) and history.get("record", True)

                metrics = None
                if want_live or want_record:
                    metrics = await asyncio.to_thread(collect_system_metrics)
                    if want_live:
                        await metrics_hub.broadcast({"type": "system", "data": metrics})

                if want_record and started - last_history >= history_interval:
                    async with AsyncSessionLocal() as session:
                        await persist_system_snapshot(session, metrics)
                    last_history = started

                pg_interval = 30.0
                async with AsyncSessionLocal() as session:
                    pg_settings = await get_setting(session, "postgres_monitor", DEFAULT_PG_SETTINGS)
                    pg_interval = float(pg_settings.get("interval_seconds") or 30)
                    if started - last_pg >= pg_interval:
                        await persist_pg_snapshots(session)
                        last_pg = started

                    ssh_mod = modules.get("ssh_tunnel", {})
                    ssh_interval = float(ssh_mod.get("history_interval_seconds") or history_interval or 15)
                    if (
                        ssh_mod.get("enabled", True)
                        and ssh_mod.get("record_history", True)
                        and started - last_ssh >= ssh_interval
                    ):
                        await persist_ssh_tunnel_history(session)
                        last_ssh = started

                    wg_mod = modules.get("wireguard", {})
                    wg_interval = float(wg_mod.get("history_interval_seconds") or 30)
                    if (
                        wg_mod.get("enabled", True)
                        and wg_mod.get("record_history", False)
                        and started - last_wg >= wg_interval
                    ):
                        await persist_wireguard_history(session)
                        last_wg = started

                    if started - last_cleanup >= 3600:
                        await cleanup_old_metrics(session)
                        last_cleanup = started
            except Exception:
                logger.exception("background worker iteration failed")

            elapsed = loop.time() - started
            wait = max(0.2, metrics_interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


worker = BackgroundWorker()
