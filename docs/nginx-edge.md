# Nginx Edge Proxy

Central edge reverse proxy managed by Linux Admin: publish HTTP/HTTPS apps, terminate TLS, pass through SNI, proxy TCP/UDP, issue Let’s Encrypt certificates, and apply config safely (`nginx -t` → backup → reload → rollback).

State lives under `/var/lib/lnxadmin/nginx/`. Generated config is written to `/etc/nginx/lnxadmin/` and included from `/etc/nginx/conf.d/00-lnxadmin.conf`.

---

## Capabilities

| Area | Details |
|------|---------|
| **Proxy modes** | HTTP reverse, HTTPS reverse (TLS termination), static directory (HTTP/HTTPS), TLS passthrough (stream + SNI / `ssl_preread`), TCP, UDP |
| **HTTP features** | WebSocket, HTTP/2, large header buffers (Carbonio/Zimbra), custom headers, body size limits, timeouts, IP allow/deny |
| **Static sites** | `root` + `index` + `try_files` from an absolute directory. `.ps1` / `.psm1` / `.psd1` / `.sh` are served as `text/plain` |
| **Load balancing** | Multiple backends, `round_robin` / `least_conn` / `ip_hash`, weights, `max_fails` / `fail_timeout` |
| **Certificates** | Upload PEM as files (default) or pasted text, plus PFX and CSR; Let’s Encrypt HTTP-01 and manual DNS-01; auto-renew settings |
| **Templates** | Static directory, Nextcloud, OnlyOffice, Carbonio Web/Admin, generic web/API, MS RDS/RDP, Portainer, Grafana, Proxmox, Home Assistant, MinIO, PostgreSQL TCP, WireGuard UDP, TLS passthrough |
| **Lifecycle** | Install nginx/certbot if missing, start/stop/reload, config preview, safe apply, backups, rollback |
| **Ops** | Per-route access/error logs, backend health probes, Prometheus-style metrics endpoint |
| **RBAC** | Module **read** / **full**; mutations also require `allow_mutations` in Settings |

---

## Quick start

1. **Settings → Modules → Nginx Edge** — enable module; set `allow_mutations` when you are ready to write config.
2. Open **Nginx Edge** → **Install** if nginx is not present.
3. Set ACME email under Certificates / ACME settings.
4. Create a route (**From template** or manually) → **Check for errors** → Save with **Apply**.
5. Point WAN **80/443** (NAT/firewall) at this host’s Edge IP — not at backend app hosts, unless you use TLS passthrough only.

Frontend bind defaults to `0.0.0.0:443` (or `:80` for HTTP). Keep the Linux Admin panel itself on `127.0.0.1:8000` behind VPN/tunnel.

---

## Proxy modes

### HTTPS reverse (TLS termination)

Edge presents the public certificate. Backend may be `http` or `https` (`verify_backend_tls` usually `false` for private/self-signed upstreams).

Use for: Carbonio web UI, Nextcloud, Grafana, Portainer, generic apps.

### TLS passthrough

Edge does **not** decrypt TLS. Certificate stays on the backend. Renewal must happen on the backend (or via DNS-01 there).

### TCP / UDP

Stream proxy for databases, RDP, WireGuard, etc. Combine with `allow_ips` when exposing sensitive ports.

### Static directory

Serves files from a folder on this host. There is no backend.

| Field | Meaning |
|-------|---------|
| `proxy_type` | `static_http` or `static_https` |
| `static_root` | Absolute path, for example `/projects/ps.ismarty.pro`. `..`, `;`, `{`, `}` are rejected |
| `index` | Space-separated index names. Default `index.html index.htm`. A script site can use `iscript.ps1 index.html index.htm` |
| `cert_id` | Required for `static_https` before Apply |

Use two routes for the same folder when you want both schemes: HTTP on port 80 and HTTPS on port 443 with a certificate that covers the domain (a `*.example.com` upload is enough).

Template **Static directory** (category Web) pre-fills HTTPS, port 443, and a placeholder root `/var/www/site`. Override `domain`, `name`, and `static_root`, then pick the certificate.

`.ps1`, `.psm1`, `.psd1`, and `.sh` get `default_type text/plain` so browsers show the script instead of downloading it as an unknown type.

---

## Let’s Encrypt on Edge vs backends

When WAN 80/443 DNAT targets the **Edge** host:

| Layer | Certificate | Renewal |
|-------|-------------|---------|
| **Browser → Edge** (`https_reverse`) | LE on Edge (panel ACME) | HTTP-01 on Edge webroot; keep port **80** open to Edge |
| **Edge → backend** | Backend’s own cert (often self-signed) | Not required to be public LE if `verify_backend_tls` is false |
| **TLS passthrough** | Backend owns the public cert | Backend ACME or DNS-01; Edge only forwards by SNI |
| **Mail protocols** (25/465/587/993…) | Usually terminate on mail host, not Edge | Separate LE/DNS-01 on Carbonio (or sync Edge cert after renew) |

**Important:** After moving NAT from an app host (e.g. Carbonio) to Edge, the app’s old HTTP-01 certbot will stop renewing — challenges hit Edge. For web UI behind `https_reverse`, that is expected: Edge owns the public cert.

Recommended for Carbonio:

1. **Web UI** — Edge LE + HTTPS reverse to Carbonio `:443` (`verify_backend_tls: false`, `large_headers: true`).
2. **SMTP/IMAP** — valid cert on Carbonio itself (DNS-01, or deploy Edge cert after each renew).
3. Do **not** set `backend_host` to the Edge IP — that creates a proxy loop (`400 Request Header Or Cookie Too Large` / `502`).

---

## Route templates (highlights)

| Template | Notes |
|----------|--------|
| **Carbonio Web** | Backend = Carbonio IP (not Edge). Enables `large_headers`, WebSocket, long timeouts, `200m` body. |
| **Carbonio Admin** | Backend `:6071`; restrict with `allow_ips` / VPN. Separate admin hostname + cert. |
| **Static directory** | Folder on this host. Set `static_root`. HTTPS needs a certificate. No `backend_host`. |
| **Nextcloud / OnlyOffice** | Large uploads, WebSocket where needed. |
| **MS RDS / RDP** | HTTPS gateway or TCP as appropriate; change placeholder backend IP. |
| **WireGuard UDP** | Stream UDP to `wg` listen port. |
| **TLS passthrough** | SNI routing; certs renew on backend. |

Always override `domain`. For proxy templates also override `backend_host`. For a static site override `static_root` instead. Run **Check for errors** before apply.

---

## Safe apply

1. Render managed config under `/etc/nginx/lnxadmin/`.
2. `nginx -t`.
3. Backup previous managed files.
4. Atomic write + graceful reload.
5. On failure — restore backup and reload again.

Backups are listed in the UI; you can roll back explicitly.

Apply also handles common host conflicts:

- If `/etc/nginx/sites-enabled` already has `listen … default_server` on port 80, the managed ACME server does not add another `default_server`.
- If host `nginx.service` is inactive, Apply removes an empty `/run/nginx.pid` and starts the unit instead of reloading a dead pid.
- If ports 80 or 443 are already held by another process (often Docker `nginx`), the public `:80` ACME listener is left out so host nginx can still start and serve `stub_status` on `127.0.0.1:8088`. Those routes stay in the panel, but they will not bind on the host until the other listener releases the ports. On a host where Docker owns 80/443, publish the same `root` in that container’s `conf.d` and mount the directory into the container.

---

## Settings (module options)

| Option | Purpose |
|--------|---------|
| `enabled` | Show module / allow API |
| `allow_mutations` | Permit writes (routes, certs, apply) |
| `allow_install` | Permit package install of nginx/certbot |
| `data_dir` | Panel state (`/var/lib/lnxadmin/nginx`) |
| `managed_dir` | Generated nginx snippets |
| `acme_email` / `acme_environment` | Let’s Encrypt account |
| `renew_days_before` | Renew window (default 30 days) |
| `log_lines` | Lines returned by log API |

---

## Privileges (sudo)

Nginx apply/install needs elevated rights. Example (tighten to your OS paths):

```sudoers
# Nginx Edge module
lnxadmin ALL=(root) NOPASSWD: /usr/sbin/nginx, /bin/systemctl, /usr/bin/systemctl, /usr/bin/certbot, /usr/bin/install, /bin/mkdir, /bin/chmod, /bin/chown, /bin/cp, /bin/mv, /bin/rm, /usr/bin/tee, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum
```

---

## API (selected)

Prefix: `/api/nginx` — requires module permission.

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/overview` | Dashboard metrics |
| `POST` | `/install` | Install nginx/certbot |
| `GET` | `/templates` | Route templates |
| `GET`/`POST` | `/routes` | List / upsert (optional `apply`) |
| `POST` | `/routes/from-template` | Create from template |
| `POST` | `/routes/validate` | Pre-flight checks |
| `POST` | `/config/apply` | Safe apply |
| `GET`/`POST` | `/certificates`, `/acme/*` | Certs & ACME |
| `GET` | `/backends/health` | Upstream probes |
| `GET` | `/metrics` | Prometheus-style gauges |

Full OpenAPI: `/docs` in development (or when docs are enabled).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `400 Request Header Or Cookie Too Large` | Proxy loop (backend = Edge), or huge cookies — enable `large_headers`, clear site cookies, fix `backend_host` |
| `502 Bad Gateway` | Backend down, wrong port/proto, or TLS handshake to upstream failed |
| ACME / renew fails | WAN 80 not DNAT to Edge; firewall; another vhost stealing `/.well-known`; public :80 omitted because Docker already holds the port |
| `duplicate default server for 0.0.0.0:80` | Distro site in `sites-enabled` already has `default_server`. Apply skips a second one; move the distro symlink out of `sites-enabled` if you want Edge to own the default |
| `nginx.service is not active` / empty pid | Apply starts nginx instead of `nginx -s reload`. If start still fails with `address already in use`, another process holds 80/443 |
| `nginx -t` fails on `http2 on` | Ubuntu nginx 1.24 uses `listen … ssl http2` (module already generates that form) |
| Admin UI exposed | Use `allow_ips`, VPN, or do not publish admin hostname publicly |
