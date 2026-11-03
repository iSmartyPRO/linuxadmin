"""Multilingual instructions.html for SSH Tunnel client ZIP (EN / RU / TR switcher).

Short quick-start is shown by default; the long guide is behind a collapsed <details>.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from app.services.ssh_tunnel_pack_i18n import LOCALES, fmt, get_strings


def _identity_basename(identity_file: str, username: str) -> str:
    name = (identity_file or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", ".."):
        return f"{username}_rsa4096"
    safe = re.sub(r"[^\w.+=@-]", "_", name)
    return safe[:120] or f"{username}_rsa4096"


def _esc_pre(text: str) -> str:
    return html.escape(text)


def _render_details_body(locale: str, ctx: dict[str, Any]) -> str:
    """Long-form sections (collapsed by default)."""
    t = lambda key, **kw: fmt(locale, key, **{**ctx, **kw})  # noqa: E731
    has_key = bool(ctx["has_key"])
    alias = ctx["alias"]
    identity = ctx["identity"]
    key_name = ctx["key_name"]
    config = ctx["config"]
    forwards_table = ctx["forwards_table"]
    forwards_maps = ctx["forwards_maps"]
    first_lp = ctx["first_lp"]
    first_label = ctx["first_label"]
    first_ide_alias = ctx["first_ide_alias"]
    ide_hosts_pre = ctx["ide_hosts_pre"]
    suffix = f"-{locale}"
    byok_extra = t("tr_pubkey_byok_extra") if not has_key else ""

    if has_key:
        key_file_card = (
            f"<div class='file'><div class='ico'>03</div><div><strong>{key_name}</strong>"
            f"<div class='muted'>{t('file_key_in_zip')}</div></div></div>"
        )
        install_key_section = f"""
      <section id="install-key{suffix}">
        <h2>{t("key_with_title")}</h2>
        <p class="lead">{t("key_with_lead")}</p>
        <div class="steps">
          <div class="step"><div>
            <strong>{t("key_with_step1_title")}</strong>
            <pre>mkdir -p ~/.ssh
chmod 700 ~/.ssh</pre>
          </div></div>
          <div class="step"><div>
            <strong>{t("key_with_step2_title")}</strong>
            <pre>cp {key_name} ~/.ssh/{key_name}
chmod 600 ~/.ssh/{key_name}</pre>
            <p>{t("key_with_step2_win")}</p>
          </div></div>
        </div>
        <div class="callout warn">{t("key_with_warn")}</div>
      </section>"""
        windows_key_steps = _esc_pre(t("win_steps_with_key"))
        unix_key_steps = _esc_pre(t("unix_steps_with_key"))
        identity_callout = t("key_with_identity")
    else:
        key_file_card = (
            f"<div class='file'><div class='ico'>03</div><div><strong>{t('file_key_byok_title')}</strong>"
            f"<div class='muted'>{t('file_key_byok')}</div></div></div>"
        )
        install_key_section = f"""
      <section id="install-key{suffix}">
        <h2>{t("key_byok_title")}</h2>
        <p class="lead">{t("key_byok_lead")}</p>
        <div class="callout">{t("key_byok_callout")}</div>
        <div class="steps">
          <div class="step"><div>
            <strong>{t("key_byok_step1_title")}</strong>
            <pre>{_esc_pre(t("key_byok_step1_pre"))}</pre>
          </div></div>
          <div class="step"><div>
            <strong>{t("key_byok_step2_title")}</strong>
            <p>{t("key_byok_step2_p1")}</p>
            <pre>IdentityFile {identity}</pre>
            <p>{t("key_byok_step2_p2")}</p>
            <pre>{_esc_pre(t("key_byok_step2_pre"))}</pre>
          </div></div>
          <div class="step"><div>
            <strong>{t("key_byok_step3_title")}</strong>
            <pre>chmod 700 ~/.ssh
chmod 600 {identity}</pre>
          </div></div>
        </div>
        <div class="callout warn">{t("key_byok_warn")}</div>
      </section>"""
        windows_key_steps = _esc_pre(t("win_steps_byok"))
        unix_key_steps = _esc_pre(t("unix_steps_byok"))
        identity_callout = t("key_byok_identity")

    return f"""
      <section id="contents{suffix}">
        <h2>{t("contents_title")}</h2>
        <p class="lead">{t("contents_lead")}</p>
        <div class="files">
          <div class="file"><div class="ico">01</div><div><strong>instructions.html</strong><div class="muted">{t("file_instructions")}</div></div></div>
          <div class="file"><div class="ico">02</div><div><strong>ssh_config</strong><div class="muted">{t("file_ssh_config")}</div></div></div>
          {key_file_card}
          <div class="file"><div class="ico">04</div><div><strong>README.txt</strong><div class="muted">{t("file_readme")}</div></div></div>
        </div>
      </section>

      {install_key_section}

      <section id="ssh-config-detail{suffix}">
        <h2>{t("ssh_config_title")}</h2>
        <p class="lead">{t("ssh_config_lead")}</p>
        <div class="steps">
          <div class="step"><div>
            <strong>{t("ssh_config_step_unix")}</strong>
            <pre>{_esc_pre(t("ssh_config_step_unix_pre"))}</pre>
          </div></div>
          <div class="step"><div>
            <strong>{t("ssh_config_step_append")}</strong>
            <pre>cat ssh_config >> ~/.ssh/config
chmod 600 ~/.ssh/config</pre>
          </div></div>
        </div>
        <h3>{t("ssh_config_ready")}</h3>
        <pre>{config}</pre>
        <div class="callout">{identity_callout}</div>
      </section>

      <section id="start-tunnel{suffix}">
        <h2>{t("start_title")}</h2>
        <p class="lead">{t("start_lead")}</p>
        <pre>ssh -N {alias}</pre>
        <p class="muted">{t("start_hangs")}</p>
        <div class="callout">{t("start_bg")}</div>
        <h3>{t("start_map")}</h3>
        {forwards_maps}
      </section>

      <section id="use-services{suffix}">
        <h2>{t("services_title")}</h2>
        <p class="lead">{t("services_lead")}</p>
        <table>
          <thead>
            <tr><th>{t("th_service")}</th><th>{t("th_local")}</th><th>{t("th_target")}</th><th>{t("th_example")}</th></tr>
          </thead>
          <tbody>{forwards_table}</tbody>
        </table>
        <div class="callout warn">{t("services_warn")}</div>
      </section>

      <section id="localforward{suffix}">
        <h2>{t("lf_title")}</h2>
        <p class="lead">{t("lf_lead")}</p>
        <pre>{_esc_pre(t("lf_pre"))}</pre>
        <div class="callout danger">
          <strong>{t("lf_danger_title")}</strong> {t("lf_danger_body")}
          <pre style="margin-top:10px">{_esc_pre(t("lf_danger_pre"))}</pre>
        </div>
        <h3>{t("lf_why_title")}</h3>
        <ul>
          <li>{t("lf_why_1")}</li>
          <li>{t("lf_why_2")}</li>
          <li>{t("lf_why_3")}</li>
          <li>{t("lf_why_4")}</li>
        </ul>
        <div class="callout">{t("lf_tip")}</div>
      </section>

      <section id="examples{suffix}">
        <h2>{t("ex_title")}</h2>
        <h3>{t("ex_ssh_title")}</h3>
        <pre>{_esc_pre(t("ex_ssh_pre"))}</pre>
        <h3>{t("ex_scp_title")}</h3>
        <pre>scp -P {first_lp} ./file.txt yourlogin@127.0.0.1:/tmp/
sftp -P {first_lp} yourlogin@127.0.0.1</pre>
        <h3>{t("ex_rdp_title")}</h3>
        <pre>{_esc_pre(t("ex_rdp_pre"))}</pre>
        <h3>{t("ex_check_title")}</h3>
        <pre># Linux/macOS
nc -vz 127.0.0.1 {first_lp}

ssh -N -v {alias}</pre>
      </section>

      <section id="ide{suffix}">
        <h2>{t("ide_title")}</h2>
        <p class="lead">{t("ide_lead")}</p>
        <div class="callout danger">{t("ide_danger")}</div>
        <div class="steps">
          <div class="step"><div>
            <strong>{t("ide_step1_title")}</strong>
            <pre>ssh -N {alias}</pre>
            <p>{t("ide_step1_p")}</p>
          </div></div>
          <div class="step"><div>
            <strong>{t("ide_step2_title")}</strong>
            <p>{t("ide_step2_p")}</p>
            <pre>{ide_hosts_pre}</pre>
            <p class="muted">{t("ide_step2_note")}</p>
          </div></div>
          <div class="step"><div>
            <strong>VS Code</strong>
            <p>{t("ide_vscode_p")}</p>
            <pre>1. F1 / Ctrl+Shift+P → “Remote-SSH: Connect to Host…”
2. Select {first_ide_alias} (or yourlogin@127.0.0.1:{first_lp})
3. Open Folder on the server</pre>
          </div></div>
          <div class="step"><div>
            <strong>Cursor</strong>
            <p>{t("ide_cursor_p")}</p>
            <pre>1. Ctrl+Shift+P (Cmd+Shift+P on macOS)
2. “Remote-SSH: Connect to Host…” → {first_ide_alias}
3. Wait for remote server install
4. File → Open Folder</pre>
            <p class="muted">{t("ide_cursor_note")}</p>
          </div></div>
        </div>
        <h3>{t("ide_jb_title")}</h3>
        <pre># 1) ssh -N {alias}
# 2) JetBrains Gateway → SSH → New Connection
#    Host: 127.0.0.1
#    Port: {first_lp}
#    Username: yourlogin</pre>
        <h3>{t("ide_scheme_title")}</h3>
        <pre>{_esc_pre(t("ide_scheme_pre"))}</pre>
        <div class="callout warn">{t("ide_warn")}</div>
      </section>

      <section id="windows{suffix}">
        <h2>{t("win_title")}</h2>
        <p class="lead">{t("win_lead")}</p>
        <h3>{t("win_openssh")}</h3>
        <pre>{windows_key_steps}</pre>
        <h3>{t("win_path")}</h3>
        <p class="muted">{t("win_path_note")}</p>
      </section>

      <section id="macos-linux{suffix}">
        <h2>{t("unix_title")}</h2>
        <pre>{unix_key_steps}</pre>
        <div class="callout">{t("unix_fingerprint")}</div>
      </section>

      <section id="troubleshooting{suffix}">
        <h2>{t("trouble_title")}</h2>
        <h3>{t("tr_nologin_title")}</h3>
        <p class="muted">{t("tr_nologin_body")}</p>
        <h3>{t("tr_pubkey_title")}</h3>
        <p class="muted">{t("tr_pubkey_body", byok_extra=byok_extra)}</p>
        <h3>{t("tr_bind_title")}</h3>
        <p class="muted">{t("tr_bind_body")}</p>
        <h3>{t("tr_admin_title")}</h3>
        <p class="muted">{t("tr_admin_body").replace("#localforward", f"#localforward{suffix}")}</p>
        <h3>{t("tr_web_title")}</h3>
        <p class="muted">{t("tr_web_body").replace("#localforward", f"#localforward{suffix}")}</p>
        <h3>{t("tr_close_title")}</h3>
        <p class="muted">{t("tr_close_body")}</p>
        <h3>{t("tr_ide_title")}</h3>
        <p class="muted">{t("tr_ide_body").replace("#ide", f"#ide{suffix}")}</p>
      </section>

      <section id="security{suffix}">
        <h2>{t("sec_title")}</h2>
        <ul>
          <li>{t("sec_1")}</li>
          <li>{t("sec_2")}</li>
          <li>{t("sec_3")}</li>
          <li>{t("sec_4")}</li>
          <li>{t("sec_5")}</li>
        </ul>
        <div class="callout danger">{t("sec_danger")}</div>
      </section>
"""


def _render_pane(locale: str, ctx: dict[str, Any]) -> str:
    t = lambda key, **kw: fmt(locale, key, **{**ctx, **kw})  # noqa: E731
    has_key = bool(ctx["has_key"])
    username = ctx["username"]
    alias = ctx["alias"]
    hostname = ctx["hostname"]
    port = ctx["port"]
    config = ctx["config"]
    forwards_table = ctx["forwards_table"]
    suffix = f"-{locale}"

    key_step = t("quick_s1_zip") if has_key else t("quick_s1_byok")
    key_chip = (
        f'<span class="chip">{t("chip_key_in_zip")}</span>'
        if has_key
        else f'<span class="chip">{t("chip_key_byok")}</span>'
    )
    details_body = _render_details_body(locale, ctx)

    return f"""
  <div class="lang-pane" data-lang="{locale}" hidden>
  <div class="topbar">
    <div class="brand">Linux Admin <span>·</span> SSH Tunnel</div>
    <a href="#quick{suffix}">{t("toc_jump")}</a>
  </div>

  <header class="hero" id="overview{suffix}">
    <div class="eyebrow">{t("eyebrow")}</div>
    <h1>{t("hero_title")}</h1>
    <p class="essence">{t("hero_intro")}</p>
    <div class="meta">
      <span class="chip">ssh -N <strong class="mono">{alias}</strong></span>
      <span class="chip">Jump <strong class="mono">{hostname}:{port}</strong></span>
      {key_chip}
    </div>
  </header>

  <main class="main-simple">
    <section class="quick" id="quick{suffix}">
      <h2>{t("quick_title")}</h2>
      <p class="lead">{t("quick_enough")}</p>

      <ol class="quick-list">
        <li>
          <strong>{t("quick_s1_title")}</strong>
          <p>{key_step}</p>
        </li>
        <li>
          <strong>{t("quick_s2_title")}</strong>
          <p>{t("quick_s2_body")}</p>
          <pre>{config}</pre>
        </li>
        <li>
          <strong>{t("quick_s3_title")}</strong>
          <p>{t("quick_s3_body")}</p>
          <pre>ssh -N {alias}</pre>
          <p class="note">{t("quick_s3_note")}</p>
        </li>
        <li>
          <strong>{t("quick_s4_title")}</strong>
          <p>{t("quick_s4_body")}</p>
        </li>
        <li>
          <strong>{t("quick_s5_title")}</strong>
          <p>{t("quick_s5_body")}</p>
          <h3 class="ports-h">{t("ports_title")}</h3>
          <table>
            <thead>
              <tr><th>{t("th_service")}</th><th>{t("th_local")}</th><th>{t("th_target")}</th><th>{t("th_example")}</th></tr>
            </thead>
            <tbody>{forwards_table}</tbody>
          </table>
        </li>
        <li>
          <strong>{t("quick_s6_title")}</strong>
          <p>{t("quick_s6_body")}</p>
          <p class="muted">{t("quick_hosts_win")}<br/>{t("quick_hosts_unix")}</p>
          <pre>{_esc_pre(t("quick_hosts_ex"))}</pre>
        </li>
      </ol>
    </section>

    <details class="details-block" id="details{suffix}">
      <summary>
        <span class="details-title">{t("details_summary")}</span>
        <span class="details-hint">{t("details_hint")}</span>
      </summary>
      <div class="details-body">
        {details_body}
      </div>
    </details>
  </main>

  <p class="footer">
    {t("footer_gen")} <span class="mono">{username}</span> ·
    <a href="#quick{suffix}">{t("footer_toc")}</a> · <a href="#overview{suffix}">{t("footer_top")}</a>
  </p>
  <p class="footer powered">{t("powered_by")}</p>
  </div>"""


def build_instructions_html(pack: dict[str, Any]) -> str:
    """Standalone HTML guide with in-page EN / RU / TR language switcher."""
    username = html.escape(str(pack.get("username") or ""))
    alias = html.escape(str(pack.get("host_alias") or f"tunnel-{pack.get('username')}"))
    hostname = html.escape(str(pack.get("public_hostname") or ""))
    port = int(pack.get("public_port") or 22)
    identity = html.escape(str(pack.get("identity_file") or f"~/.ssh/{pack.get('username')}_rsa4096"))
    key_name = html.escape(
        str(
            pack.get("private_key_filename")
            or _identity_basename(str(pack.get("identity_file") or ""), str(pack.get("username") or "tunnel"))
        )
    )
    has_key = bool(pack.get("has_private_key"))
    config = html.escape(str(pack.get("config") or ""))
    forwards = pack.get("forwards") or []

    forward_rows_tpl = []
    forward_cards = []
    for fw in forwards:
        lp = int(fw.get("local_port") or 0)
        host = html.escape(str(fw.get("host") or ""))
        rport = int(fw.get("port") or 0)
        label = html.escape(str(fw.get("label") or "").strip() or "Service")
        example = f"localhost:{lp}"
        if rport == 3389 or "rdp" in label.lower():
            example = f"mstsc → 127.0.0.1:{lp}"
        elif rport in (80, 8080):
            example = f"http://127.0.0.1:{lp}"
        elif rport in (443, 8443):
            example = f"https://127.0.0.1:{lp}"
        elif rport == 22 or "ssh" in label.lower():
            example = f"ssh -p {lp} user@127.0.0.1"
        forward_rows_tpl.append(
            f"<tr><td>{label}</td><td><code>localhost:{lp}</code></td>"
            f"<td><code>{host}:{rport}</code></td>"
            f"<td><code>{html.escape(example)}</code></td></tr>"
        )
        forward_cards.append(
            f'<div class="map"><span class="pill">localhost:{lp}</span>'
            f'<span class="arrow">→</span><span class="pill dim">{host}:{rport}</span>'
            f'<span class="lbl">{label}</span></div>'
        )
    forwards_table_filled = "\n".join(forward_rows_tpl)
    forwards_maps_filled = "\n".join(forward_cards)

    first_lp = int(forwards[0]["local_port"]) if forwards else 22022
    first_label = html.escape(str((forwards[0].get("label") if forwards else None) or "remote host"))
    ex_http = next((fw for fw in forwards if int(fw.get("port") or 0) in (80, 443, 8080)), None)
    ex_api = next((fw for fw in forwards if int(fw.get("port") or 0) in (8000, 8443, 3000)), None)
    ex_ssh = next((fw for fw in forwards if int(fw.get("port") or 0) == 22), forwards[0] if forwards else None)
    ex_http_host = html.escape(str((ex_http or {}).get("host") or "192.168.130.8"))
    ex_http_rport = int((ex_http or {}).get("port") or 80)
    ex_http_lport = int((ex_http or {}).get("local_port") or 8080)
    ex_api_host = html.escape(str((ex_api or {}).get("host") or "192.168.130.8"))
    ex_api_rport = int((ex_api or {}).get("port") or 8000)
    ex_api_lport = int((ex_api or {}).get("local_port") or 8000)
    ex_ssh_host = html.escape(str((ex_ssh or {}).get("host") or "192.168.130.8"))
    ex_ssh_rport = int((ex_ssh or {}).get("port") or 22)
    ex_ssh_lport = int((ex_ssh or {}).get("local_port") or first_lp)

    ide_ssh_forwards = [
        fw
        for fw in forwards
        if int(fw.get("port") or 0) == 22 or "ssh" in str(fw.get("label") or "").lower()
    ]
    if not ide_ssh_forwards and forwards:
        ide_ssh_forwards = [forwards[0]]

    panes = []
    for locale in LOCALES:
        ide_comment = fmt(locale, "ide_comment_key")
        ide_blocks_loc: list[str] = []
        for idx, fw in enumerate(ide_ssh_forwards):
            lp = int(fw.get("local_port") or 0)
            label_raw = str(fw.get("label") or "").strip() or f"host-{idx + 1}"
            safe_alias = re.sub(r"[^\w.-]+", "-", label_raw.lower()).strip("-")[:40] or f"dev-{idx + 1}"
            host_alias_ide = f"via-tunnel-{safe_alias}"
            ide_blocks_loc.append(
                f"Host {host_alias_ide}\n"
                f"  HostName 127.0.0.1\n"
                f"  Port {lp}\n"
                f"  User yourlogin\n"
                f"  {ide_comment}\n"
                f"  IdentitiesOnly yes"
            )
        if ide_blocks_loc:
            ide_hosts_pre = html.escape("\n\n".join(ide_blocks_loc))
            m = re.search(r"^Host\s+(\S+)", ide_blocks_loc[0], re.M)
            first_ide_alias = html.escape(m.group(1)) if m else "via-tunnel-dev"
        else:
            ide_hosts_pre = html.escape(
                f"Host via-tunnel-dev\n"
                f"  HostName 127.0.0.1\n"
                f"  Port {first_lp}\n"
                f"  User yourlogin\n"
                f"  IdentitiesOnly yes"
            )
            first_ide_alias = "via-tunnel-dev"

        empty_row = f"<tr><td colspan='4'>{fmt(locale, 'forwards_empty_row')}</td></tr>"
        empty_map = f'<p class="muted">{fmt(locale, "forwards_empty_map")}</p>'
        ctx = {
            "username": username,
            "alias": alias,
            "hostname": hostname,
            "port": port,
            "identity": identity,
            "key_name": key_name,
            "has_key": has_key,
            "config": config,
            "forwards_table": forwards_table_filled or empty_row,
            "forwards_maps": forwards_maps_filled or empty_map,
            "first_lp": first_lp,
            "first_label": first_label,
            "first_ide_alias": first_ide_alias,
            "ide_hosts_pre": ide_hosts_pre,
            "ex_http_host": ex_http_host,
            "ex_http_rport": ex_http_rport,
            "ex_http_lport": ex_http_lport,
            "ex_api_host": ex_api_host,
            "ex_api_rport": ex_api_rport,
            "ex_api_lport": ex_api_lport,
            "ex_ssh_host": ex_ssh_host,
            "ex_ssh_rport": ex_ssh_rport,
            "ex_ssh_lport": ex_ssh_lport,
        }
        panes.append(_render_pane(locale, ctx))

    panes_html = "\n".join(panes)
    lang_labels = {loc: get_strings(loc)["lang_label"] for loc in LOCALES}

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SSH Tunnel — {username}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
:root {{
  --bg0: #07111f;
  --bg1: #0c1a2e;
  --card: rgba(18, 38, 63, 0.72);
  --line: rgba(148, 163, 184, 0.18);
  --text: #e8eef7;
  --muted: #94a3b8;
  --accent: #14b8a6;
  --accent2: #38bdf8;
  --warn: #f59e0b;
  --danger: #f43f5e;
  --shadow: 0 16px 48px rgba(0,0,0,.4);
  --radius: 16px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; min-height: 100vh; color: var(--text);
  font-family: Outfit, "Segoe UI", sans-serif;
  background:
    radial-gradient(900px 480px at 12% -8%, rgba(20,184,166,.18), transparent 55%),
    linear-gradient(180deg, var(--bg0), var(--bg1) 50%, #081525);
  line-height: 1.55;
}}
a {{ color: var(--accent2); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code, pre, .mono {{ font-family: "IBM Plex Mono", ui-monospace, monospace; }}
.wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 18px 72px; }}
.lang-bar {{
  display: flex; justify-content: flex-end; align-items: center; gap: 10px;
  margin-bottom: 12px; flex-wrap: wrap;
}}
.lang-bar .lang-label {{ color: var(--muted); font-size: 13px; }}
.lang-switch {{
  display: inline-flex; gap: 4px; padding: 4px;
  border: 1px solid var(--line); border-radius: 999px; background: rgba(2,8,23,.45);
}}
.lang-switch button {{
  appearance: none; border: 0; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600;
  padding: 7px 14px; border-radius: 999px; color: var(--muted); background: transparent;
}}
.lang-switch button:hover {{ color: var(--text); }}
.lang-switch button.active {{
  color: #042f2e; background: linear-gradient(145deg, var(--accent), #0f766e);
}}
.lang-pane[hidden] {{ display: none !important; }}
.topbar {{
  display: flex; justify-content: space-between; gap: 12px; align-items: center;
  margin-bottom: 14px; flex-wrap: wrap;
}}
.brand {{ font-weight: 700; letter-spacing: -0.02em; }}
.brand span {{ color: var(--accent); }}
.hero {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: linear-gradient(145deg, rgba(20,184,166,.1), rgba(15,23,42,.5));
  box-shadow: var(--shadow); padding: 26px 24px 22px; margin-bottom: 16px;
}}
.eyebrow {{
  font-size: 12px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin-bottom: 8px;
}}
.hero h1 {{
  margin: 0 0 10px; font-size: clamp(1.45rem, 3.5vw, 1.9rem);
  letter-spacing: -0.03em; font-weight: 700;
}}
.hero .essence {{ margin: 0; color: var(--muted); font-size: 1.02rem; max-width: 62ch; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.chip {{
  border: 1px solid var(--line); background: rgba(2,8,23,.35);
  border-radius: 999px; padding: 6px 12px; font-size: 12px; color: var(--muted);
}}
.chip strong {{ color: var(--text); font-weight: 600; }}
.main-simple section.quick {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--card); backdrop-filter: blur(10px);
  padding: 22px 22px 8px; margin-bottom: 14px;
}}
.quick h2 {{ margin: 0 0 6px; font-size: 1.25rem; }}
.lead {{ color: var(--muted); margin: 0 0 18px; }}
.quick-list {{ margin: 0; padding: 0 0 12px 0; list-style: none; counter-reset: q; }}
.quick-list > li {{
  counter-increment: q;
  position: relative;
  padding: 14px 0 14px 48px;
  border-top: 1px solid var(--line);
}}
.quick-list > li::before {{
  content: counter(q);
  position: absolute; left: 0; top: 14px;
  width: 32px; height: 32px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(145deg, var(--accent), #0f766e);
  color: #042f2e; font-weight: 700; font-size: 14px;
}}
.quick-list strong {{ display: block; margin-bottom: 4px; font-size: 1.02rem; }}
.quick-list p {{ margin: 0 0 8px; color: var(--muted); font-size: 0.98rem; }}
.quick-list .note {{
  margin-top: 8px; padding: 10px 12px; border-radius: 10px;
  border-left: 3px solid var(--accent); background: rgba(20,184,166,.08);
}}
.ports-h {{ margin: 12px 0 4px; font-size: 0.95rem; color: #dbeafe; }}
pre {{
  margin: 10px 0 0; padding: 12px 14px; overflow: auto;
  border-radius: 10px; border: 1px solid var(--line);
  background: #020617; color: #e2e8f0; font-size: 12.5px; line-height: 1.5;
}}
table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 8px 0 4px; }}
th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; font-size: 11px; letter-spacing: .05em; text-transform: uppercase; }}
.muted {{ color: var(--muted); }}
.details-block {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: rgba(2,8,23,.28); margin-bottom: 16px; overflow: hidden;
}}
.details-block > summary {{
  cursor: pointer; list-style: none; padding: 16px 20px;
  display: flex; flex-direction: column; gap: 4px;
  user-select: none;
}}
.details-block > summary::-webkit-details-marker {{ display: none; }}
.details-block > summary::before {{
  content: "▸ "; color: var(--accent); font-weight: 700;
}}
.details-block[open] > summary::before {{ content: "▾ "; }}
.details-title {{ font-weight: 700; font-size: 1.05rem; }}
.details-hint {{ color: var(--muted); font-size: 13px; padding-left: 1.1em; }}
.details-body {{ padding: 0 12px 16px; border-top: 1px solid var(--line); }}
.details-body section {{
  border: 1px solid var(--line); border-radius: 14px;
  background: var(--card); padding: 20px 18px; margin: 12px 0;
}}
.details-body h2 {{ margin: 0 0 8px; font-size: 1.2rem; }}
.details-body h3 {{ margin: 18px 0 8px; font-size: 1.02rem; color: #dbeafe; }}
.steps {{ counter-reset: step; display: grid; gap: 10px; }}
.step {{
  counter-increment: step;
  display: grid; grid-template-columns: 32px 1fr; gap: 10px;
  padding: 12px; border-radius: 12px; border: 1px solid var(--line);
  background: rgba(2,8,23,.28);
}}
.step::before {{
  content: counter(step); width: 32px; height: 32px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(145deg, var(--accent), #0f766e);
  color: #042f2e; font-weight: 700; font-size: 13px;
}}
.step strong {{ display: block; margin-bottom: 4px; }}
.step p {{ margin: 0; color: var(--muted); font-size: 14px; }}
.callout {{
  border-left: 3px solid var(--accent); background: rgba(20,184,166,.08);
  padding: 11px 12px; border-radius: 0 10px 10px 0; color: var(--muted); margin: 12px 0;
}}
.callout.warn {{ border-left-color: var(--warn); background: rgba(245,158,11,.08); }}
.callout.danger {{ border-left-color: var(--danger); background: rgba(244,63,94,.08); }}
.map {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  padding: 9px 11px; border: 1px solid var(--line); border-radius: 10px;
  background: rgba(2,8,23,.28); margin: 7px 0;
}}
.pill {{
  font-family: "IBM Plex Mono", monospace; font-size: 12px;
  padding: 4px 9px; border-radius: 999px;
  background: rgba(20,184,166,.15); color: #99f6e4; border: 1px solid rgba(20,184,166,.35);
}}
.pill.dim {{ background: rgba(56,189,248,.12); color: #bae6fd; border-color: rgba(56,189,248,.3); }}
.arrow {{ color: var(--muted); }}
.lbl {{ color: var(--muted); font-size: 13px; }}
.files {{ display: grid; gap: 8px; }}
.file {{
  display: grid; grid-template-columns: 28px 1fr; gap: 10px;
  padding: 11px; border-radius: 10px; border: 1px solid var(--line); background: rgba(2,8,23,.25);
}}
.file .ico {{
  width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
  background: rgba(20,184,166,.15); color: var(--accent); font-size: 13px;
}}
.footer {{ margin-top: 22px; color: var(--muted); font-size: 13px; text-align: center; }}
.footer.powered {{ margin-top: 8px; font-size: 12px; }}
.footer.powered a {{ color: var(--accent); font-weight: 600; text-decoration: none; }}
.footer.powered a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="lang-bar">
    <span class="lang-label" id="langLabel">{html.escape(lang_labels["en"])}</span>
    <div class="lang-switch" role="group" aria-label="Language">
      <button type="button" data-lang="en" aria-pressed="false">EN</button>
      <button type="button" data-lang="ru" aria-pressed="false">RU</button>
      <button type="button" data-lang="tr" aria-pressed="false">TR</button>
    </div>
  </div>
{panes_html}
</div>
<script>
(function () {{
  var KEY = "lnxadmin-ssh-pack-lang";
  var LABELS = {json.dumps(lang_labels, ensure_ascii=False)};
  var panes = Array.prototype.slice.call(document.querySelectorAll(".lang-pane"));
  var buttons = Array.prototype.slice.call(document.querySelectorAll(".lang-switch button"));
  var labelEl = document.getElementById("langLabel");

  function detect() {{
    try {{
      var stored = localStorage.getItem(KEY);
      if (stored && LABELS[stored]) return stored;
    }} catch (e) {{}}
    var nav = (navigator.language || "en").toLowerCase();
    if (nav.indexOf("ru") === 0) return "ru";
    if (nav.indexOf("tr") === 0) return "tr";
    return "en";
  }}

  function setLang(lang) {{
    if (!LABELS[lang]) lang = "en";
    panes.forEach(function (p) {{
      var on = p.getAttribute("data-lang") === lang;
      if (on) p.removeAttribute("hidden");
      else p.setAttribute("hidden", "");
    }});
    buttons.forEach(function (b) {{
      var on = b.getAttribute("data-lang") === lang;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    }});
    document.documentElement.lang = lang;
    if (labelEl) labelEl.textContent = LABELS[lang] || "Language";
    try {{ localStorage.setItem(KEY, lang); }} catch (e) {{}}
  }}

  buttons.forEach(function (b) {{
    b.addEventListener("click", function () {{ setLang(b.getAttribute("data-lang")); }});
  }});
  setLang(detect());
}})();
</script>
</body>
</html>
"""


def build_readme_txt(pack: dict[str, Any]) -> str:
    username = str(pack.get("username") or "")
    alias = str(pack.get("host_alias") or f"tunnel-{username}")
    identity = str(pack.get("identity_file") or f"~/.ssh/{username}_rsa4096")
    key_name = str(pack.get("private_key_filename") or _identity_basename(identity, username))
    has_key = bool(pack.get("has_private_key"))
    lines = [
        f"SSH Tunnel pack — {username}",
        "",
        "Short guide (full EN/RU/TR text with details in instructions.html):",
        "",
        "1) Private key → ~/.ssh/  "
        + (f"(file {key_name} from ZIP)" if has_key else f"(your key, e.g. {identity}; not in ZIP)"),
        "2) Append ssh_config to ~/.ssh/config",
        f"3) Keep this running:  ssh -N {alias}",
        "4) Use services as localhost:<local_port> — not as 192.168.x.x",
        "5) Port number = which host/service (see table below)",
        "6) Need a hostname for SSL? Add to hosts:  127.0.0.1  your.name",
        "",
        "Ports:",
    ]
    for fw in pack.get("forwards") or []:
        label = f" ({fw.get('label')})" if fw.get("label") else ""
        lines.append(f"   localhost:{fw.get('local_port')} -> {fw.get('host')}:{fw.get('port')}{label}")
    lines.extend(
        [
            "",
            "Open instructions.html for language switcher + optional detailed guide.",
            "",
            "Powered by iSmartyPRO® — https://www.ismarty.pro",
            "",
        ]
    )
    return "\n".join(lines)
