"""i18n strings for SSH Tunnel client pack instructions.html (en / ru / tr)."""

from __future__ import annotations

from typing import Any

LOCALES = ("en", "ru", "tr")
DEFAULT_LOCALE = "en"

# Each locale: flat string keys. HTML fragments allowed where noted (*_html).
# Placeholders use Python str.format_map / format: {username}, {alias}, etc.

_PACK: dict[str, dict[str, str]] = {
    "en": {
        "lang_label": "Language",
        "toc_jump": "Contents ↓",
        "eyebrow": "Client setup pack",
        "hero_title": "SSH tunnel setup guide",
        "hero_intro": (
            "This pack sets up secure access through jump host "
            "<strong>{hostname}</strong> as account <strong class=\"mono\">{username}</strong>. "
            "The tunnel does not give a shell on the server — only port forwarding to allowed services."
        ),
        "hero_note_with_key": (
            "This pack <strong>includes a private key</strong>. Do not send the ZIP in open chats — "
            "prefer a protected channel."
        ),
        "hero_note_byok": (
            "The private key is <strong>not included</strong> — your public key was used (BYOK). "
            "Set <code>IdentityFile</code> to the path of your private key."
        ),
        "chip_key_in_zip": 'Key in ZIP <strong class="mono">{key_name}</strong>',
        "chip_key_byok": "Key mode <strong>your own key (BYOK)</strong>",
        "toc_title": "Contents",
        "toc_overview": "Overview",
        "toc_contents": "ZIP contents",
        "toc_key": "Key (yours / from ZIP)",
        "toc_ssh_config": "SSH config",
        "toc_start": "Start the tunnel",
        "toc_services": "Access services",
        "toc_localforward": "LocalForward syntax",
        "toc_examples": "Examples",
        "toc_ide": "VS Code / Cursor / IDE",
        "toc_windows": "Windows",
        "toc_unix": "macOS / Linux",
        "toc_trouble": "Troubleshooting",
        "toc_security": "Security",
        "contents_title": "ZIP contents",
        "contents_lead": (
            "Unpack the archive somewhere convenient. Open this file "
            "(<code>instructions.html</code>) in a browser."
        ),
        "file_instructions": "This guide with all sections and examples.",
        "file_ssh_config": 'Host block to paste into <code>~/.ssh/config</code>.',
        "file_key_in_zip": "Private SSH key from the archive. Keep it only on your machine.",
        "file_key_byok_title": "Private key — not in the archive",
        "file_key_byok": (
            "You (or the developer) sent the administrator only a <em>public</em> key. "
            "The private key stays on your PC — it is not and must not be in the ZIP."
        ),
        "file_readme": "Short cheat sheet if HTML does not open.",
        "forwards_empty_row": "No destinations yet — ask the administrator to add them.",
        "forwards_empty_map": "No LocalForward entries in this pack.",
        "service_default": "Service",
        # install key — with private key in ZIP
        "key_with_title": "1. Install the private key",
        "key_with_lead": (
            "The archive contains key file <code>{key_name}</code> — copy it to <code>~/.ssh/</code>."
        ),
        "key_with_step1_title": "Create ~/.ssh if needed",
        "key_with_step2_title": "Copy the key and restrict permissions",
        "key_with_step2_win": (
            "On Windows (OpenSSH): file Properties → Security → access for your account only."
        ),
        "key_with_warn": (
            "Without <code>chmod 600</code> OpenSSH often refuses the key "
            "(<em>WARNING: UNPROTECTED PRIVATE KEY FILE</em>)."
        ),
        "key_with_identity": (
            "Parameter <code>IdentityFile {identity}</code> must point to the key file from the archive. "
            "If you placed the key elsewhere — fix the path."
        ),
        "win_steps_with_key": (
            "mkdir $env:USERPROFILE\\.ssh\n"
            "copy {key_name} $env:USERPROFILE\\.ssh\\{key_name}\n"
            "# permissions: your account only (Properties → Security)\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# paste ssh_config; IdentityFile must point to the key:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\{key_name}\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_with_key": (
            "chmod 700 ~/.ssh\n"
            "cp {key_name} {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "ssh -N {alias}"
        ),
        # BYOK
        "key_byok_title": "1. Your private key (BYOK)",
        "key_byok_lead": (
            "The administrator added <strong>your public key</strong> on the jump host. "
            "The private key is <strong>not</strong> in this ZIP — it should already be on your machine "
            "(typical paths: <code>~/.ssh/id_rsa</code>, <code>~/.ssh/id_ed25519</code>)."
        ),
        "key_byok_callout": (
            "This is the preferred developer flow: you generate a key pair locally → "
            "send only <code>.pub</code> → receive a pack with <code>ssh_config</code> and this guide."
        ),
        "key_byok_step1_title": "Check that the private key is present",
        "key_byok_step1_pre": (
            "ls -la ~/.ssh/\n"
            "# expect a file without .pub suffix, for example:\n"
            "# id_rsa         ← private (never send to anyone)\n"
            "# id_rsa.pub     ← public (this is what the server accepts)"
        ),
        "key_byok_step2_title": "Set the path in IdentityFile",
        "key_byok_step2_p1": "In <code>ssh_config</code> it is currently set to:",
        "key_byok_step2_p2": "If your key is elsewhere — fix the line, for example:",
        "key_byok_step2_pre": (
            "IdentityFile ~/.ssh/id_rsa\n"
            "# or\n"
            "IdentityFile ~/.ssh/id_ed25519\n"
            "# or\n"
            "IdentityFile ~/.ssh/my_work_key"
        ),
        "key_byok_step3_title": "Key permissions",
        "key_byok_warn": (
            "Public and private keys are a pair. If the server has the wrong <code>.pub</code>, "
            "or <code>IdentityFile</code> does not point to the matching private file, you get "
            "<em>Permission denied (publickey)</em>."
        ),
        "key_byok_identity": (
            "Mode <strong>your own key</strong>: <code>IdentityFile {identity}</code> must point to "
            "<em>your</em> existing private key (the one whose public half is already on the server)."
        ),
        "win_steps_byok": (
            "# Private key is already yours — not in the ZIP.\n"
            "# Make sure the file exists, for example:\n"
            "#   C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# paste ssh_config and adjust if needed:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_byok": (
            "# Private key is already yours (not copied from ZIP)\n"
            "ls -la {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "# edit IdentityFile in ~/.ssh/config if needed\n"
            "ssh -N {alias}"
        ),
        "ssh_config_title": "2. Add SSH config",
        "ssh_config_lead": (
            "Open (or create) <code>~/.ssh/config</code> and add the block from <code>ssh_config</code>. "
            "Or paste the fragment below as-is."
        ),
        "ssh_config_step_unix": "Linux / macOS",
        "ssh_config_step_unix_pre": (
            "nano ~/.ssh/config\n"
            "# paste the Host … block, then:\n"
            "chmod 600 ~/.ssh/config"
        ),
        "ssh_config_step_append": "Quick append from the pack file",
        "ssh_config_ready": "Ready block for this user",
        "start_title": "3. Start the tunnel",
        "start_lead": (
            "The tunnel account <strong>does not provide an interactive shell</strong>. "
            "Always use <code>-N</code> (no remote command)."
        ),
        "start_hangs": (
            "The command “hangs” with no prompt — that is normal: the tunnel stays up while the window is open."
        ),
        "start_bg": (
            "Background (Linux/macOS): <code>ssh -fN {alias}</code><br/>"
            "Debug: <code>ssh -N -v {alias}</code> (verbose log)."
        ),
        "start_map": "Forward map",
        "services_title": "4. Connect to services via localhost",
        "services_lead": (
            "After the tunnel starts, services are available on <strong>your computer</strong> as "
            "<code>localhost:&lt;local_port&gt;</code>. Do not connect to internal IPs from the internet."
        ),
        "th_service": "Service",
        "th_local": "Local",
        "th_target": "Target",
        "th_example": "Example",
        "services_warn": (
            "If the local port is busy — change the <em>left</em> number in <code>LocalForward</code> "
            "(e.g. <code>41736</code> → <code>45001</code>) and restart the tunnel."
        ),
        "lf_title": "LocalForward syntax (important)",
        "lf_lead": (
            "OpenSSH format: left — <strong>port on your PC</strong>, right — where to go from the jump host."
        ),
        "lf_pre": (
            "LocalForward <local_port> <host>:<port>\n"
            "\n"
            "# correct — web at http://127.0.0.1:{ex_http_lport}\n"
            "LocalForward {ex_http_lport} {ex_http_host}:{ex_http_rport}\n"
            "\n"
            "# correct — API/panel at http://127.0.0.1:{ex_api_lport}\n"
            "LocalForward {ex_api_lport} {ex_api_host}:{ex_api_rport}\n"
            "\n"
            "# correct — SSH to the target server\n"
            "LocalForward {ex_ssh_lport} {ex_ssh_host}:{ex_ssh_rport}"
        ),
        "lf_danger_title": "Common mistake:",
        "lf_danger_body": (
            "putting an IP on the left or the same “remote” addresses on both sides. "
            "This <em>does not work</em>:"
        ),
        "lf_danger_pre": (
            "# WRONG — left side must be a local PC port, not 192.168.x.x\n"
            "LocalForward {ex_http_host}:{ex_http_rport} {ex_http_host}:{ex_http_rport}\n"
            "LocalForward {ex_api_host}:{ex_api_rport} {ex_api_host}:{ex_api_rport}"
        ),
        "lf_why_title": "Why “localhost:80” does not open",
        "lf_why_1": (
            "In the browser you need <code>http://127.0.0.1:{ex_http_lport}</code> — "
            "the port on the <em>left</em> in <code>LocalForward</code>."
        ),
        "lf_why_2": (
            "Port <strong>80</strong> on your PC is often busy (IIS, Skype, another nginx) or needs admin rights. "
            "That is why a high port (e.g. <strong>{ex_http_lport}</strong>) is used instead of 80."
        ),
        "lf_why_3": (
            "Do not open internal IP <code>http://{ex_http_host}</code> from your home PC — "
            "it is unreachable without the tunnel. Use only <code>127.0.0.1:&lt;local_port&gt;</code>."
        ),
        "lf_why_4": (
            "Do not invent extra <code>LocalForward</code> lines: only destinations from the admin panel "
            "are allowed on the right. Otherwise you get <em>administratively prohibited</em>."
        ),
        "lf_tip": (
            "Prefer the ready block from this ZIP’s <code>ssh_config</code> "
            "(or re-download the pack in Linux Admin) instead of editing ports by hand."
        ),
        "ex_title": "Usage examples",
        "ex_ssh_title": "SSH to an internal host (typical jump use)",
        "ex_ssh_pre": (
            "# 1) in one terminal:\n"
            "ssh -N {alias}\n"
            "\n"
            "# 2) in another — SSH to the service behind the tunnel:\n"
            "ssh -p {first_lp} yourlogin@127.0.0.1\n"
            "# ({first_label})"
        ),
        "ex_scp_title": "SCP / SFTP via the same port",
        "ex_rdp_title": "RDP / web / DB",
        "ex_rdp_pre": (
            "# RDP (if 3389 is forwarded → local port L):\n"
            "# connect to 127.0.0.1:L in Remote Desktop\n"
            "\n"
            "# HTTP/HTTPS:\n"
            "# http://127.0.0.1:L\n"
            "\n"
            "# PostgreSQL / other TCP:\n"
            "# host=127.0.0.1  port=L"
        ),
        "ex_check_title": "Check that the port is listening",
        "ide_title": "VS Code, Cursor and other IDEs (Remote SSH)",
        "ide_lead": (
            "Editors like <strong>VS Code</strong>, <strong>Cursor</strong>, VSCodium, and JetBrains Gateway "
            "can open a folder on a remote Linux host over SSH. Through this tunnel you connect "
            "not to the jump user, but to the <strong>target server</strong> on <code>localhost:&lt;port&gt;</code>."
        ),
        "ide_danger": (
            "<strong>Do not Remote-SSH to the tunnel account</strong> "
            "(<code>{username}</code> / alias <code>{alias}</code>). "
            "It has shell <code>nologin</code> — the IDE will get "
            "“This account is currently not available” / PTY failed. "
            "First start <code>ssh -N</code>, then in the IDE open the "
            "<em>host behind the forward</em> (usually internal SSH port 22)."
        ),
        "ide_step1_title": "Start the tunnel and leave it running",
        "ide_step1_p": (
            "While the tunnel is alive, your PC listens on the local port "
            "(e.g. <code>{first_lp}</code> → {first_label})."
        ),
        "ide_step2_title": "Add an IDE Host in ~/.ssh/config",
        "ide_step2_p": (
            "This is a <em>separate</em> block from the tunnel alias: it points at <code>127.0.0.1</code> "
            "and uses the login/key of the <strong>account on the target server</strong> "
            "(not the jump-tunnel key, if they differ)."
        ),
        "ide_step2_note": "Replace <code>yourlogin</code> and <code>IdentityFile</code> if needed.",
        "ide_comment_key": "# IdentityFile ~/.ssh/id_rsa   # key for the TARGET host account",
        "ide_vscode_p": "Extension <em>Remote - SSH</em> (Microsoft).",
        "ide_cursor_p": "Same Remote SSH (command palette like VS Code).",
        "ide_cursor_note": (
            "Ensure the target host can download the server component "
            "(or use offline install per Cursor/VS Code docs)."
        ),
        "ide_term_title": "Check from the IDE terminal",
        "ide_jb_title": "JetBrains (Gateway / IDEA / PyCharm)",
        "ide_scheme_title": "One diagram",
        "ide_scheme_pre": (
            "Your PC\n"
            "  │\n"
            "  ├─ ssh -N {alias}          ← tunnel (jump, no shell)\n"
            "  │     LocalForward {first_lp} → internal SSH\n"
            "  │\n"
            "  └─ VS Code / Cursor Remote-SSH\n"
            "        Host {first_ide_alias} = 127.0.0.1:{first_lp}\n"
            "        User yourlogin         ← normal user on the target server"
        ),
        "ide_warn": (
            "If the IDE says <em>Could not establish connection</em> — usually "
            "<code>ssh -N {alias}</code> is not running, the local port changed/busy, "
            "or User/key is wrong for the <em>target</em> host (not the jump)."
        ),
        "win_title": "Windows",
        "win_lead": "Built-in OpenSSH (Windows 10/11) or a client like PuTTY/Bitvise works.",
        "win_openssh": "OpenSSH (recommended)",
        "win_path": "Config path",
        "win_path_note": "Usually: <code>C:\\Users\\&lt;User&gt;\\.ssh\\config</code>",
        "unix_title": "macOS / Linux",
        "unix_fingerprint": (
            "The first time SSH asks for host fingerprint <code>{hostname}</code> — "
            "compare with what the admin gave you, then type <code>yes</code>."
        ),
        "trouble_title": "Common problems",
        "tr_nologin_title": "“This account is currently not available” / PTY allocation failed",
        "tr_nologin_body": "Started without <code>-N</code>. Need: <code>ssh -N {alias}</code>.",
        "tr_pubkey_title": "“Permission denied (publickey)”",
        "tr_pubkey_body": (
            "Wrong key, <code>IdentityFile</code> path, or file mode not 600."
            "{byok_extra} Add <code>-v</code> for diagnostics."
        ),
        "tr_pubkey_byok_extra": (
            " In BYOK mode check that the server has the matching .pub for your private key."
        ),
        "tr_bind_title": "“bind: Address already in use”",
        "tr_bind_body": "Local port is busy. Change the left port in <code>LocalForward</code>.",
        "tr_admin_title": "“channel … administratively prohibited”",
        "tr_admin_body": (
            "Forward to a <code>host:port</code> not in allowed destinations, or a typo on the right "
            "(e.g. wrong IP/port). See also <a href=\"#localforward\">LocalForward syntax</a>."
        ),
        "tr_web_title": "Web does not open on localhost:80 / “I added LocalForward myself”",
        "tr_web_body": (
            "Left side of <code>LocalForward</code> must be a PC port (e.g. <code>{ex_http_lport}</code>), not "
            "<code>{ex_http_host}:{ex_http_rport}</code>. In the browser: "
            "<code>http://127.0.0.1:{ex_http_lport}</code> "
            "(and <code>http://127.0.0.1:{ex_api_lport}</code> for the backend). "
            "Details — <a href=\"#localforward\">LocalForward section</a>."
        ),
        "tr_close_title": "Tunnel closes immediately",
        "tr_close_body": (
            "Check network/VPN to <code>{hostname}:{port}</code>, PC clock, "
            "and that the key matches user <code>{username}</code>."
        ),
        "tr_ide_title": "VS Code / Cursor: “Could not establish connection” / nologin",
        "tr_ide_body": (
            "IDE connected to jump user <code>{username}</code> or the tunnel is down. "
            "Need: (1) <code>ssh -N {alias}</code>, (2) Remote-SSH to <code>127.0.0.1:{first_lp}</code> "
            "as the target server login — see <a href=\"#ide\">IDE section</a>."
        ),
        "sec_title": "Security",
        "sec_1": "Treat the private key like a password. Do not post it in Telegram/email unencrypted.",
        "sec_2": "Do not copy the key to other people’s computers.",
        "sec_3": "If compromised — tell the admin immediately: the key will be revoked and replaced.",
        "sec_4": "The tunnel only reaches explicitly allowed <code>host:port</code>, not the whole network.",
        "sec_5": "Close the <code>ssh -N</code> session when done (Ctrl+C).",
        "sec_danger": (
            "If the key may have leaked — treat it as compromised and request a reissue."
        ),
        "footer_gen": "Generated by Linux Admin · user",
        "footer_toc": "to contents",
        "footer_top": "top",
        "readme_open": "1) Open instructions.html in a browser (EN / RU / TR switcher inside).",
        "readme_key": "2) Save private key from ZIP as {identity} (chmod 600). File: {key_name}",
        "readme_byok": (
            "2) Private key is NOT in this ZIP (BYOK — you sent only the public key). "
            "Point IdentityFile to your existing key (default in config: {identity})."
        ),
        "readme_config": "3) Append ssh_config to ~/.ssh/config",
        "readme_start": "4) Start tunnel: ssh -N {alias}",
        "readme_use": "5) Use services via localhost:<LocalForward port>",
        "powered_by": 'Powered by <a href="https://www.ismarty.pro" target="_blank" rel="noopener noreferrer">iSmartyPRO</a>®',
    },
    "ru": {
        "lang_label": "Язык",
        "toc_jump": "К разделам ↓",
        "eyebrow": "Client setup pack",
        "hero_title": "Инструкция по SSH-туннелю",
        "hero_intro": (
            "Этот пакет настраивает безопасный доступ через jump-хост "
            "<strong>{hostname}</strong> под учётной записью <strong class=\"mono\">{username}</strong>. "
            "Туннель не даёт shell на сервере — только проброс портов к разрешённым сервисам."
        ),
        "hero_note_with_key": (
            "В этом пакете <strong>есть приватный ключ</strong>. Не пересылайте ZIP в открытых чатах — "
            "лучше передать архив защищённым каналом."
        ),
        "hero_note_byok": (
            "Приватный ключ <strong>не включён</strong> в пакет — использован ваш публичный ключ (BYOK). "
            "Настройте <code>IdentityFile</code> на путь к своему приватному ключу."
        ),
        "chip_key_in_zip": 'Key in ZIP <strong class="mono">{key_name}</strong>',
        "chip_key_byok": "Key mode <strong>свой ключ (BYOK)</strong>",
        "toc_title": "Содержание",
        "toc_overview": "Обзор",
        "toc_contents": "Содержимое ZIP",
        "toc_key": "Ключ (свой / из ZIP)",
        "toc_ssh_config": "SSH config",
        "toc_start": "Запуск туннеля",
        "toc_services": "Доступ к сервисам",
        "toc_localforward": "Синтаксис LocalForward",
        "toc_examples": "Примеры",
        "toc_ide": "VS Code / Cursor / IDE",
        "toc_windows": "Windows",
        "toc_unix": "macOS / Linux",
        "toc_trouble": "Проблемы",
        "toc_security": "Безопасность",
        "contents_title": "Содержимое ZIP",
        "contents_lead": (
            "Распакуйте архив в удобное место. Откройте этот файл "
            "(<code>instructions.html</code>) в браузере."
        ),
        "file_instructions": "Эта инструкция со всеми разделами и примерами.",
        "file_ssh_config": 'Блок <code>Host</code> для вставки в <code>~/.ssh/config</code>.',
        "file_key_in_zip": "Приватный SSH-ключ из архива. Храните только у себя.",
        "file_key_byok_title": "Приватный ключ — не в архиве",
        "file_key_byok": (
            "Вы (или разработчик) прислали администратору только <em>публичный</em> ключ. "
            "Приватный ключ остаётся у вас на ПК — в ZIP его нет и не должно быть."
        ),
        "file_readme": "Краткая шпаргалка на случай, если HTML не открывается.",
        "forwards_empty_row": "Назначения ещё не заданы — попросите администратора добавить destinations.",
        "forwards_empty_map": "Нет LocalForward в этом пакете.",
        "service_default": "Service",
        "key_with_title": "1. Установка приватного ключа",
        "key_with_lead": (
            "В архиве есть файл ключа <code>{key_name}</code> — скопируйте его в <code>~/.ssh/</code>."
        ),
        "key_with_step1_title": "Создайте каталог ~/.ssh (если его нет)",
        "key_with_step2_title": "Скопируйте ключ и ограничьте права",
        "key_with_step2_win": (
            "На Windows (OpenSSH): свойства файла → безопасность → доступ только вашей учётной записи."
        ),
        "key_with_warn": (
            "Без <code>chmod 600</code> OpenSSH часто отказывается использовать ключ "
            "(<em>WARNING: UNPROTECTED PRIVATE KEY FILE</em>)."
        ),
        "key_with_identity": (
            "Параметр <code>IdentityFile {identity}</code> должен указывать на файл ключа из архива. "
            "Если положили ключ в другое место — поправьте путь."
        ),
        "win_steps_with_key": (
            "mkdir $env:USERPROFILE\\.ssh\n"
            "copy {key_name} $env:USERPROFILE\\.ssh\\{key_name}\n"
            "# права: только ваша учётка (Properties → Security)\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# вставьте содержимое ssh_config; IdentityFile должен указывать на ключ:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\{key_name}\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_with_key": (
            "chmod 700 ~/.ssh\n"
            "cp {key_name} {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "ssh -N {alias}"
        ),
        "key_byok_title": "1. Ваш приватный ключ (BYOK)",
        "key_byok_lead": (
            "Администратор добавил на jump-хост <strong>ваш публичный ключ</strong>. "
            "Приватный ключ <strong>не входит</strong> в этот ZIP — он уже должен быть у вас "
            "(типичные пути: <code>~/.ssh/id_rsa</code>, <code>~/.ssh/id_ed25519</code>)."
        ),
        "key_byok_callout": (
            "Это нормальный и предпочтительный сценарий для разработчиков: "
            "вы генерируете пару ключей у себя → отправляете только <code>.pub</code> → "
            "получаете пакет с <code>ssh_config</code> и инструкцией."
        ),
        "key_byok_step1_title": "Проверьте, что приватный ключ на месте",
        "key_byok_step1_pre": (
            "ls -la ~/.ssh/\n"
            "# ожидайте файл без суффикса .pub, например:\n"
            "# id_rsa         ← приватный (никому не отправлять)\n"
            "# id_rsa.pub     ← публичный (его как раз принимают на сервере)"
        ),
        "key_byok_step2_title": "Укажите путь в IdentityFile",
        "key_byok_step2_p1": "В <code>ssh_config</code> сейчас задано:",
        "key_byok_step2_p2": "Если ваш ключ лежит иначе — поправьте строку, например:",
        "key_byok_step2_pre": (
            "IdentityFile ~/.ssh/id_rsa\n"
            "# или\n"
            "IdentityFile ~/.ssh/id_ed25519\n"
            "# или\n"
            "IdentityFile ~/.ssh/my_work_key"
        ),
        "key_byok_step3_title": "Права на ключ",
        "key_byok_warn": (
            "Публичный и приватный ключ — пара. Если на сервере лежит не тот <code>.pub</code>, "
            "или <code>IdentityFile</code> указывает не на парный приватный файл, будет "
            "<em>Permission denied (publickey)</em>."
        ),
        "key_byok_identity": (
            "Режим <strong>свой ключ</strong>: <code>IdentityFile {identity}</code> должен указывать "
            "на <em>ваш</em> существующий приватный ключ (тот, чья публичная часть уже на сервере)."
        ),
        "win_steps_byok": (
            "# Приватный ключ уже у вас — в ZIP его нет.\n"
            "# Убедитесь, что файл существует, например:\n"
            "#   C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# вставьте ssh_config и при необходимости поправьте:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_byok": (
            "# Приватный ключ уже у вас (не копируется из ZIP)\n"
            "ls -la {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "# при необходимости отредактируйте IdentityFile в ~/.ssh/config\n"
            "ssh -N {alias}"
        ),
        "ssh_config_title": "2. Добавление SSH config",
        "ssh_config_lead": (
            "Откройте (или создайте) файл <code>~/.ssh/config</code> и добавьте блок из <code>ssh_config</code>. "
            "Либо скопируйте фрагмент ниже целиком."
        ),
        "ssh_config_step_unix": "Linux / macOS",
        "ssh_config_step_unix_pre": (
            "nano ~/.ssh/config\n"
            "# вставьте блок Host … затем:\n"
            "chmod 600 ~/.ssh/config"
        ),
        "ssh_config_step_append": "Быстрая склейка из файла пакета",
        "ssh_config_ready": "Готовый блок для этого пользователя",
        "start_title": "3. Запуск туннеля",
        "start_lead": (
            "Учётная запись туннеля <strong>не даёт интерактивный shell</strong>. "
            "Всегда используйте флаг <code>-N</code> (no remote command)."
        ),
        "start_hangs": (
            "Команда «зависает» без приглашения — это нормально: туннель работает, пока окно открыто."
        ),
        "start_bg": (
            "Фоновый запуск (Linux/macOS): <code>ssh -fN {alias}</code><br/>"
            "Проверка: <code>ssh -N -v {alias}</code> (подробный лог)."
        ),
        "start_map": "Карта пробросов",
        "services_title": "4. Подключение к сервисам через localhost",
        "services_lead": (
            "После старта туннеля сервисы доступны на <strong>вашем компьютере</strong> как "
            "<code>localhost:&lt;локальный_порт&gt;</code>. Не подключайтесь напрямую к внутренним IP из интернета."
        ),
        "th_service": "Сервис",
        "th_local": "Локально",
        "th_target": "Куда ведёт",
        "th_example": "Пример",
        "services_warn": (
            "Если локальный порт занят — измените <em>левое</em> число в <code>LocalForward</code> "
            "(например <code>41736</code> → <code>45001</code>) и перезапустите туннель."
        ),
        "lf_title": "Синтаксис LocalForward (важно)",
        "lf_lead": (
            "Формат OpenSSH: слева — <strong>порт на вашем ПК</strong>, справа — куда идти с jump-хоста."
        ),
        "lf_pre": (
            "LocalForward <локальный_порт> <хост>:<порт>\n"
            "\n"
            "# правильно — веб на http://127.0.0.1:{ex_http_lport}\n"
            "LocalForward {ex_http_lport} {ex_http_host}:{ex_http_rport}\n"
            "\n"
            "# правильно — API/панель на http://127.0.0.1:{ex_api_lport}\n"
            "LocalForward {ex_api_lport} {ex_api_host}:{ex_api_rport}\n"
            "\n"
            "# правильно — SSH на целевой сервер\n"
            "LocalForward {ex_ssh_lport} {ex_ssh_host}:{ex_ssh_rport}"
        ),
        "lf_danger_title": "Частая ошибка:",
        "lf_danger_body": (
            "писать IP слева или одинаковые «удалённые» адреса с обеих сторон. "
            "Так <em>не работает</em>:"
        ),
        "lf_danger_pre": (
            "# НЕПРАВИЛЬНО — слева должен быть локальный порт ПК, не 192.168.x.x\n"
            "LocalForward {ex_http_host}:{ex_http_rport} {ex_http_host}:{ex_http_rport}\n"
            "LocalForward {ex_api_host}:{ex_api_rport} {ex_api_host}:{ex_api_rport}"
        ),
        "lf_why_title": "Почему не открывается «localhost:80»",
        "lf_why_1": (
            "В браузере нужен адрес вида <code>http://127.0.0.1:{ex_http_lport}</code> — "
            "тот порт, что <em>слева</em> в <code>LocalForward</code>."
        ),
        "lf_why_2": (
            "Порт <strong>80</strong> на вашем ПК часто занят (IIS, Skype, другой nginx) или требует прав администратора. "
            "Поэтому обычно используют высокий порт (например <strong>{ex_http_lport}</strong>), а не 80."
        ),
        "lf_why_3": (
            "Не открывайте в браузере внутренний IP <code>http://{ex_http_host}</code> с домашнего ПК — "
            "он недоступен без туннеля. Работает только через <code>127.0.0.1:&lt;локальный_порт&gt;</code>."
        ),
        "lf_why_4": (
            "Не дописывайте свои <code>LocalForward</code> «наугад»: справа разрешены только destinations "
            "из панели администратора. Иначе будет <em>administratively prohibited</em>."
        ),
        "lf_tip": (
            "Лучше взять готовый блок из файла <code>ssh_config</code> этого ZIP "
            "(или заново скачать пакет в Linux Admin), чем править порты вручную."
        ),
        "ex_title": "Примеры использования",
        "ex_ssh_title": "SSH на внутренний хост (типичный PTO / server)",
        "ex_ssh_pre": (
            "# 1) в одном терминале:\n"
            "ssh -N {alias}\n"
            "\n"
            "# 2) в другом терминале — SSH на сервис за туннелем:\n"
            "ssh -p {first_lp} yourlogin@127.0.0.1\n"
            "# ({first_label})"
        ),
        "ex_scp_title": "SCP / SFTP через тот же порт",
        "ex_rdp_title": "RDP / веб / БД",
        "ex_rdp_pre": (
            "# RDP (если проброшен 3389 → локальный порт L):\n"
            "# подключайтесь к 127.0.0.1:L в клиенте Remote Desktop\n"
            "\n"
            "# HTTP/HTTPS:\n"
            "# http://127.0.0.1:L\n"
            "\n"
            "# PostgreSQL / другой TCP:\n"
            "# host=127.0.0.1  port=L"
        ),
        "ex_check_title": "Проверка, что порт слушает",
        "ide_title": "VS Code, Cursor и другие IDE (Remote SSH)",
        "ide_lead": (
            "Редакторы вроде <strong>VS Code</strong>, <strong>Cursor</strong>, VSCodium, а также JetBrains Gateway "
            "умеют открывать папку на удалённом Linux-хосте по SSH. Через этот туннель вы подключаетесь "
            "не к jump-пользователю, а к <strong>целевому серверу</strong> на <code>localhost:&lt;порт&gt;</code>."
        ),
        "ide_danger": (
            "<strong>Не подключайте Remote SSH к аккаунту туннеля</strong> "
            "(<code>{username}</code> / alias <code>{alias}</code>). "
            "У него shell <code>nologin</code> — IDE получит "
            "«This account is currently not available» / PTY failed. "
            "Сначала поднимите туннель <code>ssh -N</code>, затем в IDE открывайте "
            "<em>хост за пробросом</em> (обычно порт 22 внутреннего сервера)."
        ),
        "ide_step1_title": "Запустите туннель и оставьте его работать",
        "ide_step1_p": (
            "Пока туннель жив, на ПК слушает локальный порт "
            "(например <code>{first_lp}</code> → {first_label})."
        ),
        "ide_step2_title": "Добавьте Host для IDE в ~/.ssh/config",
        "ide_step2_p": (
            "Это <em>отдельный</em> блок от tunnel-alias: он смотрит на <code>127.0.0.1</code> "
            "и использует логин/ключ <strong>учётной записи на целевом сервере</strong> "
            "(не ключ jump-туннеля, если это разные ключи)."
        ),
        "ide_step2_note": "Замените <code>yourlogin</code> и при необходимости <code>IdentityFile</code>.",
        "ide_comment_key": "# IdentityFile ~/.ssh/id_rsa   # ключ УЧЁТКИ на целевом сервере",
        "ide_vscode_p": "Расширение <em>Remote - SSH</em> (Microsoft).",
        "ide_cursor_p": "Тот же Remote SSH (командная палитра как в VS Code).",
        "ide_cursor_note": (
            "Убедитесь, что на целевом хосте есть исходящий доступ для скачивания server-компонента "
            "(или офлайн-установка по документации Cursor/VS Code)."
        ),
        "ide_term_title": "Проверка из терминала IDE",
        "ide_jb_title": "JetBrains (Gateway / IDEA / PyCharm)",
        "ide_scheme_title": "Одной схемой",
        "ide_scheme_pre": (
            "Ваш ПК\n"
            "  │\n"
            "  ├─ ssh -N {alias}          ← туннель (jump, без shell)\n"
            "  │     LocalForward {first_lp} → внутренний SSH\n"
            "  │\n"
            "  └─ VS Code / Cursor Remote-SSH\n"
            "        Host {first_ide_alias} = 127.0.0.1:{first_lp}\n"
            "        User yourlogin         ← обычный пользователь целевого сервера"
        ),
        "ide_warn": (
            "Если IDE пишет <em>Could not establish connection</em> — чаще всего не запущен "
            "<code>ssh -N {alias}</code>, занят/изменён локальный порт, или неверный User/ключ "
            "для <em>целевого</em> хоста (не для jump)."
        ),
        "win_title": "Windows",
        "win_lead": "Подойдёт встроенный OpenSSH (Windows 10/11) или клиент вроде PuTTY/Bitvise.",
        "win_openssh": "OpenSSH (рекомендуется)",
        "win_path": "Путь к config",
        "win_path_note": "Обычно: <code>C:\\Users\\&lt;User&gt;\\.ssh\\config</code>",
        "unix_title": "macOS / Linux",
        "unix_fingerprint": (
            "Первый раз SSH спросит fingerprint хоста <code>{hostname}</code> — "
            "сравните с тем, что дал администратор, затем введите <code>yes</code>."
        ),
        "trouble_title": "Типичные проблемы",
        "tr_nologin_title": "«This account is currently not available» / PTY allocation failed",
        "tr_nologin_body": "Запустили без <code>-N</code>. Нужно: <code>ssh -N {alias}</code>.",
        "tr_pubkey_title": "«Permission denied (publickey)»",
        "tr_pubkey_body": (
            "Неверный ключ, путь в <code>IdentityFile</code>, или права на файл не 600."
            "{byok_extra} Добавьте <code>-v</code> для диагностики."
        ),
        "tr_pubkey_byok_extra": (
            " В режиме своего ключа проверьте, что на сервере добавлен именно парный .pub к вашему приватному файлу."
        ),
        "tr_bind_title": "«bind: Address already in use»",
        "tr_bind_body": "Локальный порт занят. Смените левый порт в <code>LocalForward</code>.",
        "tr_admin_title": "«channel … administratively prohibited»",
        "tr_admin_body": (
            "Проброс на <code>host:port</code>, которого нет в разрешённых destinations, либо опечатка в IP/порту справа. "
            "См. также <a href=\"#localforward\">синтаксис LocalForward</a>."
        ),
        "tr_web_title": "Веб не открывается на localhost:80 / «сам дописал LocalForward»",
        "tr_web_body": (
            "Слева в <code>LocalForward</code> должен быть порт на ПК (например <code>{ex_http_lport}</code>), не "
            "<code>{ex_http_host}:{ex_http_rport}</code>. В браузере: "
            "<code>http://127.0.0.1:{ex_http_lport}</code> "
            "(и <code>http://127.0.0.1:{ex_api_lport}</code> для бэкенда). "
            "Подробнее — <a href=\"#localforward\">раздел LocalForward</a>."
        ),
        "tr_close_title": "Туннель сразу закрывается",
        "tr_close_body": (
            "Проверьте сеть/VPN до <code>{hostname}:{port}</code>, время на ПК, "
            "и что ключ соответствует пользователю <code>{username}</code>."
        ),
        "tr_ide_title": "VS Code / Cursor: «Could not establish connection» / nologin",
        "tr_ide_body": (
            "IDE подключили к jump-пользователю <code>{username}</code> или туннель не запущен. "
            "Нужно: (1) <code>ssh -N {alias}</code>, (2) Remote-SSH на <code>127.0.0.1:{first_lp}</code> "
            "под логином целевого сервера — см. <a href=\"#ide\">раздел IDE</a>."
        ),
        "sec_title": "Безопасность",
        "sec_1": "Приватный ключ — как пароль. Не публикуйте его в Telegram/почте без шифрования.",
        "sec_2": "Не копируйте ключ на чужие компьютеры.",
        "sec_3": "При компрометации — сразу сообщите администратору: ключ отзовут и выдадут новый.",
        "sec_4": "Туннель даёт доступ только к явно разрешённым <code>host:port</code>, не ко всей сети.",
        "sec_5": "Закрывайте сессию <code>ssh -N</code>, когда работа закончена (Ctrl+C).",
        "sec_danger": (
            "Если ключ мог попасть к посторонним — считайте его скомпрометированным и запросите перевыпуск."
        ),
        "footer_gen": "Generated by Linux Admin · user",
        "footer_toc": "к содержанию",
        "footer_top": "наверх",
        "readme_open": "1) Open instructions.html in a browser (переключатель EN / RU / TR внутри).",
        "readme_key": "2) Save private key from ZIP as {identity} (chmod 600). File: {key_name}",
        "readme_byok": (
            "2) Private key is NOT in this ZIP (BYOK — you sent only the public key). "
            "Point IdentityFile to your existing key (default in config: {identity})."
        ),
        "readme_config": "3) Append ssh_config to ~/.ssh/config",
        "readme_start": "4) Start tunnel: ssh -N {alias}",
        "readme_use": "5) Use services via localhost:<LocalForward port>",
        "powered_by": 'Powered by <a href="https://www.ismarty.pro" target="_blank" rel="noopener noreferrer">iSmartyPRO</a>®',
    },
    "tr": {
        "lang_label": "Dil",
        "toc_jump": "İçindekiler ↓",
        "eyebrow": "Client setup pack",
        "hero_title": "SSH tüneli kurulum rehberi",
        "hero_intro": (
            "Bu paket, jump sunucusu <strong>{hostname}</strong> üzerinden "
            "<strong class=\"mono\">{username}</strong> hesabıyla güvenli erişim oturur. "
            "Tünel sunucuda shell vermez — yalnızca izinli servislere port yönlendirme sağlar."
        ),
        "hero_note_with_key": (
            "Bu pakette <strong>özel anahtar vardır</strong>. ZIP’i açık sohbetlerde göndermeyin — "
            "korumalı bir kanal kullanın."
        ),
        "hero_note_byok": (
            "Özel anahtar pakete <strong>dahil değildir</strong> — genel anahtarınız kullanıldı (BYOK). "
            "<code>IdentityFile</code> yolunu kendi özel anahtarınıza ayarlayın."
        ),
        "chip_key_in_zip": 'Key in ZIP <strong class="mono">{key_name}</strong>',
        "chip_key_byok": "Key mode <strong>kendi anahtarınız (BYOK)</strong>",
        "toc_title": "İçindekiler",
        "toc_overview": "Genel bakış",
        "toc_contents": "ZIP içeriği",
        "toc_key": "Anahtar (sizin / ZIP’ten)",
        "toc_ssh_config": "SSH config",
        "toc_start": "Tüneli başlatma",
        "toc_services": "Servislere erişim",
        "toc_localforward": "LocalForward sözdizimi",
        "toc_examples": "Örnekler",
        "toc_ide": "VS Code / Cursor / IDE",
        "toc_windows": "Windows",
        "toc_unix": "macOS / Linux",
        "toc_trouble": "Sorun giderme",
        "toc_security": "Güvenlik",
        "contents_title": "ZIP içeriği",
        "contents_lead": (
            "Arşivi uygun bir yere çıkarın. Bu dosyayı "
            "(<code>instructions.html</code>) tarayıcıda açın."
        ),
        "file_instructions": "Tüm bölümler ve örneklerle bu rehber.",
        "file_ssh_config": '<code>~/.ssh/config</code> içine yapıştırılacak <code>Host</code> bloğu.',
        "file_key_in_zip": "Arşivdeki özel SSH anahtarı. Yalnızca sizde kalsın.",
        "file_key_byok_title": "Özel anahtar — arşivde yok",
        "file_key_byok": (
            "Yöneticiye yalnızca <em>genel</em> anahtar gönderildi. "
            "Özel anahtar PC’nizde kalır — ZIP’te yoktur ve olmamalıdır."
        ),
        "file_readme": "HTML açılmazsa kısa özet.",
        "forwards_empty_row": "Henüz hedef yok — yöneticiden destination eklemesini isteyin.",
        "forwards_empty_map": "Bu pakette LocalForward yok.",
        "service_default": "Servis",
        "key_with_title": "1. Özel anahtarı kurma",
        "key_with_lead": (
            "Arşivde <code>{key_name}</code> anahtar dosyası var — <code>~/.ssh/</code> altına kopyalayın."
        ),
        "key_with_step1_title": "~/.ssh dizinini oluşturun (yoksa)",
        "key_with_step2_title": "Anahtarı kopyalayın ve izinleri kısıtlayın",
        "key_with_step2_win": (
            "Windows (OpenSSH): dosya Özellikleri → Güvenlik → yalnızca sizin hesabınız."
        ),
        "key_with_warn": (
            "<code>chmod 600</code> olmadan OpenSSH çoğu zaman anahtarı reddeder "
            "(<em>WARNING: UNPROTECTED PRIVATE KEY FILE</em>)."
        ),
        "key_with_identity": (
            "<code>IdentityFile {identity}</code> parametresi arşivdeki anahtar dosyasını göstermelidir. "
            "Başka yere koyduysanız yolu düzeltin."
        ),
        "win_steps_with_key": (
            "mkdir $env:USERPROFILE\\.ssh\n"
            "copy {key_name} $env:USERPROFILE\\.ssh\\{key_name}\n"
            "# izinler: yalnızca sizin hesabınız (Properties → Security)\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# ssh_config yapıştırın; IdentityFile anahtarı göstermeli:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\{key_name}\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_with_key": (
            "chmod 700 ~/.ssh\n"
            "cp {key_name} {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "ssh -N {alias}"
        ),
        "key_byok_title": "1. Sizin özel anahtarınız (BYOK)",
        "key_byok_lead": (
            "Yönetici jump sunucusuna <strong>sizin genel anahtarınızı</strong> ekledi. "
            "Özel anahtar bu ZIP’te <strong>yoktur</strong> — bilgisayarınızda olmalı "
            "(tipik yollar: <code>~/.ssh/id_rsa</code>, <code>~/.ssh/id_ed25519</code>)."
        ),
        "key_byok_callout": (
            "Geliştiriciler için tercih edilen akış: anahtar çiftini yerelde üretin → "
            "yalnızca <code>.pub</code> gönderin → <code>ssh_config</code> ve rehberi alın."
        ),
        "key_byok_step1_title": "Özel anahtarın yerinde olduğunu kontrol edin",
        "key_byok_step1_pre": (
            "ls -la ~/.ssh/\n"
            "# .pub soneki olmayan dosyayı bekleyin, örneğin:\n"
            "# id_rsa         ← özel (kimseye göndermeyin)\n"
            "# id_rsa.pub     ← genel (sunucuya verilen)"
        ),
        "key_byok_step2_title": "IdentityFile yolunu ayarlayın",
        "key_byok_step2_p1": "<code>ssh_config</code> içinde şu an:",
        "key_byok_step2_p2": "Anahtarınız başka yerdeyse satırı düzeltin, örneğin:",
        "key_byok_step2_pre": (
            "IdentityFile ~/.ssh/id_rsa\n"
            "# veya\n"
            "IdentityFile ~/.ssh/id_ed25519\n"
            "# veya\n"
            "IdentityFile ~/.ssh/my_work_key"
        ),
        "key_byok_step3_title": "Anahtar izinleri",
        "key_byok_warn": (
            "Genel ve özel anahtar bir çifttir. Sunucuda yanlış <code>.pub</code> varsa "
            "veya <code>IdentityFile</code> eşleşen özel dosyayı göstermiyorsa "
            "<em>Permission denied (publickey)</em> alırsınız."
        ),
        "key_byok_identity": (
            "<strong>Kendi anahtar</strong> modu: <code>IdentityFile {identity}</code> "
            "sunucuda zaten bulunan genel yarısına ait <em>sizin</em> özel anahtarınızı göstermelidir."
        ),
        "win_steps_byok": (
            "# Özel anahtar zaten sizde — ZIP’te yok.\n"
            "# Dosyanın var olduğundan emin olun, örneğin:\n"
            "#   C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "notepad $env:USERPROFILE\\.ssh\\config\n"
            "# ssh_config yapıştırın, gerekirse düzeltin:\n"
            "# IdentityFile C:\\Users\\YOU\\.ssh\\id_rsa\n"
            "\n"
            "ssh -N {alias}"
        ),
        "unix_steps_byok": (
            "# Özel anahtar zaten sizde (ZIP’ten kopyalanmaz)\n"
            "ls -la {identity}\n"
            "chmod 600 {identity}\n"
            "cat ssh_config >> ~/.ssh/config\n"
            "chmod 600 ~/.ssh/config\n"
            "# gerekirse ~/.ssh/config içinde IdentityFile düzenleyin\n"
            "ssh -N {alias}"
        ),
        "ssh_config_title": "2. SSH config ekleme",
        "ssh_config_lead": (
            "<code>~/.ssh/config</code> dosyasını açın (veya oluşturun) ve <code>ssh_config</code> bloğunu ekleyin. "
            "Ya da aşağıdaki parçayı olduğu gibi yapıştırın."
        ),
        "ssh_config_step_unix": "Linux / macOS",
        "ssh_config_step_unix_pre": (
            "nano ~/.ssh/config\n"
            "# Host … bloğunu yapıştırın, sonra:\n"
            "chmod 600 ~/.ssh/config"
        ),
        "ssh_config_step_append": "Paket dosyasından hızlı ekleme",
        "ssh_config_ready": "Bu kullanıcı için hazır blok",
        "start_title": "3. Tüneli başlatma",
        "start_lead": (
            "Tünel hesabı <strong>etkileşimli shell vermez</strong>. "
            "Her zaman <code>-N</code> kullanın (uzak komut yok)."
        ),
        "start_hangs": (
            "Komut istem olmadan “asılı” kalır — bu normaldir: pencere açıkken tünel çalışır."
        ),
        "start_bg": (
            "Arka plan (Linux/macOS): <code>ssh -fN {alias}</code><br/>"
            "Tanılama: <code>ssh -N -v {alias}</code> (ayrıntılı log)."
        ),
        "start_map": "Yönlendirme haritası",
        "services_title": "4. Servislere localhost üzerinden bağlanma",
        "services_lead": (
            "Tünel başladıktan sonra servisler <strong>bilgisayarınızda</strong> "
            "<code>localhost:&lt;yerel_port&gt;</code> olarak erişilir. "
            "İnternetten iç IP’lere doğrudan bağlanmayın."
        ),
        "th_service": "Servis",
        "th_local": "Yerel",
        "th_target": "Hedef",
        "th_example": "Örnek",
        "services_warn": (
            "Yerel port meşgulse <code>LocalForward</code> içindeki <em>sol</em> sayıyı değiştirin "
            "(ör. <code>41736</code> → <code>45001</code>) ve tüneli yeniden başlatın."
        ),
        "lf_title": "LocalForward sözdizimi (önemli)",
        "lf_lead": (
            "OpenSSH biçimi: solda — <strong>PC’nizdeki port</strong>, sağda — jump sunucusundan nereye gidileceği."
        ),
        "lf_pre": (
            "LocalForward <yerel_port> <host>:<port>\n"
            "\n"
            "# doğru — web: http://127.0.0.1:{ex_http_lport}\n"
            "LocalForward {ex_http_lport} {ex_http_host}:{ex_http_rport}\n"
            "\n"
            "# doğru — API/panel: http://127.0.0.1:{ex_api_lport}\n"
            "LocalForward {ex_api_lport} {ex_api_host}:{ex_api_rport}\n"
            "\n"
            "# doğru — hedef sunucuya SSH\n"
            "LocalForward {ex_ssh_lport} {ex_ssh_host}:{ex_ssh_rport}"
        ),
        "lf_danger_title": "Sık hata:",
        "lf_danger_body": (
            "solda IP yazmak veya her iki tarafta aynı “uzak” adresleri kullanmak. "
            "Bu <em>çalışmaz</em>:"
        ),
        "lf_danger_pre": (
            "# YANLIŞ — solda yerel PC portu olmalı, 192.168.x.x değil\n"
            "LocalForward {ex_http_host}:{ex_http_rport} {ex_http_host}:{ex_http_rport}\n"
            "LocalForward {ex_api_host}:{ex_api_rport} {ex_api_host}:{ex_api_rport}"
        ),
        "lf_why_title": "Neden “localhost:80” açılmıyor",
        "lf_why_1": (
            "Tarayıcıda <code>http://127.0.0.1:{ex_http_lport}</code> gerekir — "
            "<code>LocalForward</code> içindeki <em>sol</em> port."
        ),
        "lf_why_2": (
            "PC’nizde <strong>80</strong> portu sık meşguldür (IIS, Skype, başka nginx) veya yönetici ister. "
            "Bu yüzden genellikle yüksek port (ör. <strong>{ex_http_lport}</strong>) kullanılır."
        ),
        "lf_why_3": (
            "Ev PC’sinden iç IP <code>http://{ex_http_host}</code> açmayın — "
            "tünelsiz erişilemez. Yalnızca <code>127.0.0.1:&lt;yerel_port&gt;</code>."
        ),
        "lf_why_4": (
            "Kendi <code>LocalForward</code> satırlarınızı uydurmayın: sağda yalnızca yönetici panelindeki "
            "destination’lar izinlidir. Aksi halde <em>administratively prohibited</em>."
        ),
        "lf_tip": (
            "Portları elle düzenlemek yerine bu ZIP’teki hazır <code>ssh_config</code> bloğunu "
            "(veya Linux Admin’den yeniden indirilen paketi) kullanın."
        ),
        "ex_title": "Kullanım örnekleri",
        "ex_ssh_title": "İç host’a SSH (tipik jump kullanımı)",
        "ex_ssh_pre": (
            "# 1) bir terminalde:\n"
            "ssh -N {alias}\n"
            "\n"
            "# 2) diğerinde — tünel arkasındaki servise SSH:\n"
            "ssh -p {first_lp} yourlogin@127.0.0.1\n"
            "# ({first_label})"
        ),
        "ex_scp_title": "Aynı port üzerinden SCP / SFTP",
        "ex_rdp_title": "RDP / web / DB",
        "ex_rdp_pre": (
            "# RDP (3389 → yerel port L yönlendirildiyse):\n"
            "# Remote Desktop’ta 127.0.0.1:L\n"
            "\n"
            "# HTTP/HTTPS:\n"
            "# http://127.0.0.1:L\n"
            "\n"
            "# PostgreSQL / diğer TCP:\n"
            "# host=127.0.0.1  port=L"
        ),
        "ex_check_title": "Portun dinlediğini kontrol edin",
        "ide_title": "VS Code, Cursor ve diğer IDE’ler (Remote SSH)",
        "ide_lead": (
            "<strong>VS Code</strong>, <strong>Cursor</strong>, VSCodium ve JetBrains Gateway gibi araçlar "
            "uzak Linux host’ta klasör açabilir. Bu tünelle jump kullanıcısına değil, "
            "<code>localhost:&lt;port&gt;</code> üzerindeki <strong>hedef sunucuya</strong> bağlanırsınız."
        ),
        "ide_danger": (
            "<strong>Remote SSH’ı tünel hesabına bağlamayın</strong> "
            "(<code>{username}</code> / alias <code>{alias}</code>). "
            "Shell <code>nologin</code> — IDE "
            "“This account is currently not available” / PTY failed alır. "
            "Önce <code>ssh -N</code> başlatın, sonra IDE’de "
            "<em>yönlendirmenin arkasındaki host</em>u açın (genelde iç SSH 22)."
        ),
        "ide_step1_title": "Tüneli başlatın ve açık bırakın",
        "ide_step1_p": (
            "Tünel canlıyken PC yerel portu dinler "
            "(ör. <code>{first_lp}</code> → {first_label})."
        ),
        "ide_step2_title": "~/.ssh/config içine IDE Host ekleyin",
        "ide_step2_p": (
            "Bu, tünel alias’ından <em>ayrı</em> bir bloktur: <code>127.0.0.1</code>’e bakar "
            "ve <strong>hedef sunucu hesabının</strong> kullanıcı/anahtarını kullanır "
            "(farklıysa jump tünel anahtarı değil)."
        ),
        "ide_step2_note": "<code>yourlogin</code> ve gerekirse <code>IdentityFile</code> değiştirin.",
        "ide_comment_key": "# IdentityFile ~/.ssh/id_rsa   # HEDEF sunucu hesabı anahtarı",
        "ide_vscode_p": "<em>Remote - SSH</em> eklentisi (Microsoft).",
        "ide_cursor_p": "Aynı Remote SSH (VS Code gibi komut paleti).",
        "ide_cursor_note": (
            "Hedef host’un server bileşenini indirebildiğinden emin olun "
            "(veya Cursor/VS Code belgelerine göre çevrimdışı kurulum)."
        ),
        "ide_term_title": "IDE terminalinden kontrol",
        "ide_jb_title": "JetBrains (Gateway / IDEA / PyCharm)",
        "ide_scheme_title": "Tek şema",
        "ide_scheme_pre": (
            "PC’niz\n"
            "  │\n"
            "  ├─ ssh -N {alias}          ← tünel (jump, shell yok)\n"
            "  │     LocalForward {first_lp} → iç SSH\n"
            "  │\n"
            "  └─ VS Code / Cursor Remote-SSH\n"
            "        Host {first_ide_alias} = 127.0.0.1:{first_lp}\n"
            "        User yourlogin         ← hedef sunucudaki normal kullanıcı"
        ),
        "ide_warn": (
            "IDE <em>Could not establish connection</em> diyorsa — çoğu zaman "
            "<code>ssh -N {alias}</code> çalışmıyor, yerel port değişmiş/meşgul "
            "veya User/anahtar <em>hedef</em> host için yanlış (jump için değil)."
        ),
        "win_title": "Windows",
        "win_lead": "Yerleşik OpenSSH (Windows 10/11) veya PuTTY/Bitvise gibi istemci uygundur.",
        "win_openssh": "OpenSSH (önerilir)",
        "win_path": "Config yolu",
        "win_path_note": "Genellikle: <code>C:\\Users\\&lt;User&gt;\\.ssh\\config</code>",
        "unix_title": "macOS / Linux",
        "unix_fingerprint": (
            "İlk seferde SSH, <code>{hostname}</code> host parmak izini sorar — "
            "yöneticinin verdiğiyle karşılaştırıp <code>yes</code> yazın."
        ),
        "trouble_title": "Sık sorunlar",
        "tr_nologin_title": "“This account is currently not available” / PTY allocation failed",
        "tr_nologin_body": "<code>-N</code> olmadan başlatıldı. Gerekli: <code>ssh -N {alias}</code>.",
        "tr_pubkey_title": "“Permission denied (publickey)”",
        "tr_pubkey_body": (
            "Yanlış anahtar, <code>IdentityFile</code> yolu veya dosya izni 600 değil."
            "{byok_extra} Tanılama için <code>-v</code> ekleyin."
        ),
        "tr_pubkey_byok_extra": (
            " BYOK modunda sunucudaki .pub’un özel anahtarınızla eşleştiğini kontrol edin."
        ),
        "tr_bind_title": "“bind: Address already in use”",
        "tr_bind_body": "Yerel port meşgul. <code>LocalForward</code> sol portunu değiştirin.",
        "tr_admin_title": "“channel … administratively prohibited”",
        "tr_admin_body": (
            "İzinli destination listesinde olmayan <code>host:port</code> veya sağ tarafta yazım hatası. "
            "Ayrıca <a href=\"#localforward\">LocalForward sözdizimine</a> bakın."
        ),
        "tr_web_title": "localhost:80’de web açılmıyor / “LocalForward’ı kendim ekledim”",
        "tr_web_body": (
            "<code>LocalForward</code> solunda PC portu olmalı (ör. <code>{ex_http_lport}</code>), "
            "<code>{ex_http_host}:{ex_http_rport}</code> değil. Tarayıcıda: "
            "<code>http://127.0.0.1:{ex_http_lport}</code> "
            "(backend için <code>http://127.0.0.1:{ex_api_lport}</code>). "
            "Ayrıntılar — <a href=\"#localforward\">LocalForward bölümü</a>."
        ),
        "tr_close_title": "Tünel hemen kapanıyor",
        "tr_close_body": (
            "<code>{hostname}:{port}</code> ağı/VPN’i, PC saatini "
            "ve anahtarın <code>{username}</code> ile eşleştiğini kontrol edin."
        ),
        "tr_ide_title": "VS Code / Cursor: “Could not establish connection” / nologin",
        "tr_ide_body": (
            "IDE jump kullanıcısı <code>{username}</code>’a bağlandı veya tünel kapalı. "
            "Gerekli: (1) <code>ssh -N {alias}</code>, (2) hedef sunucu hesabıyla "
            "<code>127.0.0.1:{first_lp}</code> Remote-SSH — <a href=\"#ide\">IDE bölümü</a>."
        ),
        "sec_title": "Güvenlik",
        "sec_1": "Özel anahtar şifre gibidir. Telegram/e-postada şifresiz paylaşmayın.",
        "sec_2": "Anahtarı başkasının bilgisayarına kopyalamayın.",
        "sec_3": "Sızdıysa hemen yöneticiye bildirin: anahtar iptal edilir ve yenisi verilir.",
        "sec_4": "Tünel yalnızca açıkça izinli <code>host:port</code>’lara gider, tüm ağa değil.",
        "sec_5": "İş bitince <code>ssh -N</code> oturumunu kapatın (Ctrl+C).",
        "sec_danger": (
            "Anahtar başkasına geçmiş olabilirse — ele geçirilmiş sayın ve yeniden talep edin."
        ),
        "footer_gen": "Generated by Linux Admin · user",
        "footer_toc": "içindekilere",
        "footer_top": "üste",
        "readme_open": "1) Open instructions.html in a browser (EN / RU / TR switcher inside).",
        "readme_key": "2) Save private key from ZIP as {identity} (chmod 600). File: {key_name}",
        "readme_byok": (
            "2) Private key is NOT in this ZIP (BYOK — you sent only the public key). "
            "Point IdentityFile to your existing key (default in config: {identity})."
        ),
        "readme_config": "3) Append ssh_config to ~/.ssh/config",
        "readme_start": "4) Start tunnel: ssh -N {alias}",
        "readme_use": "5) Use services via localhost:<LocalForward port>",
        "powered_by": 'Powered by <a href="https://www.ismarty.pro" target="_blank" rel="noopener noreferrer">iSmartyPRO</a>®',
    },
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_locale(lang: str | None) -> str:
    code = (lang or "").strip().lower().replace("_", "-")
    if code.startswith("ru"):
        return "ru"
    if code.startswith("tr"):
        return "tr"
    if code.startswith("en"):
        return "en"
    return DEFAULT_LOCALE


def get_strings(locale: str) -> dict[str, str]:
    loc = normalize_locale(locale)
    return _PACK.get(loc) or _PACK[DEFAULT_LOCALE]


def fmt(locale: str, key: str, **kwargs: Any) -> str:
    raw = get_strings(locale).get(key, _PACK[DEFAULT_LOCALE].get(key, key))
    if not kwargs:
        return raw
    return raw.format_map(_SafeDict(**{k: str(v) for k, v in kwargs.items()}))

# Short quick-start copy overlays longer defaults (instructions.html short-first UX).
_QUICK_OVERLAY: dict[str, dict[str, str]] = {'en': {'hero_title': 'SSH tunnel — short guide', 'hero_intro': 'The tunnel maps ports on <strong>your PC</strong> (<code>localhost</code>) to internal services. There are no “remote IPs” to connect to — only <code>localhost</code>; the <strong>port number</strong> chooses the host and service.', 'quick_title': 'Quick start', 'quick_enough': 'This is enough for daily work. Details are below if you need them.', 'quick_s1_title': 'Put the private key in the .ssh folder', 'quick_s1_zip': 'Copy <code>{key_name}</code> from this ZIP to <code>~/.ssh/</code> (Windows: <code>%USERPROFILE%\\.ssh\\</code>) and set permissions to your account only (<code>chmod 600</code> on Linux/macOS).', 'quick_s1_byok': 'Use your existing private key (path in config: <code>{identity}</code>). It is <strong>not</strong> in the ZIP — you already sent only the public key.', 'quick_s2_title': 'Add this block to your SSH config', 'quick_s2_body': 'Open or create <code>~/.ssh/config</code> (Windows: <code>%USERPROFILE%\\.ssh\\config</code>) and paste the block below (or append the <code>ssh_config</code> file from the ZIP).', 'quick_s3_title': 'Connect and leave the window open', 'quick_s3_body': 'Run in PowerShell / Terminal:', 'quick_s3_note': 'The command “hangs” with no prompt — that is normal. Keep the window open while you work. Close with Ctrl+C when done.', 'quick_s4_title': 'Use services as localhost + port', 'quick_s4_body': 'While the tunnel is up, the remote machine is available as <code>localhost</code>. Instead of the usual port (e.g. RDP <code>3389</code>), connect to the <strong>local</strong> port from the table. Do not open internal addresses like <code>192.168.x.x</code> from your PC — they are reached only through these localhost ports.', 'quick_s5_title': 'Port = host + service', 'quick_s5_body': 'Each local port forwards to a specific host:service. Pick the row you need:', 'quick_s6_title': 'Need a hostname (e.g. for SSL)?', 'quick_s6_body': 'If an app expects a name, not an IP, add a line to the hosts file pointing that name to <code>127.0.0.1</code>, then open <code>https://that-name:&lt;local_port&gt;</code> (or the port your app uses).', 'quick_hosts_win': 'Windows: edit <code>C:\\Windows\\System32\\drivers\\etc\\hosts</code> as Administrator', 'quick_hosts_unix': 'Linux / macOS: edit <code>/etc/hosts</code>', 'quick_hosts_ex': '127.0.0.1   app.internal.example', 'ports_title': 'Your ports', 'details_summary': 'Detailed guide (optional)', 'details_hint': 'ZIP contents, LocalForward syntax, IDE (VS Code / Cursor), Windows/macOS notes, troubleshooting.', 'toc_jump': 'Quick start ↓'}, 'ru': {'hero_title': 'SSH-туннель — кратко', 'hero_intro': 'Туннель пробрасывает порты с <strong>вашего ПК</strong> (<code>localhost</code>) на внутренние сервисы. Отдельных «удалённых IP» для подключения нет — есть только <code>localhost</code>; <strong>номер порта</strong> выбирает хост и службу.', 'quick_title': 'Быстрый старт', 'quick_enough': 'Этого достаточно для обычной работы. Подробности — ниже, если понадобятся.', 'quick_s1_title': 'Положите private key в папку .ssh', 'quick_s1_zip': 'Скопируйте <code>{key_name}</code> из этого ZIP в <code>~/.ssh/</code> (Windows: <code>%USERPROFILE%\\.ssh\\</code>) и ограничьте доступ только вашей учёткой (<code>chmod 600</code> на Linux/macOS).', 'quick_s1_byok': 'Используйте свой существующий приватный ключ (путь в config: <code>{identity}</code>). В ZIP его <strong>нет</strong> — вы отдавали только публичный ключ.', 'quick_s2_title': 'Добавьте блок в SSH config', 'quick_s2_body': 'Откройте или создайте <code>~/.ssh/config</code> (Windows: <code>%USERPROFILE%\\.ssh\\config</code>) и вставьте блок ниже (или допишите файл <code>ssh_config</code> из ZIP).', 'quick_s3_title': 'Подключитесь и оставьте окно открытым', 'quick_s3_body': 'В PowerShell / Terminal:', 'quick_s3_note': 'Команда «зависает» без приглашения — так и должно быть. Окно не закрывайте, пока работаете. Выход — Ctrl+C.', 'quick_s4_title': 'Сервисы доступны как localhost + порт', 'quick_s4_body': 'Пока туннель запущен, удалённый компьютер доступен как <code>localhost</code>. Вместо привычного порта (например RDP <code>3389</code>) подключайтесь на <strong>локальный</strong> порт из таблицы. Не открывайте с ПК адреса вида <code>192.168.x.x</code> — до них можно добраться только через эти порты localhost.', 'quick_s5_title': 'Порт = хост + служба', 'quick_s5_body': 'Каждый локальный порт ведёт на конкретный host:service. Выберите нужную строку:', 'quick_s6_title': 'Нужен доступ по имени (например SSL)?', 'quick_s6_body': 'Если приложению нужно имя, а не IP — добавьте в файл hosts строку с этим именем на <code>127.0.0.1</code>, затем открывайте <code>https://это-имя:&lt;локальный_порт&gt;</code> (или тот порт, который ждёт приложение).', 'quick_hosts_win': 'Windows: файл <code>C:\\Windows\\System32\\drivers\\etc\\hosts</code> от имени администратора', 'quick_hosts_unix': 'Linux / macOS: файл <code>/etc/hosts</code>', 'quick_hosts_ex': '127.0.0.1   app.internal.example', 'ports_title': 'Ваши порты', 'details_summary': 'Подробная инструкция (по желанию)', 'details_hint': 'Содержимое ZIP, синтаксис LocalForward, IDE (VS Code / Cursor), Windows/macOS, типичные ошибки.', 'toc_jump': 'К быстрому старту ↓'}, 'tr': {'hero_title': 'SSH tüneli — kısa rehber', 'hero_intro': 'Tünel, <strong>PC’nizdeki</strong> portları (<code>localhost</code>) iç servislere yönlendirir. Bağlanılacak ayrı “uzak IP” yoktur — yalnızca <code>localhost</code>; <strong>port numarası</strong> host’u ve servisi seçer.', 'quick_title': 'Hızlı başlangıç', 'quick_enough': 'Günlük kullanım için bu yeter. Ayrıntılar aşağıda, gerekirse açın.', 'quick_s1_title': 'Private key’i .ssh klasörüne koyun', 'quick_s1_zip': 'ZIP’teki <code>{key_name}</code> dosyasını <code>~/.ssh/</code> altına kopyalayın (Windows: <code>%USERPROFILE%\\.ssh\\</code>) ve yalnızca sizin hesabınıza izin verin (Linux/macOS: <code>chmod 600</code>).', 'quick_s1_byok': 'Mevcut özel anahtarınızı kullanın (config yolu: <code>{identity}</code>). ZIP’te <strong>yoktur</strong> — yalnızca genel anahtar gönderilmişti.', 'quick_s2_title': 'SSH config’e bu bloğu ekleyin', 'quick_s2_body': '<code>~/.ssh/config</code> dosyasını açın veya oluşturun (Windows: <code>%USERPROFILE%\\.ssh\\config</code>) ve aşağıdaki bloğu yapıştırın (veya ZIP’teki <code>ssh_config</code> dosyasını ekleyin).', 'quick_s3_title': 'Bağlanın ve pencereyi açık bırakın', 'quick_s3_body': 'PowerShell / Terminal’de:', 'quick_s3_note': 'Komut istem olmadan “asılı” kalır — bu normaldir. Çalışırken pencereyi kapatmayın. Bitince Ctrl+C.', 'quick_s4_title': 'Servisler localhost + port olarak erişilir', 'quick_s4_body': 'Tünel açıkken uzak bilgisayar <code>localhost</code> olarak erişilir. Alışılmış port yerine (ör. RDP <code>3389</code>) tablodaki <strong>yerel</strong> porta bağlanın. PC’den <code>192.168.x.x</code> adreslerini açmayın — onlara yalnızca bu localhost portlarıyla ulaşılır.', 'quick_s5_title': 'Port = host + servis', 'quick_s5_body': 'Her yerel port belirli bir host:service’e gider. İhtiyacınız olan satırı seçin:', 'quick_s6_title': 'İsimle erişim mi gerekiyor (ör. SSL)?', 'quick_s6_body': 'Uygulama IP değil isim bekliyorsa hosts dosyasına o ismi <code>127.0.0.1</code>’e yazın, sonra <code>https://o-isim:&lt;yerel_port&gt;</code> açın.', 'quick_hosts_win': 'Windows: <code>C:\\Windows\\System32\\drivers\\etc\\hosts</code> (Yönetici olarak)', 'quick_hosts_unix': 'Linux / macOS: <code>/etc/hosts</code>', 'quick_hosts_ex': '127.0.0.1   app.internal.example', 'ports_title': 'Portlarınız', 'details_summary': 'Ayrıntılı rehber (isteğe bağlı)', 'details_hint': 'ZIP içeriği, LocalForward sözdizimi, IDE (VS Code / Cursor), Windows/macOS, sorun giderme.', 'toc_jump': 'Hızlı başlangıç ↓'}}

for _loc, _upd in _QUICK_OVERLAY.items():
    if _loc in _PACK:
        _PACK[_loc].update(_upd)

