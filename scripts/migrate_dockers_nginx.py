#!/usr/bin/env python3
"""Migrate /dockers/nginx reverse-proxy vhosts into Linux Admin Nginx Edge."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("LNXADMIN_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("LNXADMIN_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("LNXADMIN_ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    print("Set LNXADMIN_ADMIN_PASSWORD (and optional LNXADMIN_URL / LNXADMIN_ADMIN_USER)", file=sys.stderr)
    sys.exit(1)

DOCKERS = Path("/dockers/nginx")
SECTIGO_CRT = DOCKERS / "server/conf.d/ssl/cert.crt"
SECTIGO_KEY = DOCKERS / "server/conf.d/ssl/cert.key"
LE_LIVE = DOCKERS / "letsencrypt/etc/live"

# Prefer host-published ports / LAN IPs (stable for host nginx).
ROUTES = [
    {
        "name": "cloud-amcham",
        "domain": "cloud.amcham.kg",
        "template_id": "nextcloud_docker",
        "backend_host": "127.0.0.1",
        "backend_port": 8086,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": True,
        },
    },
    {
        "name": "portal-amcham",
        "domain": "portal.amcham.kg",
        "template_id": "websocket_app",
        "backend_host": "192.168.68.3",
        "backend_port": 9000,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "connect_timeout": 60,
            "send_timeout": 86400,
            "read_timeout": 86400,
            "websocket": True,
            "headers": [{"name": "X-Forwarded-Host", "value": "$host"}],
        },
    },
    {
        "name": "crm-amcham",
        "domain": "crm.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "127.0.0.1",
        "backend_port": 8083,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
    },
    {
        "name": "appform-amcham",
        "domain": "appform.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 8999,
        "cert": "sectigo",
        "deny_ips": ["45.148.10.90"],
        "overrides": {
            "client_max_body_size": "20m",
            "websocket": False,
        },
    },
    {
        "name": "checkin-amcham",
        "domain": "checkin.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 9992,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
        "notes": "Old conf used expired STAR 2025-2026; migrated to current Sectigo wildcard.",
    },
    {
        "name": "checkintest-amcham",
        "domain": "checkintest.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 9993,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
        "notes": "Path /admintest→:9992 not expressible as separate location; primary / → :9993 only.",
    },
    {
        "name": "vcard-amcham",
        "domain": "vcard.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 8091,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
    },
    {
        "name": "files-amcham",
        "domain": "files.amcham.kg",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.1",
        "backend_port": 8081,
        "cert": "sectigo",
        "overrides": {
            "client_max_body_size": "100m",
            "websocket": False,
        },
        "notes": "Original CORS OPTIONS preflight not fully reproduced by Edge headers model.",
    },
    {
        "name": "u-ismarty",
        "domain": "u.ismarty.pro",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 8092,
        "cert": "le:u.ismarty.pro",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
        "notes": "LE cert on disk expired; re-issue via ACME after cutover.",
    },
    {
        "name": "portal-ismarty",
        "domain": "portal.ismarty.pro",
        "template_id": "webapp_https",
        "backend_host": "192.168.68.3",
        "backend_port": 90,
        "cert": "le:portal.ismarty.pro",
        "overrides": {
            "client_max_body_size": "0",
            "websocket": False,
        },
        "notes": "LE cert on disk expired; re-issue via ACME after cutover.",
    },
]


def api(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} → {exc.code}: {detail}") from exc


def read_pem(path: Path) -> str:
    text = path.read_text()
    if "BEGIN" not in text:
        raise RuntimeError(f"Not a PEM: {path}")
    return text


def upload_cert(token: str, name: str, fullchain: str, key: str) -> str:
    # Split leaf + chain if multiple certs in fullchain
    parts = [p.strip() for p in fullchain.split("-----END CERTIFICATE-----") if "BEGIN CERTIFICATE" in p]
    leaf = parts[0] + "\n-----END CERTIFICATE-----\n" if parts else fullchain
    chain = ""
    if len(parts) > 1:
        chain = "\n".join(p + "\n-----END CERTIFICATE-----" for p in parts[1:]) + "\n"
    body = {
        "name": name,
        "certificate_pem": leaf,
        "private_key_pem": key,
    }
    if chain.strip():
        body["chain_pem"] = chain
    res = api("POST", "/api/nginx/certificates", token, body)
    cert = res.get("certificate") or {}
    cid = cert.get("id")
    if not cid:
        raise RuntimeError(f"No cert id for {name}: {res}")
    print(f"  cert {name}: {cid} ({cert.get('not_after')}, days_left={cert.get('days_left')})")
    return cid


def main() -> int:
    print("== login ==")
    login = api("POST", "/api/auth/login", body={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    token = login["access_token"]

    print("== enable nginx module mutations ==")
    api(
        "PUT",
        "/api/settings",
        token,
        {
            "modules": {
                "nginx": {
                    "enabled": True,
                    "allow_mutations": True,
                    "allow_install": True,
                    "acme_email": "admin@ismarty.pro",
                    "acme_environment": "production",
                }
            }
        },
    )

    print("== import certificates ==")
    cert_ids: dict[str, str] = {}
    cert_ids["sectigo"] = upload_cert(
        token,
        "star.amcham.kg-sectigo",
        read_pem(SECTIGO_CRT),
        read_pem(SECTIGO_KEY),
    )
    for domain in ("u.ismarty.pro", "portal.ismarty.pro"):
        live = LE_LIVE / domain
        if not (live / "fullchain.pem").exists():
            print(f"  skip LE {domain}: missing")
            continue
        cert_ids[f"le:{domain}"] = upload_cert(
            token,
            f"le-{domain}",
            read_pem(live / "fullchain.pem"),
            read_pem(live / "privkey.pem"),
        )

    print("== create routes (apply=false) ==")
    created = []
    for spec in ROUTES:
        cert_key = spec["cert"]
        cert_id = cert_ids.get(cert_key)
        if not cert_id:
            print(f"  SKIP {spec['domain']}: missing cert {cert_key}")
            continue
        body = {
            "template_id": spec["template_id"],
            "name": spec["name"],
            "domain": spec["domain"],
            "backend_host": spec["backend_host"],
            "backend_port": spec["backend_port"],
            "cert_id": cert_id,
            "enabled": True,
            "apply": False,
            "overrides": {
                "frontend_ip": "0.0.0.0",
                "frontend_port": 443,
                "proxy_type": "https_reverse",
                "backend_proto": "http",
                "http2": True,
                **spec.get("overrides", {}),
            },
        }
        if spec.get("deny_ips"):
            body["deny_ips"] = spec["deny_ips"]
        if spec.get("allow_ips"):
            body["allow_ips"] = spec["allow_ips"]
        try:
            res = api("POST", "/api/nginx/routes/from-template", token, body)
            rid = (res.get("route") or res).get("id") or (res.get("route") or {}).get("name")
            print(f"  OK {spec['domain']} → {rid}")
            if spec.get("notes"):
                print(f"     note: {spec['notes']}")
            created.append(spec["domain"])
        except RuntimeError as exc:
            # Retry as plain POST /routes if template fails
            print(f"  template failed for {spec['domain']}: {exc}; trying POST /routes")
            route_body = {
                "name": spec["name"],
                "domain": spec["domain"],
                "proxy_type": "https_reverse",
                "frontend_ip": "0.0.0.0",
                "frontend_port": 443,
                "backend_host": spec["backend_host"],
                "backend_port": spec["backend_port"],
                "backend_proto": "http",
                "cert_id": cert_id,
                "http2": True,
                "apply": False,
                **spec.get("overrides", {}),
            }
            res = api("POST", "/api/nginx/routes", token, route_body)
            print(f"  OK {spec['domain']} (direct) → {(res.get('route') or res).get('id')}")
            created.append(spec["domain"])

    print("== list routes ==")
    listing = api("GET", "/api/nginx/routes", token)
    routes = listing.get("routes") or listing.get("items") or []
    if isinstance(routes, list):
        for r in routes:
            print(
                f"  {r.get('name')}: {r.get('domain')} → "
                f"{r.get('backend_host')}:{r.get('backend_port')} cert={r.get('cert_id')} enabled={r.get('enabled')}"
            )
    else:
        print(json.dumps(listing, indent=2)[:2000])

    print("== validate ==")
    try:
        val = api("POST", "/api/nginx/routes/validate", token, {})
        print(json.dumps(val, indent=2)[:3000])
    except RuntimeError as exc:
        print(f"validate endpoint: {exc}")

    print(f"\nDone. Created {len(created)} routes: {', '.join(created)}")
    print("Skipped static sites: d.ismarty.pro, reg.ismarty.pro (not reverse proxies).")
    print("NOT applied live yet — docker nginx still owns :80/:443.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
