# Linux Admin

Web-based administration panel for a Linux host: live system metrics, historical charts in PostgreSQL, Fail2ban, firewall, Docker, network, disks, users, systemd services, PostgreSQL monitoring, SSH tunnel jump-host, WireGuard/OpenVPN, and an Nginx Edge reverse-proxy module (TLS, Let's Encrypt, stream/SNI).

---

## Features

| Area | What you get |
|------|----------------|
| **Overview** | Live CPU / RAM / swap / disk / network, load average, processes, temperatures, OS info |
| **History** | Time-range charts from PostgreSQL; SSH tunnel activity, traffic rates, and connection log |
| **Fail2ban** | Jail status, banned IPs, logs; optional ban/unban and jail parameter updates. Ignore IP lists are written to `jail.d` and survive reload |
| **Firewall** | Auto-detect ufw / firewalld / nftables / iptables |
| **Docker** | Containers with live CPU, memory, network/block I/O, PIDs, and disk usage |
| **Network** | Listening / established sockets, interfaces; optional iface up/down & process kill |
| **Disks** | Partitions, I/O, safe browse under mount points |
| **File Manager** | Mount named folders: tree + explorer, preview PDF / images / Markdown, edit text, upload, rename, move, delete |
| **Users / Services** | Local accounts & systemd units (mutations optional) |
| **PostgreSQL** | Connections, cache hit, activity, statements, tables, locks, replication |
| **SSH Tunnel** | Jump-host users (`nologin`), keys / BYOK, `permitopen` destinations, live sessions (duration + TCP traffic), history, client ZIP pack |
| **WireGuard** | VPN server, peers, full/split/custom routes, client `.conf` download + QR codes |
| **OpenVPN** | VPN server, clients, full/split/custom routes, `.ovpn` download (QR when small) |
| **Nginx Edge** | Reverse proxy (HTTP/HTTPS/TCP/UDP), static directories, TLS termination & SNI passthrough, cert upload (files or PEM text), Let's Encrypt, route templates (Carbonio, Nextcloud, static site, …), safe apply + rollback |
| **Access** | Panel users, RBAC roles (none/read/full per module), API keys for integrations |
| **Docs** | In-app documentation on every module + API integration guide |

Destructive actions are **off by default** (`allow_mutations` per module in Settings) and also require role permission **full**.

---

## Requirements

- Linux host (tested on modern distributions)
- Python **3.12+**
- Node.js **20+** (build time)
- PostgreSQL **14+** (database `lnxadmin`)

---

## Quick start (production-style)

One process serves the API **and** the built UI (default bind: `127.0.0.1:8000`).

### Option A — Setup Wizard (recommended on a new host)

```bash
git clone https://github.com/iSmartyPRO/linuxadmin.git
cd linuxadmin
make env
# Leave LNXADMIN_SETUP_COMPLETE=false (default in .env.example)
make install build
LNXADMIN_ENV=production make run   # starts even before DB is configured
```

Open **http://127.0.0.1:8000/setup**, enter PostgreSQL + admin account. JWT is generated automatically. Modules and fine-tuning are configured later under **Settings**.

### Option B — Pre-filled `.env`

```bash
make env && $EDITOR .env   # set DB, JWT (openssl rand -hex 32), admin password
# LNXADMIN_SETUP_COMPLETE=true
# LNXADMIN_ENV=production
make install build migrate
make run
make status
```

Open **http://127.0.0.1:8000** and sign in.

Useful targets:

```text
make help              # list all targets
make check             # security validation of .env + health
make logs              # tail .run/logs/app.log
make stop / restart
make systemd-install   # install/enable systemd unit (root)
```

After first start you can always change the panel database, admin password, and CORS in **Settings → Connection**, and enable modules / fine-tune them under **Settings → Modules** (card grid → detail page; PostgreSQL connection is inside the PostgreSQL card).

Settings is a set of pages, not tabs:

| Path | Section |
|------|---------|
| `/settings/project` | Project name and appearance |
| `/settings/connection` | Database, admin password, CORS |
| `/settings/modules` | Module cards |
| `/settings/module/<key>` | One module, for example `/settings/module/fail2ban` |
| `/settings/access` | Users, roles, API keys |

### Development (API + Vite)

```bash
make install
make dev-backend       # terminal 1 — API with reload on :8000
make dev-frontend      # terminal 2 — Vite on :5173 (proxies /api and /ws)
```

UI: http://127.0.0.1:5173

---

## Configuration

**Single bootstrap file:** `.env` (never commit it). Template: `.env.example`.

| Variable | Purpose |
|----------|---------|
| `LNXADMIN_ENV` | `development` or `production` (production refuses weak secrets) |
| `LNXADMIN_BIND_HOST` / `PORT` | Listen address (prefer `127.0.0.1` behind a reverse proxy) |
| `LNXADMIN_DB_*` | PostgreSQL connection |
| `LNXADMIN_JWT_SECRET` | Signing key — use `openssl rand -hex 32` (≥ 32 chars) |
| `LNXADMIN_ADMIN_*` | Initial admin account (created on first start) |
| `LNXADMIN_CORS_ORIGINS` | Allowed browser origins (comma-separated) |
| `LNXADMIN_*_INTERVAL` / `RETENTION_DAYS` | Defaults until overridden in the UI |

Module toggles, mutation flags, and fine-grained options live in PostgreSQL (`app_settings`) and are edited under **Settings → Modules** in the UI (toggle on the card; open the card for detail options).

---

## Deploy to other hosts

**Source:** [github.com/iSmartyPRO/linuxadmin](https://github.com/iSmartyPRO/linuxadmin)

```bash
git clone https://github.com/iSmartyPRO/linuxadmin.git /opt/lnxadmin
cd /opt/lnxadmin
make env && $EDITOR .env   # unique secrets per host
make install build migrate
make systemd-install       # or: make run
```

Put **nginx / Caddy / WireGuard / SSH tunnel** in front. Keep `LNXADMIN_BIND_HOST=127.0.0.1` so the panel is not exposed on the public interface.

Notes from a real host deploy: [docs/deploy-issues.md](docs/deploy-issues.md).

---

## Security practices

Built-in:

- JWT auth on API routes; WebSocket auth via first message (token not in the URL)
- Login rate-limit / lockout; setup wizard rate-limited and localhost-only in production (or `LNXADMIN_SETUP_TOKEN`)
- Production mode **refuses to start** with default/weak JWT or admin password
- OpenAPI `/docs` disabled in production by default
- Security headers (CSP, `X-Frame-Options`, `nosniff`, …); HSTS only behind HTTPS
- CORS limited to configured origins and common methods/headers
- Mutations gated per module (`allow_mutations` defaults to **false**)
- Bind defaults to **127.0.0.1** (not `0.0.0.0`)
- Env-based login fallback removed — only the database user is accepted

Operator checklist:

1. Strong `LNXADMIN_JWT_SECRET` and admin password on every host  
2. Do not publish port 8000 publicly — use VPN, SSH tunnel, or reverse proxy + TLS + IP allowlist  
3. Grant **minimal** passwordless sudo only for the commands you need (see below)  
4. Keep mutations disabled until required  
5. Rotate secrets if `.env` was ever shared or committed  

Run `make check` after editing `.env`.

---

## Privileges (optional sudo)

Read-only views often work without root. Writes need elevated rights. Example **sudoers** snippets (tighten to your needs):

```sudoers
# Fail2ban / firewall / network
lnxadmin ALL=(root) NOPASSWD: /usr/bin/fail2ban-client, /usr/sbin/ufw, /usr/bin/firewall-cmd, /usr/sbin/nft, /usr/sbin/iptables, /usr/bin/systemctl, /sbin/ip, /bin/kill, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum, /usr/bin/install, /bin/mkdir

# Users / groups
lnxadmin ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupadd, /usr/sbin/groupdel, /usr/bin/passwd, /usr/bin/chage, /usr/sbin/chpasswd

# Services
lnxadmin ALL=(root) NOPASSWD: /usr/bin/systemctl

# SSH tunnel module
lnxadmin ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/userdel, /usr/sbin/usermod, /usr/sbin/groupadd, /usr/bin/install, /usr/bin/tee, /bin/chmod, /bin/chown, /bin/mkdir, /usr/bin/systemctl, /usr/sbin/sshd, /bin/rm

# WireGuard module
lnxadmin ALL=(root) NOPASSWD: /usr/bin/wg, /usr/bin/wg-quick, /usr/bin/systemctl, /usr/sbin/sysctl, /usr/sbin/iptables, /usr/bin/install, /bin/mkdir, /bin/chmod, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum

# OpenVPN module
lnxadmin ALL=(root) NOPASSWD: /usr/sbin/openvpn, /usr/bin/openvpn, /usr/bin/openssl, /usr/bin/systemctl, /usr/sbin/sysctl, /usr/sbin/iptables, /usr/bin/install, /bin/mkdir, /bin/chmod, /bin/chown, /bin/rm, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum

# Nginx Edge module
lnxadmin ALL=(root) NOPASSWD: /usr/sbin/nginx, /bin/systemctl, /usr/bin/systemctl, /usr/bin/certbot, /usr/bin/install, /bin/mkdir, /bin/chmod, /bin/chown, /bin/cp, /bin/mv, /bin/rm, /usr/bin/tee, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum
```

Prefer a dedicated OS user for the service and a narrow command list.

---

## PostgreSQL monitoring

A superuser is **not** required. Create a role with `pg_monitor` and optionally enable `pg_stat_statements`.

Step-by-step: [docs/postgres-monitoring.md](docs/postgres-monitoring.md)  
Checklist (restarts / 1C): [docs/TODO-pg-stat-statements.md](docs/TODO-pg-stat-statements.md)

Monitor credentials are stored under **Settings → Modules → PostgreSQL**, not in git.

---

## SSH Tunnel (jump host)

Restricted accounts for **LocalForward-only** access (no interactive shell). Typical use: developers reach an internal SSH/RDP/DB host through a public jump without full VPN.

| Concept | Details |
|---------|---------|
| Accounts | Prefix configurable (e.g. `bsktun-` / `tun-`); shell `nologin`; group match in sshd drop-in |
| Destinations | Per-user `permitopen` list (`host:port`) rewritten into `authorized_keys` |
| Keys | Generate RSA 4096 in the UI **or** add a user-supplied pubkey (**BYOK** — private key never on the server) |
| Public vs listen port | **Public SSH port** = value for client configs / NAT; **local sshd listen port** = where sessions are detected (default `22`) |
| Live sessions | Active `-N` tunnels: client, duration, TCP RX/TX (via `ss`), active forwards |
| History | Snapshots + connect/disconnect log (duration, traffic); charts under **History → SSH Tunnel** |
| Client pack | **Download ZIP**: `instructions.html` (setup, BYOK, VS Code/Cursor Remote SSH, troubleshooting), `ssh_config`, optional private key, `README.txt` |

Client connect pattern:

```bash
ssh -N tunnel-<username>          # keep running (no shell)
ssh -p <local_port> user@127.0.0.1   # or VS Code / Cursor Remote-SSH to 127.0.0.1:<local_port>
```

Settings: **Settings → Modules → SSH Tunnel** (`public_hostname`, `public_port`, `listen_port`, history interval, mutations).

---

## Nginx Edge Proxy

Publish apps through a managed edge nginx on this host: HTTPS reverse proxy, static files from a directory, TLS passthrough (SNI), TCP/UDP, certificates, Let’s Encrypt, templates (Carbonio, Nextcloud, OnlyOffice, Grafana, static directory, …), and safe apply with automatic rollback.

Operator guide (modes, ACME vs backends, Carbonio, troubleshooting): [docs/nginx-edge.md](docs/nginx-edge.md).

Typical flow: enable module → install nginx → issue LE for the public hostname → create route from template → point WAN **80/443** at this Edge host → Apply. Backend `backend_host` must be the app server IP, not the Edge itself.

**Static directory** serves a folder on this host (`static_http` on port 80, `static_https` on 443). No backend host. Example: `ps.ismarty.pro` → `/projects/ps.ismarty.pro`, index `iscript.ps1`. HTTPS uses an uploaded certificate whose SAN covers the name.

Certificates can be added as **files** (default) or pasted as PEM text. Apply starts host nginx if it is stopped, and it will not add a second `default_server` when the distro site already has one. If another process already holds ports 80/443, the public ACME listener is omitted so host nginx can still run for `stub_status`.

---

## Project layout

```text
lnxadmin/
├── .env.example          # bootstrap template (tracked)
├── Makefile              # install / build / run / systemd
├── deploy/lnxadmin.service
├── scripts/check_security.py
├── docs/
└── src/
    ├── backend/          # FastAPI + collectors + Alembic
    └── frontend/         # React + Ant Design + Vite
```

---

## API (selected)

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/api/auth/login` | JWT |
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/access/me` | Current principal + permissions |
| `GET` | `/api/access/...` | Users, roles, API keys (RBAC) |
| `GET` | `/api/system/...` | Live metrics |
| `WS` | `/ws/metrics` | Live stream (auth via first JSON message) |
| `GET` | `/api/history/metrics` | System history |
| `GET` | `/api/history/ssh-tunnel` | Tunnel session counts (+ aggregate traffic rates) |
| `GET` | `/api/history/ssh-tunnel/connections` | Connection log (duration, bytes, status) |
| `GET` | `/api/security/...` | Fail2ban / firewall |
| `GET` | `/api/ssh-tunnel` | Overview: users, live sessions |
| `GET`/`POST` | `/api/ssh-tunnel/users/...` | Users, keys, destinations, ssh-config |
| `POST` | `/api/ssh-tunnel/users/{user}/client-pack` | ZIP: instructions + config + optional key |
| `GET` | `/api/nginx/overview` | Edge proxy dashboard |
| `GET`/`POST` | `/api/nginx/routes` | Routes (templates, validate, apply) |
| `GET`/`POST` | `/api/nginx/certificates`, `/acme/*` | Certs & Let's Encrypt |

Full OpenAPI is available at `/docs` when `LNXADMIN_ENV=development` (or `LNXADMIN_DISABLE_DOCS=false`).

---

## License / support

Internal operations tooling. Adapt sudoers and network exposure to your security policy before production use.
