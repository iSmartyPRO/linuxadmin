# Phase 1 — notes

## Metrics collection

- Live: WebSocket `/ws/metrics` every ~1.5 s
- History: `metric_snapshots` table every ~15 s
- PG history: `pg_metric_snapshots` per settings (`app_settings.postgres_monitor`)

## PostgreSQL monitoring

Key sources:

- `pg_stat_activity` — live sessions
- `pg_stat_database` — cache hit, commits, sizes
- `pg_stat_statements` — top queries (extension required)
- `pg_stat_user_tables` — seq/idx scans, dead tuples
- `pg_locks` / `pg_stat_replication`

Prefer a role with `pg_monitor` instead of a superuser.
Detailed guide: [postgres-monitoring.md](postgres-monitoring.md).  
Checklist for enabling top queries (restart / 1C): [TODO-pg-stat-statements.md](TODO-pg-stat-statements.md).
