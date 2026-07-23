from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import asyncpg

from app.core.config import Settings, get_settings


@dataclass
class MonitorConn:
    host: str
    port: int
    user: str
    password: str
    database: str


def resolve_monitor_conn(
    monitor_settings: dict[str, Any] | None = None,
    app_settings: Settings | None = None,
    database: str | None = None,
) -> MonitorConn:
    """Build connection params from postgres_monitor settings with .env fallback."""
    app_settings = app_settings or get_settings()
    ms = monitor_settings or {}
    host = (ms.get("host") or "").strip() or app_settings.db_host
    port = int(ms.get("port") or app_settings.db_port)
    user = (ms.get("username") or "").strip() or app_settings.db_user
    password = ms.get("password") if ms.get("password") not in (None, "") else app_settings.db_password
    db = database or (ms.get("database") or "").strip() or app_settings.db_name
    return MonitorConn(host=host, port=port, user=user, password=str(password or ""), database=db)


async def _connect(
    monitor_settings: dict[str, Any] | None = None,
    database: str | None = None,
    conn_override: MonitorConn | None = None,
) -> asyncpg.Connection:
    c = conn_override or resolve_monitor_conn(monitor_settings, database=database)
    return await asyncpg.connect(
        host=c.host,
        port=c.port,
        user=c.user,
        password=c.password,
        database=database or c.database,
        timeout=5,
    )


async def probe_capabilities(conn: asyncpg.Connection) -> dict[str, Any]:
    is_super = bool(await conn.fetchval("SELECT current_setting('is_superuser') = 'on'"))
    is_pg_monitor = bool(
        await conn.fetchval(
            """
            SELECT pg_has_role(current_user, 'pg_monitor', 'member')
               OR current_setting('is_superuser') = 'on'
            """
        )
    )
    can_read_settings = False
    shared_preload = None
    try:
        shared_preload = await conn.fetchval("SHOW shared_preload_libraries")
        can_read_settings = True
    except Exception:
        can_read_settings = False

    pg_stat_statements = bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')"
        )
    )
    statements_available_ext = bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_stat_statements')"
        )
    )

    hints: list[str] = []
    if not is_pg_monitor and not is_super:
        hints.append(
            "Grant the role with GRANT pg_monitor TO <monitor_user>; a superuser is not required."
        )
    if not can_read_settings:
        hints.append(
            "No permission to read GUC (pg_monitor / pg_read_all_settings required)."
        )
    if not pg_stat_statements:
        if statements_available_ext:
            hints.append(
                "Install the extension: shared_preload_libraries = 'pg_stat_statements', "
                "restart PostgreSQL, then CREATE EXTENSION pg_stat_statements;"
            )
        else:
            hints.append(
                "Extension pg_stat_statements is unavailable on the OS — install postgresql-contrib."
            )

    return {
        "can_connect": True,
        "is_superuser": is_super,
        "is_pg_monitor": is_pg_monitor,
        "can_read_settings": can_read_settings,
        "shared_preload_libraries": shared_preload,
        "pg_stat_statements": pg_stat_statements,
        "pg_stat_statements_files_present": statements_available_ext,
        "current_user": await conn.fetchval("SELECT current_user"),
        "hints": hints,
    }


async def test_connection(
    monitor_settings: dict[str, Any] | None = None,
    conn_override: MonitorConn | None = None,
) -> dict[str, Any]:
    c = conn_override or resolve_monitor_conn(monitor_settings)
    try:
        conn = await _connect(monitor_settings, conn_override=c)
        try:
            version = await conn.fetchval("SHOW server_version")
            caps = await probe_capabilities(conn)
            return {
                "ok": True,
                "version": version,
                "host": c.host,
                "port": c.port,
                "database": c.database,
                "username": c.user,
                "capabilities": caps,
            }
        finally:
            await conn.close()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "host": c.host,
            "port": c.port,
            "database": c.database,
            "username": c.user,
            "capabilities": {
                "can_connect": False,
                "is_superuser": False,
                "is_pg_monitor": False,
                "can_read_settings": False,
                "pg_stat_statements": False,
                "hints": [str(exc)],
            },
        }


async def check_postgres_available(
    monitor_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await test_connection(monitor_settings)
    if not result["ok"]:
        return {
            "available": False,
            "error": result.get("error"),
            "host": result["host"],
            "port": result["port"],
            "database": result["database"],
            "username": result.get("username"),
            "capabilities": result.get("capabilities"),
        }
    return {
        "available": True,
        "version": result["version"],
        "host": result["host"],
        "port": result["port"],
        "database": result["database"],
        "username": result.get("username"),
        "capabilities": result.get("capabilities"),
    }


async def collect_postgres_summary(
    monitor_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = await check_postgres_available(monitor_settings)
    if not status["available"]:
        return status

    conn = await _connect(monitor_settings)
    try:
        caps = status.get("capabilities") or await probe_capabilities(conn)
        max_conn = int(await conn.fetchval("SHOW max_connections"))
        connections = await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname IS NOT NULL"
        )
        db_stats = await conn.fetch(
            """
            SELECT datname,
                   numbackends,
                   xact_commit,
                   xact_rollback,
                   blks_hit,
                   blks_read,
                   deadlocks,
                   temp_files,
                   temp_bytes,
                   pg_database_size(datname) AS size_bytes
            FROM pg_stat_database
            WHERE datname NOT IN ('template0', 'template1')
            ORDER BY datname
            """
        )
        databases = []
        for row in db_stats:
            hit = row["blks_hit"] or 0
            read = row["blks_read"] or 0
            total = hit + read
            ratio = (hit / total * 100.0) if total > 0 else None
            databases.append(
                {
                    "name": row["datname"],
                    "backends": row["numbackends"],
                    "commits": row["xact_commit"],
                    "rollbacks": row["xact_rollback"],
                    "cache_hit_ratio": ratio,
                    "deadlocks": row["deadlocks"],
                    "temp_files": row["temp_files"],
                    "temp_bytes": row["temp_bytes"],
                    "size_bytes": row["size_bytes"],
                }
            )

        replication = [
            dict(r)
            for r in await conn.fetch(
                """
                SELECT application_name, client_addr::text, state,
                       sync_state,
                       EXTRACT(EPOCH FROM replay_lag) AS replay_lag_seconds
                FROM pg_stat_replication
                """
            )
        ]

        has_statements = bool(caps.get("pg_stat_statements"))

        return {
            **status,
            "capabilities": caps,
            "max_connections": max_conn,
            "connections": connections,
            "connection_usage_percent": round(connections / max_conn * 100, 2) if max_conn else None,
            "databases": databases,
            "replication": replication,
            "pg_stat_statements_available": has_statements,
        }
    finally:
        await conn.close()


async def collect_postgres_activity(
    monitor_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    conn = await _connect(monitor_settings)
    try:
        rows = await conn.fetch(
            """
            SELECT pid, usename, datname, client_addr::text AS client_addr,
                   state, wait_event_type, wait_event,
                   EXTRACT(EPOCH FROM (now() - query_start)) AS query_duration_seconds,
                   left(query, 500) AS query
            FROM pg_stat_activity
            WHERE pid <> pg_backend_pid()
            ORDER BY query_start NULLS LAST
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def collect_postgres_statements(
    monitor_settings: dict[str, Any] | None = None, limit: int = 30
) -> dict[str, Any]:
    conn = await _connect(monitor_settings)
    try:
        has_ext = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')"
        )
        if not has_ext:
            return {
                "available": False,
                "hint": (
                    "CREATE EXTENSION pg_stat_statements; "
                    "and shared_preload_libraries = 'pg_stat_statements' "
                    "(see docs/postgres-monitoring.md)"
                ),
                "statements": [],
            }
        rows = await conn.fetch(
            """
            SELECT queryid::text AS queryid,
                   left(query, 400) AS query,
                   calls,
                   total_exec_time,
                   mean_exec_time,
                   rows,
                   shared_blks_hit,
                   shared_blks_read
            FROM pg_stat_statements
            ORDER BY total_exec_time DESC
            LIMIT $1
            """,
            limit,
        )
        return {"available": True, "statements": [dict(r) for r in rows]}
    finally:
        await conn.close()


async def collect_postgres_tables(
    monitor_settings: dict[str, Any] | None = None,
    database: Optional[str] = None,
) -> list[dict[str, Any]]:
    conn_info = resolve_monitor_conn(monitor_settings, database=database)
    conn = await _connect(monitor_settings, database=database or conn_info.database)
    try:
        rows = await conn.fetch(
            """
            SELECT schemaname, relname AS table_name,
                   seq_scan, idx_scan, n_live_tup, n_dead_tup,
                   last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC NULLS LAST
            LIMIT 100
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def collect_postgres_locks(
    monitor_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    conn = await _connect(monitor_settings)
    try:
        rows = await conn.fetch(
            """
            SELECT l.locktype, l.mode, l.granted, l.pid,
                   a.usename, a.datname, a.state,
                   left(a.query, 300) AS query
            FROM pg_locks l
            LEFT JOIN pg_stat_activity a ON a.pid = l.pid
            WHERE NOT l.granted OR l.mode ILIKE '%Exclusive%'
            ORDER BY l.granted, l.pid
            LIMIT 200
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def list_databases(
    monitor_settings: dict[str, Any] | None = None,
) -> list[str]:
    conn = await _connect(monitor_settings)
    try:
        rows = await conn.fetch(
            """
            SELECT datname FROM pg_database
            WHERE datistemplate = false
            ORDER BY datname
            """
        )
        return [r["datname"] for r in rows]
    finally:
        await conn.close()


async def collect_pg_metric_for_db(
    database: str,
    monitor_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = await _connect(monitor_settings)
    try:
        max_conn = int(await conn.fetchval("SHOW max_connections"))
        row = await conn.fetchrow(
            """
            SELECT numbackends, xact_commit, xact_rollback, blks_hit, blks_read,
                   deadlocks, pg_database_size(datname) AS size_bytes
            FROM pg_stat_database WHERE datname = $1
            """,
            database,
        )
        if not row:
            return {"database_name": database, "missing": True}
        hit = row["blks_hit"] or 0
        read = row["blks_read"] or 0
        total = hit + read
        ratio = (hit / total * 100.0) if total > 0 else None
        return {
            "database_name": database,
            "connections": row["numbackends"],
            "max_connections": max_conn,
            "cache_hit_ratio": ratio,
            "size_bytes": row["size_bytes"],
            "commits": row["xact_commit"],
            "rollbacks": row["xact_rollback"],
            "deadlocks": row["deadlocks"],
            "payload": dict(row),
        }
    finally:
        await conn.close()
