# SECURITY.md — operational security notes for Linux Admin

## Threat model (short)

This panel can view host state and, if mutations are enabled, change firewall rules,
users, services, and SSH tunnel accounts. Treat access as **equivalent to limited root**.

## Built-in protections

- Production refuses weak JWT / admin / empty DB password after setup
- Login rate-limit + lockout (per client IP) and short delay on failed login
- Setup wizard: rate-limited; in production only from localhost unless `LNXADMIN_SETUP_TOKEN` is set
- WebSocket metrics auth via first JSON message (token **not** in the URL)
- JWT kept in `sessionStorage` (cleared when the browser session ends)
- Admin password from `.env` is applied only when creating the user — not overwritten on every restart
- Mutations default off; OpenAPI docs disabled in production; security response headers

## Hardening checklist

1. **Network**
   - Keep `LNXADMIN_BIND_HOST=127.0.0.1`.
   - Expose only via VPN, SSH local forward, or reverse proxy with TLS + IP allowlist.
   - Example proxy: `deploy/nginx.example.conf`.
   - Set `LNXADMIN_TRUST_PROXY=true` only when the proxy strips/forges client IP headers safely.

2. **Secrets**
   - Generate JWT: `openssl rand -hex 32`.
   - Never reuse default `admin` / `admin` in production (`LNXADMIN_ENV=production` refuses it).
   - Never commit `.env`. Rotate secrets after any leak.
   - Before first setup on a reachable host: set `LNXADMIN_SETUP_TOKEN` and pass it in the wizard.

3. **Auth**
   - Login uses the database user created on first start from `.env`.
   - Changing only `LNXADMIN_ADMIN_PASSWORD` in `.env` does **not** rewrite an existing DB hash —
     use **Settings → Connection** (updates DB + `.env`) or recreate the user.
   - Prefer shorter JWT TTL in hostile networks (`LNXADMIN_JWT_EXPIRE_MINUTES`).

4. **Mutations**
   - Leave `allow_mutations` off until needed.
   - Scope sudoers to exact binaries (see README). Prefer a dedicated service user.

5. **Application**
   - Production disables `/docs` by default.
   - Security headers are applied on responses; HSTS only when the request is HTTPS (or `X-Forwarded-Proto: https`).
   - Run `make check` after editing `.env`.

6. **Supply chain**
   - Pin dependencies (`requirements.txt`, `package-lock.json`).
   - Build frontend on a trusted host (`make build`).

## Reporting

Treat this as internal ops software. Report issues to your infrastructure team.
