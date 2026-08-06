"""In-app documentation for modules and API integrations."""

from __future__ import annotations

from typing import Any

from app.core.principal import Principal

DOCS: dict[str, dict[str, Any]] = {
    "overview": {
        "title": "Overview",
        "summary": "Live host metrics: CPU, memory, disks, network, processes, temperatures.",
        "body": """
## What it is
The Overview dashboard streams live system metrics over a WebSocket and shows status cards for enabled modules.

## Capabilities
- Live CPU / RAM / swap / load / network rates
- Disk usage and top processes
- Jump cards into Fail2ban, Docker, VPN modules, etc.

## Settings
Under **Settings → Modules → Overview** you can toggle live metrics, gauges, charts, disks, processes, and temperatures.

## Permissions
- **Read** — view dashboard
- **Full** — same as read (no destructive actions here)
""",
    },
    "history": {
        "title": "History",
        "summary": "Time-series charts stored in PostgreSQL, plus SSH tunnel session history.",
        "body": """
## What it is
Historical metrics recorded by the background worker into PostgreSQL for trend analysis.

## Capabilities
- CPU / memory / network history over selectable ranges
- SSH tunnel active-session charts and connection log (if SSH Tunnel module records history)

## Settings
**Settings → Project**: metrics interval, history interval, retention days.
**SSH Tunnel module**: `record_history`, `history_interval_seconds`.

## Permissions
- **Read** — view charts
- **Full** — same as read
""",
    },
    "fail2ban": {
        "title": "Fail2ban",
        "summary": "Jail status, banned IPs, logs; optional install, ban/unban and jail parameter edits.",
        "body": """
## What it is
Manage Fail2ban jails on this host: see banned addresses, ignore lists, and recent log lines.

## Capabilities
- Install Fail2ban via the host package manager (when not present)
- List jails and banned IPs
- Ban / unban / reload
- Adjust bantime, findtime, maxretry (when mutations allowed)

## Settings
Enable **Allow management** for Fail2ban in Settings before mutating. Package install also needs **Allow package install**. Host needs appropriate sudoers for `fail2ban-client`, `systemctl`, and the package manager (`apt-get` / `dnf` / `yum`).

## Permissions
- **Read** — view status and logs
- **Full** — install, ban/unban and parameter changes (also requires module `allow_mutations`)
""",
    },
    "firewall": {
        "title": "Firewall",
        "summary": "Detects ufw / firewalld / nftables / iptables and shows rules.",
        "body": """
## What it is
Firewall overview with auto-detected backend and optional rule changes.

## Capabilities
- Show active rules / zones
- Enable/disable, allow/deny ports (when mutations allowed)

## Permissions
- **Read** — view rules
- **Full** — change rules (`allow_mutations` required)
""",
    },
    "docker": {
        "title": "Docker",
        "summary": "Containers, images, and Docker disk usage.",
        "body": """
## What it is
Read-only style overview of the local Docker engine (containers, images, disk).

## Settings
Toggle collect_stats / collect_disk / collect_info under the Docker module settings.

## Permissions
- **Read / Full** — view data (no container lifecycle control in this panel yet)
""",
    },
    "network": {
        "title": "Network",
        "summary": "Listening and established sockets, interfaces; optional iface/process actions.",
        "body": """
## What it is
Socket and interface inventory for troubleshooting.

## Capabilities
- Listening / established / other connections
- Optional interface up/down and process kill when mutations + allow_kill are enabled

## Permissions
- **Read** — view
- **Full** — mutate (`allow_mutations` / `allow_kill`)
""",
    },
    "disks": {
        "title": "Disks",
        "summary": "Partitions, I/O, and safe browse under mount points.",
        "body": """
## What it is
Disk usage and a constrained file browser under real mount points (pseudo filesystems hidden by default).

## Settings
`allow_browse`, `include_pseudo`, `max_entries`, `scan_timeout_seconds`.

## Permissions
- **Read** — overview + browse (if allow_browse)
- **Full** — same (browse is not destructive writes)
""",
    },
    "users": {
        "title": "OS Users",
        "summary": "Local Linux accounts and groups (not panel login users).",
        "body": """
## What it is
Manage **operating system** users/groups on the host. Panel login accounts are under **Settings → Access**.

## Permissions
- **Read** — list accounts
- **Full** — create/modify when `allow_mutations` is on
""",
    },
    "services": {
        "title": "Services",
        "summary": "systemd units: status, start/stop/restart, logs.",
        "body": """
## What it is
systemd unit control for this host.

## Permissions
- **Read** — list + logs
- **Full** — start/stop/restart (`allow_mutations`)
""",
    },
    "postgres": {
        "title": "PostgreSQL",
        "summary": "Connections, cache hit, activity, statements, locks, replication.",
        "body": """
## What it is
Monitoring against a PostgreSQL instance (often with `pg_monitor`). Credentials live in Settings → Modules → PostgreSQL.

## Permissions
- **Read / Full** — view monitor data (no arbitrary SQL execution)
""",
    },
    "ssh_tunnel": {
        "title": "SSH Tunnel",
        "summary": "Restricted tun-* jump users, keys, permitopen, live sessions.",
        "body": """
## What it is
Provision locked-down SSH accounts for port-forwarding only.

## Permissions
- **Read** — list users/sessions
- **Full** — create/revoke users and keys (`allow_mutations`)
""",
    },
    "wireguard": {
        "title": "WireGuard",
        "summary": "VPN server, peers, route presets, client configs + QR.",
        "body": """
## What it is
Manage a WireGuard interface: server config, peers, full/split/custom routes, download `.conf` / QR.

## Permissions
- **Read** — view server/peers/configs
- **Full** — install tools, apply/stop, manage peers (`allow_mutations`)
""",
    },
    "openvpn": {
        "title": "OpenVPN",
        "summary": "VPN server, clients, route presets, .ovpn export.",
        "body": """
## What it is
OpenVPN server with local PKI, CCD routes, and client `.ovpn` profiles.

## Permissions
- **Read** — view server/clients/configs
- **Full** — install, apply/stop, manage clients (`allow_mutations`)
""",
    },
    "nginx": {
        "title": "Nginx Edge Proxy",
        "summary": "HTTP/HTTPS/TCP/UDP reverse proxy, TLS passthrough, certificates, Let's Encrypt, route templates.",
        "body": """
## What it is
Central edge proxy for publishing services: reverse proxy, TLS termination, SNI passthrough (stream + `ssl_preread`), TCP/UDP, WebSocket, HTTP/2, large header buffers, load balancing, IP ACL, certificates, and ACME (HTTP-01 / DNS-01).

Managed files: `/etc/nginx/lnxadmin/` (included via `conf.d/00-lnxadmin.conf`). State: `/var/lib/lnxadmin/nginx/`.

Full operator guide: repository file `docs/nginx-edge.md`.

## Modes
- **HTTP / HTTPS reverse** — Edge terminates TLS; backend http or https
- **TLS Passthrough** — certificate stays on backend; Edge routes by SNI
- **TCP / UDP** — stream proxy (DB, RDP, WireGuard, …)

## Capabilities
- Route CRUD + templates + validation / conflict checks
- PEM / PFX upload, CSR, Let's Encrypt issue & renew (`auto_renew`)
- Safe apply: preview → `nginx -t` → backup → reload → rollback
- Backend health probes, per-route logs, Prometheus-style `/api/nginx/metrics`
- `large_headers` for Carbonio/Zimbra-style cookie sizes

## Templates
**From template**: Nextcloud, OnlyOffice, Carbonio Web/Admin, web apps, Microsoft RDS/RDP, Portainer, Grafana, Proxmox, Home Assistant, MinIO, PostgreSQL TCP, WireGuard UDP, TLS passthrough.
Always set **domain** and **backend_host** to the real app host — never the Edge IP (proxy loop → 400/502).

## Let's Encrypt after moving NAT to Edge
- Public web certs renew on **Edge** (WAN 80/443 → this host).
- Backend behind HTTPS reverse can keep a private/self-signed cert (`verify_backend_tls: false`).
- Mail ports (SMTP/IMAP) usually need a valid cert on Carbonio itself (DNS-01 or copy Edge cert after renew).
- Old HTTP-01 on the former direct-NAT host will fail once NAT points at Edge — expected for web UI.

## Carbonio tips
- Template **Carbonio Web**: backend = Carbonio IP:443, `large_headers`, WebSocket on.
- Clear site cookies if you still see `400 Request Header Or Cookie Too Large` after fixing the backend.
- Restrict **Carbonio Admin** (`:6071`) with `allow_ips` or VPN.

## Permissions
- **Read** — dashboard, routes, certs, logs, config preview
- **Full** — install, mutate routes/certs/ACME, apply/rollback (also needs `allow_mutations`)
""",
    },
    "settings": {
        "title": "Settings",
        "summary": "Project name, intervals, modules, connection, and access control.",
        "body": """
## Sections
- **Project** — app name, retention
- **Connection** — panel DB / admin bootstrap (requires `settings_connection`)
- **Modules** — enable modules and mutation flags (`settings_modules`)
- **Access** — panel users, roles, API keys (`settings_access`)
- **Documentation** — this help system + API integration guide

## Permission levels
| Level | Meaning |
|-------|---------|
| none | Hidden / API 403 |
| read | View only |
| full | View + changes |
""",
    },
    "settings_access": {
        "title": "Access control",
        "summary": "Panel users, roles (RBAC), and API keys for integrations.",
        "body": """
## Roles
- **Super Admin** — full access; cannot be locked out as the last superadmin
- **Operator / Viewer** — built-in templates; clone or create custom roles
- Per-module levels: **none / read / full**

## API keys
Create keys under Settings → Access → API keys. Format `lnx_<prefix>_<secret>`.
Send as `Authorization: Bearer …` or `X-API-Key`. Keys inherit the user's role and may optionally narrow scopes.
See **API integration** docs for examples.
""",
    },
}


def list_module_docs(principal: Principal) -> list[dict[str, Any]]:
    out = []
    for key, meta in DOCS.items():
        module_key = key if not key.startswith("settings") else (
            "settings_access" if key == "settings_access" else "settings"
        )
        if key == "settings_access":
            allowed = principal.can("settings_access", "read") or principal.is_superadmin
        elif key == "settings":
            allowed = principal.can("settings", "read") or principal.is_superadmin
        else:
            allowed = principal.can(key, "read") or principal.is_superadmin
        if not allowed:
            continue
        out.append({"key": key, "title": meta["title"], "summary": meta["summary"]})
    return out


def get_module_doc(key: str, principal: Principal) -> dict[str, Any] | None:
    meta = DOCS.get(key)
    if not meta:
        return None
    if key == "settings_access":
        if not (principal.can("settings_access", "read") or principal.is_superadmin):
            return None
    elif key.startswith("settings"):
        if not (principal.can("settings", "read") or principal.is_superadmin):
            return None
    else:
        if not (principal.can(key, "read") or principal.is_superadmin):
            return None
    return {"key": key, **meta}


def api_integration_doc() -> dict[str, Any]:
    return {
        "key": "api_integration",
        "title": "API integration guide",
        "summary": "Authenticate with JWT or API keys and call module endpoints from external systems.",
        "body": """
## Base URL
Use your panel origin, e.g. `https://admin.example.com` (or `http://127.0.0.1:8000` via tunnel).

## Authentication

### 1) Session JWT (interactive / short-lived)
```bash
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \\
  -H 'Content-Type: application/json' \\
  -d '{"username":"operator","password":"***"}' | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/access/me"
```

### 2) API key (recommended for integrations)
Create a key in **Settings → Access → API keys**. You receive a one-time token:
`lnx_<prefix>_<secret>`

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$BASE/api/docker/overview"
# or
curl -s -H "X-API-Key: $API_KEY" "$BASE/api/docker/overview"
```

Keys inherit the owning user's role permissions. Optional per-key scopes can only **narrow** access.

## Permissions
Every module endpoint requires at least **read**. Mutations (POST/PUT/DELETE that change the host) require **full** on that module, and the module's `allow_mutations` flag in Settings must be enabled.

## Useful endpoints
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/access/me` | Current identity + permissions |
| GET | `/api/settings/modules` | Enabled modules (needs settings read) |
| GET | `/api/docker/overview` | Docker summary |
| GET | `/api/wireguard/overview` | WireGuard status |
| GET | `/api/openvpn/overview` | OpenVPN status |
| GET | `/api/security/fail2ban` | Fail2ban status |
| POST | `/api/security/fail2ban/install` | Install Fail2ban package |
| WS | `/ws/metrics` | Send `{"type":"auth","token":"<jwt>"}` first (API keys not for WS) |

## Errors
- `401` — missing/invalid token
- `403` — authenticated but missing module permission
- `429` — login/setup rate limited

## Safety
Never commit API keys. Prefer keys bound to a least-privilege role (e.g. Viewer or custom read-only). Rotate by revoking the key in Settings.
""",
    }
