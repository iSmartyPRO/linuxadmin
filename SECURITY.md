# SECURITY.md — operational security notes for Linux Admin

## Threat model (short)

This panel can view host state and, if mutations are enabled, change firewall rules,
users, services, and SSH tunnel accounts. Treat access as **equivalent to limited root**.

## Hardening checklist

1. **Network**
   - Keep `LNXADMIN_BIND_HOST=127.0.0.1`.
   - Expose only via VPN, SSH local forward, or reverse proxy with TLS + IP allowlist.
   - Example proxy: `deploy/nginx.example.conf`.

2. **Secrets**
   - Generate JWT: `openssl rand -hex 32`.
   - Never reuse default `admin` / `admin` in production (`LNXADMIN_ENV=production` refuses it).
   - Never commit `.env`. Rotate secrets after any leak.

3. **Auth**
   - Login uses the database user created on first start from `.env`.
   - Changing `LNXADMIN_ADMIN_PASSWORD` later does **not** auto-update the DB hash — set a new password via a controlled process or recreate the user.
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
