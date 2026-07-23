# TODO: enable pg_stat_statements (do later)

Checklist for this server. Linux Admin monitoring already works
(`gesadmin` → `postgres` connection), but **top queries are unavailable** until
this document is completed.

Status at time of writing:

| Item | Current |
|-------|--------|
| PostgreSQL 18.4 | OK |
| Extension files on OS | OK (`pg_available_extensions`) |
| `shared_preload_libraries` | empty |
| `CREATE EXTENSION pg_stat_statements` | not done |
| 1C downtime on restart | **will occur** |

---

## Important notes about 1C

`shared_preload_libraries` can only be changed via a **PostgreSQL restart**.

- **Restart** = all sessions are dropped (1C, clients, Linux Admin to this DB).
- `pg_reload_conf()` / `systemctl reload` is **not enough** — the library will not load.
- `CREATE EXTENSION` after a successful restart does **not** drop connections.

Plan a short maintenance window and notify 1C users.

---

## Step 0 — preparation

1. Agree on a downtime window (usually 1–5 minutes).
2. Locate the PostgreSQL config, for example:

```bash
# path to the main conf
psql -U postgres -c "SHOW config_file;"
# or for a 1C build often something like:
# /etc/postgresql/.../postgresql.conf
# /var/lib/pgpro/... 
```

3. Identify the service unit:

```bash
systemctl list-units --type=service | grep -iE 'postgres|pgpro|1c'
```

Record the unit name (below, provisionally `postgresql`).

---

## Step 1 — edit postgresql.conf (before restart)

Open `config_file` and set:

```
shared_preload_libraries = 'pg_stat_statements'
```

If the parameter already lists other libraries — **add** with a comma, do not overwrite:

```
shared_preload_libraries = 'other_lib,pg_stat_statements'
```

Optional (sensible defaults):

```
pg_stat_statements.max = 10000
pg_stat_statements.track = all
```

Save the file. Do **not** restart yet if the maintenance window has not started.

Sanity check after editing (the running instance will not reflect the change until restart):

```bash
grep -n shared_preload_libraries /path/to/postgresql.conf
```

---

## Step 2 — restart during the maintenance window

```bash
# example — substitute your unit
systemctl stop <postgresql-unit>
# wait for stop
systemctl start <postgresql-unit>
systemctl status <postgresql-unit>
```

Or in one command:

```bash
systemctl restart <postgresql-unit>
```

Verify the library is loaded:

```sql
SHOW shared_preload_libraries;
-- expected: contains pg_stat_statements
```

If empty — restart did not pick up the conf (wrong file / wrong instance / typo).

---

## Step 3 — CREATE EXTENSION (no downtime)

As a superuser (e.g. `gesadmin` / `postgres`) in a system database
(`postgres` or `lnxadmin`):

```sql
\c postgres
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- verify
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_stat_statements';
SELECT count(*) FROM pg_stat_statements;
```

The extension is installed **once per cluster** (installing in one database is enough to read
cluster-wide stats via `pg_stat_statements` for a role with the right privileges).

---

## Step 4 — verify in Linux Admin

1. Open **PostgreSQL** or **Settings** → Test connection.
2. Capability `pg_stat_statements` = **yes**.
3. The **Top queries** tab should start filling once there is load.

API:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/postgres/status | jq .capabilities
```

---

## Step 5 — (recommended) dedicated monitoring role

Settings may currently use a superuser (`gesadmin`) — convenient for testing,
but for production prefer a dedicated role (superuser is not required for monitoring):

```sql
CREATE ROLE lnxadmin_monitor WITH LOGIN PASSWORD 'strong-password-here';
GRANT pg_monitor TO lnxadmin_monitor;
GRANT CONNECT ON DATABASE postgres TO lnxadmin_monitor;
GRANT CONNECT ON DATABASE lnxadmin TO lnxadmin_monitor;
-- if needed:
-- GRANT CONNECT ON DATABASE "1cpg-erp" TO lnxadmin_monitor;
```

Then in Linux Admin → **Settings**, set this role instead of the superuser.

Details: [postgres-monitoring.md](postgres-monitoring.md).

---

## Rollback (if something goes wrong)

1. Remove `pg_stat_statements` from `shared_preload_libraries` (or restore the previous value).
2. **Restart** PostgreSQL again (1C downtime again).
3. Optionally: `DROP EXTENSION IF EXISTS pg_stat_statements;`

---

## Done checklist

- [ ] Downtime window agreed with 1C users
- [ ] `shared_preload_libraries` edited in the correct `postgresql.conf`
- [ ] Restart done; `SHOW shared_preload_libraries` contains `pg_stat_statements`
- [ ] `CREATE EXTENSION pg_stat_statements`
- [ ] Linux Admin capability green; Top queries working
- [ ] (optional) credentials switched to `lnxadmin_monitor`
