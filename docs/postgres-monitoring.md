# PostgreSQL monitoring

## Do not use a superuser

A dedicated role with `pg_monitor` is enough for monitoring
(includes `pg_read_all_stats`, `pg_read_all_settings`, `pg_stat_scan_tables`).

Run once as superuser / cluster owner:

```sql
CREATE ROLE lnxadmin_monitor WITH LOGIN PASSWORD 'strong-password-here';
GRANT pg_monitor TO lnxadmin_monitor;

-- access to the app database and any other databases you want to monitor
GRANT CONNECT ON DATABASE lnxadmin TO lnxadmin_monitor;
-- GRANT CONNECT ON DATABASE other_db TO lnxadmin_monitor;
```

Then in Linux Admin → **Settings**, set host/port/user/password for this role
(not the superuser password, and not necessarily the same user that writes app history).

## pg_stat_statements (top queries)

On most PostgreSQL installs the extension files are already present (contrib package).
Nothing extra needs to be installed in the OS if `pg_available_extensions`
lists `pg_stat_statements`.

**Practical checklist for this server (including 1C):**  
[TODO-pg-stat-statements.md](TODO-pg-stat-statements.md) — run later during a maintenance window.

Summary:

1. In `postgresql.conf`:

```
shared_preload_libraries = 'pg_stat_statements'
```

If the parameter already lists other libraries, add with a comma.

2. **Restart** PostgreSQL (reload is not enough).  
   Restart **disconnects all sessions**, including 1C connections.

3. In a system database (e.g. `lnxadmin` or `postgres`) — no downtime required:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

After that, on the PostgreSQL page in the UI the `pg_stat_statements` capability turns green,
and the Top queries tab starts filling in.

## Capabilities in Linux Admin

`GET /api/postgres/status` returns a `capabilities` block:

| Field | Meaning |
|------|--------|
| `is_pg_monitor` | Role is in `pg_monitor` (or is superuser) |
| `can_read_settings` | Can read `shared_preload_libraries` and related settings |
| `pg_stat_statements` | Extension is installed |
| `can_connect` | Successful connection with monitor credentials |

The Test connection button calls `POST /api/postgres/test-connection`.
